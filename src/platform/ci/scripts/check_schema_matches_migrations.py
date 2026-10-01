#!/usr/bin/env python3
"""Check that `alembic upgrade head` builds exactly the schema in contracts/db-schema.sql.

Connects with LMS_DATABASE_URL (any database on the target server; the role
needs CREATEDB), creates two throwaway lms_scratch_schemacheck_* databases,
builds one from the contract and one with Alembic, compares their catalogs and
drops both. That database's contents are never read or changed.

--live-url additionally compares the contract with an existing database, using
read-only catalog queries only.

Exit codes: 0 schemas match, 1 differences found, 2 setup or migration error.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import asyncpg

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_SQL = REPO_ROOT / "contracts" / "db-schema.sql"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
SCRATCH_PREFIX = "lms_scratch_schemacheck_"
IGNORED_TABLES = {"alembic_version"}

Snapshot = dict[str, dict[str, Any]]

_QUERIES: dict[str, str] = {
    "extensions": """
        SELECT extname AS key, '' AS value FROM pg_extension WHERE extname <> 'plpgsql'
    """,
    "enums": """
        SELECT t.typname AS key,
               array_agg(e.enumlabel ORDER BY e.enumsortorder)::text AS value
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public'
        GROUP BY t.typname
    """,
    "tables": """
        SELECT c.relname AS key,
               string_agg(a.attname, ', ' ORDER BY a.attnum) AS value
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
        GROUP BY c.relname
    """,
    "columns": """
        SELECT c.relname || '.' || a.attname AS key,
               format_type(a.atttypid, a.atttypmod)
               || CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE ' NULL' END
               || coalesce(' DEFAULT ' || pg_get_expr(d.adbin, d.adrelid), '') AS value
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v')
    """,
    "constraints": """
        SELECT cl.relname || '.' || co.conname AS key,
               co.contype::text || ' ' || pg_get_constraintdef(co.oid) AS value
        FROM pg_constraint co
        JOIN pg_class cl ON cl.oid = co.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = 'public'
    """,
    "indexes": """
        SELECT indexname AS key, indexdef AS value
        FROM pg_indexes WHERE schemaname = 'public'
    """,
    "views": """
        SELECT c.relname AS key, pg_get_viewdef(c.oid, true) AS value
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm')
    """,
    "sequences": """
        SELECT c.relname AS key, s.seqtypid::regtype::text AS value
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_sequence s ON s.seqrelid = c.oid
        WHERE n.nspname = 'public'
    """,
    "triggers": """
        SELECT cl.relname || '.' || t.tgname AS key, pg_get_triggerdef(t.oid) AS value
        FROM pg_trigger t
        JOIN pg_class cl ON cl.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = 'public' AND NOT t.tgisinternal
    """,
}


def _is_ignored(category: str, key: str) -> bool:
    table = key.split(".", 1)[0]
    if category in ("tables", "columns", "constraints", "triggers"):
        return table in IGNORED_TABLES
    if category == "indexes":
        return key.startswith("alembic_version")
    return False


async def snapshot(url: str, *, read_only: bool = False) -> Snapshot:
    conn = await asyncpg.connect(url)
    try:
        tx = conn.transaction(readonly=read_only)
        await tx.start()
        try:
            result: Snapshot = {}
            for category, sql in _QUERIES.items():
                rows = await conn.fetch(sql)
                result[category] = {
                    r["key"]: r["value"] for r in rows if not _is_ignored(category, r["key"])
                }
            return result
        finally:
            await tx.rollback()
    finally:
        await conn.close()


def diff(expected: Snapshot, actual: Snapshot) -> list[str]:
    lines: list[str] = []
    for category in _QUERIES:
        exp, act = expected.get(category, {}), actual.get(category, {})
        for key in sorted(exp.keys() - act.keys()):
            lines.append(f"[{category}] missing: {key} = {exp[key]}")
        for key in sorted(act.keys() - exp.keys()):
            lines.append(f"[{category}] extra:   {key} = {act[key]}")
        for key in sorted(exp.keys() & act.keys()):
            if exp[key] != act[key]:
                lines.append(
                    f"[{category}] differs: {key}\n"
                    f"    expected: {exp[key]}\n"
                    f"    actual:   {act[key]}"
                )
    return lines


def _with_database(url: str, dbname: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{dbname}", parts.query, parts.fragment))


async def _create_db(admin_url: str, name: str) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def _drop_db(admin_url: str, name: str) -> None:
    if not name.startswith(SCRATCH_PREFIX):
        raise ValueError(f"Refusing to drop non-scratch database {name!r}")
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


async def _apply_contract(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(CONTRACT_SQL.read_text())
    finally:
        await conn.close()


def _alembic_upgrade(url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "LMS_DATABASE_URL": url},
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade head failed:\n{result.stderr}")


def _report(title: str, lines: list[str]) -> bool:
    if lines:
        print(f"{title}: {len(lines)} difference(s)")
        for line in lines:
            print(f"  {line}")
        return False
    print(f"{title}: no differences")
    return True


async def run(admin_url: str, live_url: str | None) -> int:
    token = secrets.token_hex(4)
    contract_db = f"{SCRATCH_PREFIX}{token}_contract"
    alembic_db = f"{SCRATCH_PREFIX}{token}_alembic"
    created: list[str] = []
    try:
        for name in (contract_db, alembic_db):
            await _create_db(admin_url, name)
            created.append(name)

        contract_url = _with_database(admin_url, contract_db)
        alembic_url = _with_database(admin_url, alembic_db)
        await _apply_contract(contract_url)
        await asyncio.to_thread(_alembic_upgrade, alembic_url)

        contract_snap = await snapshot(contract_url)
        ok = _report(
            "contract vs alembic head", diff(contract_snap, await snapshot(alembic_url))
        )
        if live_url:
            live_snap = await snapshot(live_url, read_only=True)
            ok = _report("contract vs live", diff(contract_snap, live_snap)) and ok
        return 0 if ok else 1
    finally:
        for name in created:
            await _drop_db(admin_url, name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--admin-url",
        default=os.environ.get("LMS_DATABASE_URL"),
        help="Connection URL used to create/drop scratch databases (default: $LMS_DATABASE_URL)",
    )
    parser.add_argument(
        "--live-url",
        help="Also compare the contract against this database (read-only queries)",
    )
    args = parser.parse_args()
    if not args.admin_url:
        print("error: set LMS_DATABASE_URL or pass --admin-url", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run(args.admin_url, args.live_url))
    except (RuntimeError, OSError, asyncpg.PostgresError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
