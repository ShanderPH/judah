# Stage 1: Builder
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


# Stage 2: Runtime
FROM python:3.14-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY . .

RUN python manage.py collectstatic --noinput || true

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["gunicorn", "core.asgi:application", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-connections", "1000", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
