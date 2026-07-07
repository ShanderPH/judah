Expert in Python, Django, Django Ninja, Celery, and scalable RESTful API dev.

Core Principles

- Django-First: use Django built-ins to full capability.
- Code Quality: readable, maintainable; PEP 8 + Django style.
- Naming: descriptive; lowercase_with_underscores for functions/vars.
- Modular Architecture: split project into Django apps for reuse + separation.
- Performance Awareness: weigh scalability + perf in design.

Project Structure

Application Structure

app_name/
├── migrations/        # Database migration files
├── admin.py           # Django admin configuration
├── apps.py            # App configuration
├── models.py          # Database models
├── managers.py        # Custom model managers (when needed)
├── signals.py         # Django signals (when needed)
├── tasks.py           # Celery tasks (if applicable)
├── api.py             # Django Ninja router + endpoints
├── schemas.py         # Pydantic request/response schemas
├── services.py        # Business logic / use cases
└── __init__.py        # Package initialization

API Structure (Django Ninja)

apps/<app>/api.py      # Router, views, and endpoint definitions
apps/<app>/schemas.py  # Pydantic schemas for request/response validation
core/urls.py           # Root NinjaAPI registration

Core Structure

core/
├── settings/          # base / development / production / test
├── urls.py            # NinjaAPI root + router registration
├── celery.py          # Celery app factory
├── wsgi.py            # WSGI entry point
└── asgi.py            # ASGI entry point (used by Uvicorn)

common/
├── exceptions.py      # JudahError hierarchy + Ninja handlers
├── pagination.py      # Custom pagination classes
├── permissions.py     # Base permission classes
├── middleware.py      # RequestLoggingMiddleware
├── logging.py         # Structured logging utilities
├── rate_limit.py      # Redis sliding-window limiter
├── circuit_breaker.py # Process-local circuit breaker
├── cache.py           # Cache decorator and invalidation helpers
└── utils.py           # Reusable utilities

Django/Python Development Guidelines

Views and API Design

- Function-Based Views with Ninja: keep endpoints as plain functions returning schemas.
- RESTful Design: proper HTTP methods + status codes.
- Keep Views Light: views handle requests; business logic lives in services/tasks.
- Consistent Response Format: unified error structure via common.exceptions.

Models and Database

- ORM First: use Django ORM; avoid raw SQL unless perf-critical.
- Business Logic in Models/Services: put domain logic in models, managers, or services.
- Query Optimization: use select_related + prefetch_related for related fetches.
- Database Indexing: index frequently queried fields.
- Transactions: use transaction.atomic() for critical ops.

Schemas and Validation

- Pydantic v2 Schemas: validate + serialize via Ninja schemas.
- Custom Validation: custom validators for complex rules.
- Field-Level Validation: sanitize input via schema fields.
- Nested Schemas: handle nested relationships correctly.

Authentication and Permissions

- JWT Authentication: django-ninja-jwt (HS256) using DJANGO_SECRET_KEY as signing key.
- Custom Permissions: granular helpers in common.permissions (require_role, require_manager_or_admin, etc.).
- Security: CSRF, CORS, input sanitization.

URL Configuration

- URL Patterns: Ninja routers are registered in core/urls.py with api.add_router().
- API Versioning: URL-based versioning (/api/v1/).

Performance and Scalability

Query Optimization

- N+1 Prevention: always use select_related + prefetch_related.
- Query Monitoring: track query count + exec time in dev.
- Database Connection Pooling: conn_max_age tuned per environment.
- Caching Strategy: Django cache framework + Redis for hot data.

Response Optimization

- Pagination: standard pagination on list endpoints.
- Field Selection: clients pick fields, shrink payload where applicable.
- Compression: enable response compression for big payloads.

Error Handling and Logging

Unified Error Responses

{
    "success": false,
    "message": "Error description",
    "errors": {
        "field_name": ["Specific error details"]
    },
    "error_code": "SPECIFIC_ERROR_CODE"
}

Exception Handling

- Custom Exception Handler: global handler for consistent errors (common.exceptions).
- Django Signals: decouple error handling + post-model work.
- HTTP Status Codes: use correct codes (400, 401, 403, 404, 422, 500, etc.).

Logging Strategy

- Structured Logging: structlog for API monitoring + debugging.
- Request/Response Logging: log calls with exec time, user, status.
- Performance Monitoring: log slow queries + bottlenecks.
