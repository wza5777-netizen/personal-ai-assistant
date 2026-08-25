# PostgreSQL MCP — Production Read-Only Security

This document describes the **application-side** read-only integration with the
PostgreSQL MCP Server (`@yawlabs/postgres-mcp`). It is the companion to the
runtime wiring implemented in `app/main.py::_init_postgres_mcp()`.

> **Database roles are provisioned by the DBA — never by this application.**
> The `mcp_reader` role, its `GRANT`s, and default privileges were created
> **by hand** (via Neon SQL Editor / psql), not by application code. The
> application MUST NOT contain any `CREATE ROLE`, `CREATE USER`, `GRANT`,
> `ALTER DEFAULT PRIVILEGES`, or similar DDL/DCL. If those statements are ever
> needed, they are run out-of-band by an administrator.

## Security model — three layers of defense

The read-only guarantee is **defense in depth**. No single layer is trusted
alone.

### Layer 1 — Least-privilege PostgreSQL role (`mcp_reader`)

Created and granted by the DBA only:

```sql
-- Run by the DBA, NOT by the application.
CREATE ROLE mcp_reader LOGIN PASSWORD '...';
GRANT CONNECT          ON DATABASE <db>           TO mcp_reader;
GRANT USAGE            ON SCHEMA public           TO mcp_reader;
GRANT SELECT           ON ALL TABLES    IN SCHEMA public TO mcp_reader;
GRANT SELECT           ON ALL SEQUENCES IN SCHEMA public TO mcp_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES    TO mcp_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO mcp_reader;
```

`mcp_reader` has **only** `SELECT`. It cannot `INSERT` / `UPDATE` / `DELETE` /
`CREATE` / `DROP`. This is the real security boundary.

### Layer 2 — Server read-only mode

The MCP server is launched **without** any write-enabling flag:

```python
env = {"DATABASE_URL": settings.postgres_mcp_database_url}  # ALLOW_WRITES is NEVER set
```

`ALLOW_WRITES=1` (or any equivalent) is **deliberately never** injected. The
MCP server therefore stays in its default read-only mode. This is a
*convenience* guard, not the primary boundary — see Layer 1.

### Layer 3 — Application RBAC (`database:read`)

Every PostgreSQL MCP tool is registered with:

```python
required_permission = "database:read"
```

`ToolGateway.check_permission()` runs **before** the call is forwarded to the
MCP client. A request without `database:read` is rejected with
`permission_denied` and the MCP client is never invoked. There is **no**
`database:write` capability and no write-mode toggle in this codebase.

## Configuration

| Env var                     | Default | Notes                                            |
|-----------------------------|---------|--------------------------------------------------|
| `POSTGRES_MCP_ENABLED`      | `false` | Opt-in. Set `true` to enable.                    |
| `POSTGRES_MCP_DATABASE_URL` | _empty_ | **Independent** read-only connection string.     |
| `POSTGRES_MCP_TIMEOUT`      | `30`    | Subprocess / call timeout (seconds).             |

### Independence requirement

`POSTGRES_MCP_DATABASE_URL` is **fully independent** of the application's own
`DATABASE_URL`. There is **no fallback** to `DATABASE_URL` — if
`POSTGRES_MCP_DATABASE_URL` is empty, Postgres MCP initialization is skipped
(with a `postgres_mcp_database_url_missing` warning). The application's
`DATABASE_URL` is never used for the MCP server.

### Secret handling

- `POSTGRES_MCP_DATABASE_URL` is read **only** from the environment / Settings.
- It is **never** hard-coded, **never** written into `.env.example` with a real
  value, **never** logged, and **never** placed in an observability payload.
- The connection string is injected into the MCP subprocess **environment**
  only — **never** as a command-line argument.
- `.env.example` ships `POSTGRES_MCP_DATABASE_URL=` (empty).

## Startup failure isolation

A Postgres MCP failure (connection refused, auth failure, timeout, subprocess
crash) is caught and logged **without secrets**
(`postgres_mcp_initialization_failed`, `error_type` only). It does **not** break
FastAPI startup, GitHub MCP, Time MCP, or native tools. Other servers are
initialized independently in `_initialize_mcp_servers()`.

## Verification

Run `backend/scripts/verify_postgres_mcp_readonly.py` after exporting
`POSTGRES_MCP_DATABASE_URL` to a real `mcp_reader` connection string:

```bash
export POSTGRES_MCP_DATABASE_URL='postgresql://mcp_reader:***@ep-xxx.aws.neon.tech/neondb?ssl=require'
python backend/scripts/verify_postgres_mcp_readonly.py
```

Expected:

- `SELECT current_user`       → `mcp_reader`
- `SELECT current_database()` → `<db>` (succeeds)
- `SELECT ...`                → succeeds
- `INSERT` / `UPDATE` / `DELETE` / `CREATE TABLE` / `DROP TABLE` → **fail**
  (permission denied), and **no production data is modified**.

## What this codebase will NEVER do

- Create or alter PostgreSQL roles.
- Issue `GRANT` / revoke privileges.
- Enable MCP write mode or `database:write`.
- Fall back to `DATABASE_URL` for the MCP server.
- Log or echo the connection string / username / password.
