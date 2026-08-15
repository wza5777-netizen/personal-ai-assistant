"""Pytest bootstrap.

Redirect the database to a local SQLite file BEFORE any ``app.*`` module is
imported so ``app.database.session.engine`` is built against SQLite (not the
real Neon/Postgres). This keeps auth + isolation tests fully offline and avoids
touching production columns that only exist after running Alembic migrations.
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./.test_auth_isolation.db"
os.environ["JWT_SECRET"] = "test-secret-shared"
os.environ["APP_ENV"] = "development"
