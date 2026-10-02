from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from engine.app import create_app
from engine.auth.config import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, AuthSettings
from engine.tests.auth_fakes import DEMO_PASSWORD, build_auth_world

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "api.openapi.yaml"
GENERIC_401 = {"detail": "Invalid username or password."}


def _set_cookies(resp) -> dict[str, str]:
    """Set-Cookie header values keyed by cookie name."""
    return {h.split("=", 1)[0]: h for h in resp.headers.get_list("set-cookie")}


async def _login(client, email, password=DEMO_PASSWORD):
    return await client.post("/api/auth/login", json={"username": email, "password": password})


# ---- login -------------------------------------------------------------------


async def test_login_sets_cookies_with_contract_attributes(auth_client, auth_world):
    resp = await _login(auth_client, auth_world.people["student"].email)
    assert resp.status_code == 200
    cookies = _set_cookies(resp)
    session = cookies[SESSION_COOKIE].lower()
    csrf = cookies[CSRF_COOKIE].lower()
    for header in (session, csrf):
        assert "samesite=lax" in header
        assert "path=/" in header
        assert "max-age=43200" in header
        assert "secure" not in header
    assert "httponly" in session
    assert "httponly" not in csrf


async def test_login_cookie_secure_when_configured():
    world = build_auth_world(AuthSettings(cookie_secure=True))
    app = create_app(auth_service=world.service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await _login(c, world.people["student"].email)
    cookies = _set_cookies(resp)
    assert "; secure" in cookies[SESSION_COOKIE].lower()
    assert "; secure" in cookies[CSRF_COOKIE].lower()


async def test_login_csrf_cookie_matches_stored_session(auth_client, auth_world):
    person = auth_world.people["student"]
    await _login(auth_client, person.email)
    (session,) = auth_world.repo.sessions_for(person.id)
    assert auth_client.cookies[CSRF_COOKIE] == session.csrf_token
    assert session.active_role == "student"
    assert session.user_agent


async def test_login_username_is_case_insensitive(auth_client, auth_world):
    resp = await _login(auth_client, auth_world.people["student"].email.upper())
    assert resp.status_code == 200


async def test_login_updates_last_login_and_resets_counter(auth_client, auth_world):
    person = auth_world.people["student"]
    await _login(auth_client, person.email, "wrong")
    await _login(auth_client, person.email, "wrong")
    assert auth_world.repo.credentials[person.id].failed_attempts == 2
    await _login(auth_client, person.email)
    cred = auth_world.repo.credentials[person.id]
    assert cred.failed_attempts == 0
    assert cred.last_login_at == auth_world.clock.now


async def test_login_does_not_require_csrf_header(auth_client, auth_world):
    await _login(auth_client, auth_world.people["student"].email)
    resp = await _login(auth_client, auth_world.people["admin"].email)
    assert resp.status_code == 200


async def test_relogin_revokes_the_previous_session(auth_client, auth_world):
    person = auth_world.people["student"]
    await _login(auth_client, person.email)
    await _login(auth_client, person.email)
    states = sorted(s.revoked_at is None for s in auth_world.repo.sessions_for(person.id))
    assert states == [False, True]


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("nobody@university.edu", DEMO_PASSWORD),
        ("e.smith@university.edu", "wrong password"),
        ("", ""),
    ],
)
async def test_login_failures_return_identical_generic_401(auth_client, username, password):
    resp = await _login(auth_client, username, password)
    assert resp.status_code == 401
    assert resp.json() == GENERIC_401
    assert "set-cookie" not in resp.headers


async def test_unknown_username_still_verifies_a_hash(auth_client, auth_world, monkeypatch):
    calls = []
    passwords = auth_world.service.passwords
    original = passwords.verify_dummy
    monkeypatch.setattr(passwords, "verify_dummy", lambda pw: calls.append(pw) or original(pw))
    await _login(auth_client, "nobody@university.edu", "x")
    assert calls == ["x"]


