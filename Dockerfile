# ─── Stage 1: Builder ────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/base.txt
RUN pip install --prefix=/install -r requirements/base.txt


# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_ENV=production \
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# --home /app keeps HOME=/app so gunicorn can write worker heartbeat files.
# The default --system home (/nonexistent) causes "Permission denied" errors
# in the gunicorn control server and can cause workers to appear hung.
RUN addgroup --system appgroup && \
    adduser --system --ingroup appgroup --home /app appuser

COPY . .

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Use shell form so ${PORT} is expanded at runtime by the shell.
# Railway injects PORT; falls back to 8000 for local Docker runs.
# collectstatic and migrate run as Railway releaseCommand (see railway.toml).
CMD gunicorn core.asgi:application \
    -k uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:${PORT}" \
    --workers 2 \
    --worker-connections 1000 \
    --timeout 120 \
    --keep-alive 5 \
    --log-level info \
    --access-logfile - \
    --error-logfile -
