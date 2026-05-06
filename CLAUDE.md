Expert in Python, Django, scalable RESTful API dev.

Core Principles

\- Django-First: use Django built-ins to full capability

\- Code Quality: readable, maintainable; PEP 8 + Django style

\- Naming: descriptive; lowercase_with_underscores for functions/vars

\- Modular Architecture: split project into Django apps for reuse + separation

\- Performance Awareness: weigh scalability + perf in design

Project Structure

Application Structure

app\_name/

├── migrations/        # Database migration files

├── admin.py           # Django admin configuration

├── apps.py            # App configuration

├── models.py          # Database models

├── managers.py        # Custom model managers

├── signals.py         # Django signals

├── tasks.py           # Celery tasks (if applicable)

└── \_\_init\_\_.py        # Package initialization

API Structure

api/

└── v1/

&#x20;   ├── app\_name/

&#x20;   │   ├── urls.py            # URL routing

&#x20;   │   ├── serializers.py     # Data serialization

&#x20;   │   ├── views.py           # API views

&#x20;   │   ├── permissions.py     # Custom permissions

&#x20;   │   ├── filters.py         # Custom filters

&#x20;   │   └── validators.py      # Custom validators

&#x20;   └── urls.py                # Main API URL configuration

Core Structure

core/

├── responses.py       # Unified response structures

├── pagination.py      # Custom pagination classes

├── permissions.py     # Base permission classes

├── exceptions.py      # Custom exception handlers

├── middleware.py      # Custom middleware

├── logging.py         # Structured logging utilities

└── validators.py      # Reusable validators

Configuration Structure

config/

├── settings/

│   ├── base.py        # Base settings

│   ├── development.py # Development settings

│   ├── staging.py     # Staging settings

│   └── production.py  # Production settings

├── urls.py            # Main URL configuration

└── wsgi.py           # WSGI configuration

Django/Python Development Guidelines

Views and API Design

\- Class-Based Views: use CBVs with DRF APIViews

\- RESTful Design: strict REST, proper HTTP methods + status codes

\- Keep Views Light: views handle requests; business logic in models, managers, services

\- Consistent Response Format: unified structure for success + error

Models and Database

\- ORM First: use Django ORM; avoid raw SQL unless perf-critical

\- Business Logic in Models: put logic in models + custom managers

\- Query Optimization: use select\_related + prefetch\_related for related fetches

\- Database Indexing: index frequently queried fields

\- Transactions: use transaction.atomic() for critical ops

Serializers and Validation

\- DRF Serializers: validate + serialize via DRF

\- Custom Validation: custom validators for complex rules

\- Field-Level Validation: sanitize input via serializer fields

\- Nested Serializers: handle nested relationships correctly

Authentication and Permissions

\- JWT Authentication: djangorestframework\_simplejwt for JWT auth

\- Custom Permissions: granular permission classes per role

\- Security: CSRF, CORS, input sanitization

URL Configuration

\- URL Patterns: clean urlpatterns; path() maps routes to views

\- Nested Routing: include() for modular URLs

\- API Versioning: URL-based versioning preferred

Performance and Scalability

Query Optimization

\- N+1 Prevention: always use select\_related + prefetch\_related

\- Query Monitoring: track query count + exec time in dev

\- Database Connection Pooling: pool connections for high traffic

\- Caching Strategy: Django cache framework + Redis/Memcached for hot data

Response Optimization

\- Pagination: standard pagination on all list endpoints

\- Field Selection: clients pick fields, shrink payload

\- Compression: enable response compression for big payloads

Error Handling and Logging

Unified Error Responses

{

&#x20;   "success": false,

&#x20;   "message": "Error description",

&#x20;   "errors": {

&#x20;       "field\_name": \["Specific error details"]

&#x20;   },

&#x20;   "error\_code": "SPECIFIC\_ERROR\_CODE"

}

Exception Handling

\- Custom Exception Handler: global handler for consistent errors

\- Django Signals: decouple error handling + post-model work

\- HTTP Status Codes: use correct codes (400, 401, 403, 404, 422, 500, etc.)

Logging Strategy

\- Structured Logging: for API monitoring + debugging

\- Request/Response Logging: log calls with exec time, user, status

\- Performance Monitoring: log slow queries + bottlenecks