async def test_credentials_removed_mid_login_get_the_generic_401(auth_client, auth_world,
                                                                  monkeypatch):
    repo = auth_world.repo
    lookup = repo.get_credential_by_username

    async def lookup_then_delete(username):
        cred = await lookup(username)
        repo.credentials.pop(cred.person_id)
        return cred

    monkeypatch.setattr(repo, "get_credential_by_username", lookup_then_delete)
    resp = await _login(auth_client, "e.smith@university.edu")
    assert resp.status_code == 401
    assert resp.json() == GENERIC_401


async def test_login_rejects_malformed_body(auth_client):
    resp = await auth_client.post("/api/auth/login", json={"username": "x"})
    assert resp.status_code == 422


async def test_malformed_login_body_does_not_echo_the_password(auth_client):
    resp = await auth_client.post(
        "/api/auth/login", json={"username": ["not", "a", "string"], "password": "s3cret-pass"}
    )
    assert resp.status_code == 422
    assert "s3cret-pass" not in resp.text
    assert all("input" not in err for err in resp.json()["detail"])


async def test_failed_logins_are_padded_to_the_configured_floor():
    world = build_auth_world(AuthSettings(login_failure_floor_ms=60))
    app = create_app(auth_service=world.service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for username in ("nobody@university.edu", world.people["student"].email):
            started = time.monotonic()
            assert (await _login(c, username, "wrong")).status_code == 401
            assert time.monotonic() - started >= 0.06


# ---- lockout -----------------------------------------------------------------


async def test_five_failures_lock_for_five_minutes_without_revealing_it(auth_client, auth_world):
    person = auth_world.people["student"]
    for _ in range(5):
        resp = await _login(auth_client, person.email, "wrong")
        assert resp.status_code == 401 and resp.json() == GENERIC_401
    cred = auth_world.repo.credentials[person.id]
    assert cred.locked_until == auth_world.clock.now + timedelta(minutes=5)

    locked = await _login(auth_client, person.email)
    assert locked.status_code == 401
    assert locked.json() == GENERIC_401

    auth_world.clock.advance(minutes=4, seconds=59)
    assert (await _login(auth_client, person.email)).status_code == 401

    auth_world.clock.advance(seconds=1)
    assert (await _login(auth_client, person.email)).status_code == 200
    cred = auth_world.repo.credentials[person.id]
    assert cred.failed_attempts == 0 and cred.locked_until is None


async def test_attempts_while_locked_do_not_extend_the_lock(auth_client, auth_world):
    person = auth_world.people["student"]
    for _ in range(5):
        await _login(auth_client, person.email, "wrong")
    until = auth_world.repo.credentials[person.id].locked_until
    auth_world.clock.advance(minutes=3)
    await _login(auth_client, person.email, "wrong")
    assert auth_world.repo.credentials[person.id].locked_until == until


async def test_lockout_honours_configured_limits():
    world = build_auth_world(AuthSettings(login_max_attempts=2, login_lockout_minutes=1))
    app = create_app(auth_service=world.service)
    person = world.people["student"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _login(c, person.email, "wrong")
        await _login(c, person.email, "wrong")
        assert (await _login(c, person.email)).status_code == 401
        world.clock.advance(minutes=1)
        assert (await _login(c, person.email)).status_code == 200


# ---- /me ---------------------------------------------------------------------


def _me_required_keys() -> list[str]:
    spec = yaml.safe_load(CONTRACT.read_text())
    return spec["components"]["schemas"]["Me"]["required"]


async def test_login_returns_me_payload(auth_client, auth_world):
    person = auth_world.people["student"]
    body = (await _login(auth_client, person.email)).json()
    assert set(body) == set(_me_required_keys())
    assert body["person"] == {
        "id": person.id, "display_name": "Emma Smith", "email": person.email
    }
    assert body["roles"] == ["student"]
    assert body["active_role"] == "student"
    assert [e["slug"] for e in body["enrollments"]] == ["cs101", "math201"]
    assert set(body["enrollments"][0]) == {"course_id", "slug", "title", "role"}
    assert body["advisees_count"] == 0
    assert body["home_route"] == "/"
    assert "tutor_chat" in body["capabilities"]
    assert body["effective_ui_policy"] == {}
    assert body["must_change_password"] is False


async def test_me_matches_login_payload(authed_client):
    client = await authed_client("faculty")
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["active_role"] == "faculty"
    assert me.json()["enrollments"][0]["role"] == "faculty"


async def test_me_for_advisor_counts_advisees_and_lists_no_courses(authed_client):
    body = (await (await authed_client("advisor")).get("/api/auth/me")).json()
    assert body["advisees_count"] == 1
    assert body["enrollments"] == []
    assert body["capabilities"]["roster"] == {"scope": "assigned", "access": "read"}


async def test_me_reports_must_change_password(auth_client, auth_world):
    person = auth_world.people["admin"]
    cred = auth_world.repo.credentials[person.id]
    auth_world.repo.credentials[person.id] = type(cred)(**{**cred.__dict__, "must_change": True})
    body = (await _login(auth_client, person.email)).json()
    assert body["must_change_password"] is True


async def test_me_requires_session(auth_client):
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_rejects_garbage_cookie(auth_client):
    auth_client.cookies.set(SESSION_COOKIE, "garbage")
    assert (await auth_client.get("/api/auth/me")).status_code == 401


async def test_me_rejects_expired_session(authed_client, auth_world):
    client = await authed_client("student")
    auth_world.clock.advance(hours=12, seconds=1)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_auth_endpoints_return_503_without_auth_store():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await _login(c, "a@b.c", "x")).status_code == 503
        assert (await c.get("/api/auth/me")).status_code == 503


# ---- sliding cookie refresh --------------------------------------------------


async def test_cookies_resent_only_when_session_slides(authed_client, auth_world):
    client = await authed_client("student")
    auth_world.clock.advance(seconds=30)
    quiet = await client.get("/api/auth/me")
    assert "set-cookie" not in quiet.headers

    auth_world.clock.advance(minutes=2)
    slid = await client.get("/api/auth/me")
    cookies = _set_cookies(slid)
    assert set(cookies) == {SESSION_COOKIE, CSRF_COOKIE}
    assert "max-age=43200" in cookies[SESSION_COOKIE].lower()
    assert "httponly" in cookies[SESSION_COOKIE].lower()


# ---- CSRF --------------------------------------------------------------------


async def test_csrf_missing_header_is_403(authed_client):
    client = await authed_client("student")
    del client.headers[CSRF_HEADER]
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 403


async def test_csrf_mismatched_header_is_403(authed_client):
    client = await authed_client("student")
    client.headers[CSRF_HEADER] = "not-the-token"
    assert (await client.post("/api/auth/role", json={"role": "student"})).status_code == 403


async def test_csrf_non_ascii_header_is_403_not_500(authed_client):
    client = await authed_client("student")
    client.headers[CSRF_HEADER] = b"caf\xe9".decode("latin-1")
    assert (await client.post("/api/auth/role", json={"role": "student"})).status_code == 403


async def test_csrf_applies_to_existing_api_endpoints_with_a_session(authed_client):
    client = await authed_client("student")
    del client.headers[CSRF_HEADER]
    resp = await client.post("/api/approval", json={})
    assert resp.status_code == 403


async def test_csrf_not_required_on_get(authed_client):
    client = await authed_client("student")
    del client.headers[CSRF_HEADER]
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_csrf_not_enforced_without_a_session(auth_client):
    resp = await auth_client.post("/api/approval", json={})
    assert resp.status_code != 403


async def test_csrf_matching_header_passes(authed_client):
    client = await authed_client("student")
    assert (await client.post("/api/auth/role", json={"role": "student"})).status_code == 200


# ---- logout ------------------------------------------------------------------


async def test_logout_revokes_session_and_clears_cookies(authed_client, auth_world):
    client = await authed_client("student")
    auth_world.clock.advance(minutes=5)
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 204
    cookies = _set_cookies(resp)
    assert set(cookies) == {SESSION_COOKIE, CSRF_COOKIE}
    for header in cookies.values():
        assert "max-age=0" in header.lower()
    (session,) = auth_world.repo.sessions_for(auth_world.people["student"].id)
    assert session.revoked_at is not None
    assert (await client.get("/api/auth/me")).status_code == 401


def _assert_clears_both_cookies(resp) -> None:
    cookies = _set_cookies(resp)
    assert set(cookies) == {SESSION_COOKIE, CSRF_COOKIE}
    for header in cookies.values():
        assert "max-age=0" in header.lower()


async def test_logout_without_a_session_still_clears_cookies(auth_client):
    resp = await auth_client.post("/api/auth/logout")
    assert resp.status_code == 204
    _assert_clears_both_cookies(resp)


async def test_logout_with_an_expired_session_still_clears_cookies(authed_client, auth_world):
    client = await authed_client("student")
    auth_world.clock.advance(hours=12, seconds=1)
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 204
    _assert_clears_both_cookies(resp)


async def test_logout_with_a_revoked_session_still_clears_cookies(authed_client, auth_world):
    client = await authed_client("student")
    (session,) = auth_world.repo.sessions_for(auth_world.people["student"].id)
    await auth_world.service.sessions.revoke(session.id)
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 204
    _assert_clears_both_cookies(resp)


# ---- role switch -------------------------------------------------------------


async def test_torres_switches_between_faculty_and_program_lead(authed_client, auth_world):
    client = await authed_client("faculty")
    resp = await client.post("/api/auth/role", json={"role": "program_lead"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_role"] == "program_lead"
    assert "ai_review" in body["capabilities"] and "tutor_chat" not in body["capabilities"]
    assert (await client.get("/api/auth/me")).json()["active_role"] == "program_lead"
    (session,) = auth_world.repo.sessions_for(auth_world.people["faculty"].id)
    assert session.active_role == "program_lead"

    back = await client.post("/api/auth/role", json={"role": "faculty"})
    assert back.status_code == 200 and back.json()["active_role"] == "faculty"


@pytest.mark.parametrize("role", ["student", "advisor", "admin"])
async def test_torres_cannot_switch_to_a_role_she_does_not_hold(authed_client, role):
    client = await authed_client("faculty")
    resp = await client.post("/api/auth/role", json={"role": role})
    assert resp.status_code == 403
    assert (await client.get("/api/auth/me")).json()["active_role"] == "faculty"


async def test_role_switch_rejects_unknown_role(authed_client):
    client = await authed_client("faculty")
    assert (await client.post("/api/auth/role", json={"role": "superuser"})).status_code == 422


async def test_role_switch_does_not_rotate_session_or_csrf(authed_client, auth_world):
    client = await authed_client("faculty")
    before = client.cookies[SESSION_COOKIE], client.cookies[CSRF_COOKIE]
    resp = await client.post("/api/auth/role", json={"role": "program_lead"})
    assert "set-cookie" not in resp.headers
    assert (client.cookies[SESSION_COOKIE], client.cookies[CSRF_COOKIE]) == before


# ---- password change ---------------------------------------------------------


NEW_PASSWORD = "an even longer passphrase"


async def test_password_change_wrong_current_is_400(authed_client):
    client = await authed_client("student")
    resp = await client.post(
        "/api/auth/password",
        json={"current_password": "wrong", "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 400


async def _change(client, current, new=NEW_PASSWORD):
    return await client.post(
        "/api/auth/password", json={"current_password": current, "new_password": new}
    )


async def test_wrong_current_passwords_lock_the_account_and_revoke_the_session(
    authed_client, auth_client, auth_world
):
    client = await authed_client("student")
    person = auth_world.people["student"]
    for _ in range(4):
        assert (await _change(client, "wrong")).status_code == 400
    tripped = await _change(client, "wrong")
    assert tripped.status_code == 401
    _assert_clears_both_cookies(tripped)
    (session,) = auth_world.repo.sessions_for(person.id)
    assert session.revoked_at is not None
    cred = auth_world.repo.credentials[person.id]
    assert cred.locked_until == auth_world.clock.now + timedelta(minutes=5)
    assert (await _login(auth_client, person.email)).json() == GENERIC_401


async def test_password_change_is_refused_while_locked(authed_client, auth_client, auth_world):
    client = await authed_client("student")
    person = auth_world.people["student"]
    for _ in range(5):
        await _login(auth_client, person.email, "wrong")
    assert (await _change(client, DEMO_PASSWORD)).status_code == 400
    auth_world.clock.advance(minutes=5)
    assert (await _login(auth_client, person.email)).status_code == 200


async def test_wrong_current_password_counts_with_failed_logins(
    authed_client, auth_client, auth_world
):
    client = await authed_client("student")
    person = auth_world.people["student"]
    for _ in range(4):
        await _login(auth_client, person.email, "wrong")
    assert (await _change(client, "wrong")).status_code == 401
    assert (await _login(auth_client, person.email)).status_code == 401


async def test_password_change_success_resets_the_failure_count(authed_client, auth_world):
    client = await authed_client("student")
    for _ in range(4):
        await _change(client, "wrong")
    assert (await _change(client, DEMO_PASSWORD)).status_code == 204
    cred = auth_world.repo.credentials[auth_world.people["student"].id]
    assert cred.failed_attempts == 0 and cred.locked_until is None


async def test_wrong_current_password_is_padded_to_the_configured_floor():
    world = build_auth_world(AuthSettings(login_failure_floor_ms=60))
    app = create_app(auth_service=world.service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _login(c, world.people["student"].email)
        c.headers[CSRF_HEADER] = c.cookies[CSRF_COOKIE]
        started = time.monotonic()
        assert (await _change(c, "wrong")).status_code == 400
        assert time.monotonic() - started >= 0.06


async def test_password_change_short_new_password_is_422(authed_client):
    client = await authed_client("student")
    resp = await client.post(
        "/api/auth/password",
        json={"current_password": DEMO_PASSWORD, "new_password": "elevenchars"},
    )
    assert resp.status_code == 422
    assert "elevenchars" not in resp.text


async def test_password_change_revokes_other_sessions_only(authed_client, auth_world):
    first = await authed_client("student")
    second = await authed_client("student")
    resp = await first.post(
        "/api/auth/password",
        json={"current_password": DEMO_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 204
    assert (await first.get("/api/auth/me")).status_code == 200
    assert (await second.get("/api/auth/me")).status_code == 401
    assert auth_world.repo.credentials[auth_world.people["student"].id].must_change is False


async def test_new_password_works_and_old_one_does_not(authed_client, auth_client, auth_world):
    client = await authed_client("student")
    await client.post(
        "/api/auth/password",
        json={"current_password": DEMO_PASSWORD, "new_password": NEW_PASSWORD},
    )
    email = auth_world.people["student"].email
    assert (await _login(auth_client, email)).status_code == 401
    assert (await _login(auth_client, email, NEW_PASSWORD)).status_code == 200


# ---- CORS --------------------------------------------------------------------


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://localhost:3100"])
async def test_cors_preflight_allows_ui_origins_with_csrf_header(auth_client, origin):
    resp = await auth_client.options(
        "/api/auth/logout",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin
    assert resp.headers["access-control-allow-credentials"] == "true"
    assert "x-csrf-token" in resp.headers["access-control-allow-headers"].lower()


async def test_cors_rejects_other_origins(auth_client):
    resp = await auth_client.options(
        "/api/auth/me",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers


async def test_api_docs_are_not_served_by_default(auth_client, monkeypatch):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await auth_client.get(path)).status_code == 404


async def test_api_docs_served_when_enabled(monkeypatch):
    monkeypatch.setenv("ENGINE_API_DOCS", "true")
    world = build_auth_world()
    app = create_app(auth_service=world.service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/openapi.json")).status_code == 200
