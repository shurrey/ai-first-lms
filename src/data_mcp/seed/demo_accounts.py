"""Print the demo-accounts table (name, username, roles, courses) from the DB.

Never prints or reads passwords; all seeded accounts share SEED_DEMO_PASSWORD.

Usage: uv run python -m data_mcp.seed.demo_accounts [--all]
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any

import asyncpg

from data_mcp.settings import settings

# Spec §4.3 key demo accounts, in display order.
KEY_DEMO_USERNAMES = [
    "emma.smith@student.edu",
    "noah.brown@student.edu",
    "m.torres@university.edu",
    "s.chen@university.edu",
    "e.watson@university.edu",
    "m.patel@university.edu",
    "a.okafor@university.edu",
    "r.hayes@university.edu",
]

_QUERY = """
SELECT p.display_name,
       p.email,
       c.username,
       p.roles,
       COALESCE(
         (SELECT array_agg(split_part(n.title, ' — ', 1) ORDER BY n.title)
            FROM enrollments e JOIN nodes n ON n.id = e.course_node
           WHERE e.person_id = p.id AND n.kind = 'course'),
         '{}') AS courses,
       (SELECT count(*) FROM advisor_assignments a WHERE a.advisor_id = p.id) AS advisees
  FROM persons p
  LEFT JOIN credentials c ON c.person_id = p.id
"""


async def fetch_demo_accounts(
    conn: asyncpg.Connection, all_accounts: bool = False,
) -> list[dict[str, Any]]:
    """Key demo accounts in spec order, or every person (sorted by email) when all_accounts."""
    if all_accounts:
        rows = await conn.fetch(_QUERY + " ORDER BY p.email")
    else:
        rows = await conn.fetch(_QUERY + " WHERE p.email = ANY($1::text[])", KEY_DEMO_USERNAMES)
        rank = {u: i for i, u in enumerate(KEY_DEMO_USERNAMES)}
        rows = sorted(rows, key=lambda r: rank[r["email"]])
    return [_to_account(r) for r in rows]


def _to_account(row: asyncpg.Record) -> dict[str, Any]:
    scope = list(row["courses"])
    if row["advisees"]:
        scope.append(f"{row['advisees']} advisees")
    if "admin" in row["roles"]:
        scope.append("institution")
    return {
        "name": row["display_name"],
        "username": row["username"] or "(no login)",
        "roles": ", ".join(row["roles"]),
        "courses": ", ".join(scope) or "-",
    }


def format_demo_accounts(accounts: list[dict[str, Any]]) -> str:
    headers = {"name": "Name", "username": "Username", "roles": "Roles", "courses": "Courses"}
    widths = {k: max([len(h)] + [len(a[k]) for a in accounts]) for k, h in headers.items()}
    lines = [
        "  ".join(h.ljust(widths[k]) for k, h in headers.items()),
        "  ".join("-" * widths[k] for k in headers),
    ]
    lines += ["  ".join(a[k].ljust(widths[k]) for k in headers) for a in accounts]
    return "\n".join(line.rstrip() for line in lines)


async def main(all_accounts: bool) -> None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        print(format_demo_accounts(await fetch_demo_accounts(conn, all_accounts)))
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print seeded demo accounts")
    parser.add_argument("--all", action="store_true", help="List every seeded person")
    args = parser.parse_args()
    asyncio.run(main(args.all))
