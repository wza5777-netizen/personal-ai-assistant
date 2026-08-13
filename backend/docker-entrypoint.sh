#!/usr/bin/env sh
set -e

# Wait for PostgreSQL to accept connections before applying migrations.
echo "Waiting for PostgreSQL at ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}..."
until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-postgres}" >/dev/null 2>&1; do
  sleep 1
done

# Apply database migrations. Production must NOT rely on create_all().
if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  echo "Applying Alembic migrations..."
  alembic upgrade head
fi

echo "Starting backend: $*"
exec "$@"
