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

# Run collectstatic at build time so /app/staticfiles exists in the runtime
# image. Railway's releaseCommand runs in an ephemeral container whose
# filesystem is NOT shared with the runtime container — files written
# during `releaseCommand` (e.g. collectstatic) vanish before the app starts.
# DJANGO_ENV=development is used at build only because production.py refuses
# to import without DATABASE_URL — the static manifest is the same either way.
RUN DJANGO_ENV=development \
    DJANGO_SECRET_KEY=build-time-only \
    python manage.py collectstatic --noinput --clear || mkdir -p /app/staticfiles

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# The launcher runs migrations before accepting traffic. On Render it also
# embeds one low-memory Celery worker and beat because Free instances do not
# support a separate background-worker service. Other platforms keep their
# dedicated worker/beat containers and only launch Gunicorn here.
CMD ["python", "scripts/start_service.py"]
