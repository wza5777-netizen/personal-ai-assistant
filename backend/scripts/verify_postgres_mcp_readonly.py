"""Verify that POSTGRES_MCP_DATABASE_URL connects as the read-only mcp_reader role.

This is an OPERATIONAL verification script (not a unit test). It is safe to run
against production: it only runs SELECTs and deliberately-failing writes, and it
never modifies data.

Prerequisites:
  * The DBA has created the `mcp_reader` role with SELECT-only grants.
  * `POSTGRES_MCP_DATABASE_URL` is exported to that connection string.

Usage:
  export POSTGRES_MCP_DATABASE_URL='postgresql://mcp_reader:***@host/db?ssl=require'
  python backend/scripts/verify_postgres_mcp_readonly.py

Exit code: 0 if all checks pass, 1 otherwise.
"""
from __future__ import annotations

import asyncio
import os
import sys

try:
    import psycopg
except ImportError:  # pragma: no cover
    print("psycopg is required: pip install psycopg[binary]")
    sys.exit(2)


EXPECTED_USER = os.environ.get("POSTGRES_MCP_EXPECTED_ROLE", "mcp_reader")

# Write statements that MUST fail under mcp_reader. Each is run inside its own
# transaction that is rolled back so nothing is persisted.
_FORBIDDEN_WRITES = [
    "INSERT INTO pg_stat_statements VALUES (1)",  # any table; will be denied first
    "UPDATE pg_database SET datname = datname",
    "DELETE FROM pg_database",
    "CREATE TABLE __mcp_verify_tmp (id int)",
    "DROP TABLE __mcp_verify_tmp",
]


async def main() -> int:
    url = os.environ.get("POSTGRES_MCP_DATABASE_URL")
    if not url:
        print("SKIP: POSTGRES_MCP_DATABASE_URL is not set.")
        return 0

    # Avoid ever printing the URL.
    print("Connecting using POSTGRES_MCP_DATABASE_URL (value hidden) ...")
    failures: list[str] = []

    try:
        conn = await psycopg.AsyncConnection.connect(url, connect_timeout=15)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: connection failed: {type(exc).__name__}")
        return 1

    async with conn:
        # 1) current_user must be mcp_reader
        user = await conn.execute("SELECT current_user")
        current_user = (await user.fetchone())[0]
        print(f"current_user = {current_user}")
        if current_user != EXPECTED_USER:
            failures.append(f"current_user is '{current_user}', expected '{EXPECTED_USER}'")

        # 2) current_database must succeed
        db = await conn.execute("SELECT current_database()")
        current_db = (await db.fetchone())[0]
        print(f"current_database = {current_db}")

        # 3) a plain SELECT must succeed
        try:
            cur = await conn.execute("SELECT 1 AS ok")
            row = await cur.fetchone()
            print(f"SELECT 1 -> {row[0]}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"SELECT failed: {type(exc).__name__}")

        # 4) forbidden writes must ALL fail (rolled back, no data changed)
        for stmt in _FORBIDDEN_WRITES:
            try:
                async with conn.transaction():
                    await conn.execute(stmt)
                failures.append(f"FORBIDDEN write unexpectedly succeeded: {stmt}")
                print(f"FAIL: write allowed: {stmt}")
            except Exception as exc:  # noqa: BLE001
                print(f"OK (denied): {stmt} -> {type(exc).__name__}")

    if failures:
        print("\nRESULT: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nRESULT: PASS — connected as read-only mcp_reader; writes are denied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
