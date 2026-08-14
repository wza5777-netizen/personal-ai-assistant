# ---------- Builder stage ----------
FROM python:3.12-slim AS builder

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Install uv (single static binary).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy only what uv needs to resolve+install, then sync into .venv.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ---------- Runtime stage ----------
FROM python:3.12-slim AS runtime

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    LOG_LEVEL=INFO \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl postgresql-client && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home /app app

# Bring in the uv-managed virtualenv from the builder.
COPY --from=builder /app/.venv /app/.venv
# Application code + alembic (needed for `alembic upgrade head` in prod).
COPY . .

RUN chown -R app:app /app
USER app

EXPOSE 8000

# Run migrations, then start the server. This keeps production free of
# Base.metadata.create_all() reliance.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
