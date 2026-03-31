.PHONY: run test lint migrate migrations shell superuser docker-up docker-down celery celery-beat help

run:
	uvicorn core.asgi:application --host 0.0.0.0 --port 8000 --reload

test:
	pytest --cov=apps --cov=common --cov-report=html --cov-report=term-missing

lint:
	ruff check . --fix
	ruff format .

lint-check:
	ruff check .
	ruff format --check .

migrate:
	python manage.py migrate

migrations:
	python manage.py makemigrations

shell:
	python manage.py shell_plus --ipython

superuser:
	python manage.py createsuperuser

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-build:
	docker-compose build

docker-logs:
	docker-compose logs -f

celery:
	celery -A core.celery worker --loglevel=info

celery-beat:
	celery -A core.celery beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler

install:
	pip install -r requirements/dev.txt
	pre-commit install

help:
	@echo "Available targets:"
	@echo "  run          - Start Uvicorn development server"
	@echo "  test         - Run pytest with coverage"
	@echo "  lint         - Run Ruff check + format (with fixes)"
	@echo "  lint-check   - Run Ruff without fixes (CI mode)"
	@echo "  migrate      - Apply database migrations"
	@echo "  migrations   - Create new migrations"
	@echo "  shell        - Open Django interactive shell"
	@echo "  superuser    - Create Django superuser"
	@echo "  docker-up    - Start all services via docker-compose"
	@echo "  docker-down  - Stop all docker-compose services"
	@echo "  docker-build - Rebuild docker images"
	@echo "  docker-logs  - Tail docker-compose logs"
	@echo "  celery       - Start Celery worker"
	@echo "  celery-beat  - Start Celery beat scheduler"
	@echo "  install      - Install dev dependencies + pre-commit hooks"
