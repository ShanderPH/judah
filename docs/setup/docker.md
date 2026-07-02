# Docker

## Resumo

Como usar Docker Compose para subir toda a stack local do JUDAH (API, PostgreSQL, Redis, Celery Worker, Celery Beat).

## Contexto

O `docker-compose.yml` define uma stack completa para desenvolvimento, com volumes persistentes para Postgres e Redis, healthchecks e variáveis de ambiente carregadas do `.env`.

## Serviços definidos

| Serviço | Imagem/Build | Porta | Função |
|---------|--------------|-------|--------|
| `app` | `Dockerfile` (target `builder`) | `8000` | API Django via Uvicorn com reload |
| `db` | `postgres:16-alpine` | `5432` | Banco de dados PostgreSQL |
| `redis` | `redis:7-alpine` | `6379` | Cache e broker Celery |
| `celery_worker` | `Dockerfile` (target `builder`) | — | Processa tasks assíncronas |
| `celery_beat` | `Dockerfile` (target `builder`) | — | Scheduler periódico |

## Pré-requisitos

- Docker Engine 24+
- Docker Compose 2.20+
- Arquivo `.env` configurado na raiz do projeto (veja [`environment-variables.md`](./environment-variables.md)).

## Subir a stack

```bash
make docker-up
# Equivalente a:
# docker-compose up -d
```

Aguarde os healthchecks do Postgres e Redis.

## Ver logs

```bash
make docker-logs
# Equivalente a:
# docker-compose logs -f
```

## Rebuildar imagens

```bash
make docker-build
# Equivalente a:
# docker-compose build
```

## Parar a stack

```bash
make docker-down
# Equivalente a:
# docker-compose down
```

Para remover também os volumes (apaga dados locais):

```bash
docker-compose down -v
```

## Acessar a API

- API: `http://localhost:8000/api/v1/`
- Docs OpenAPI: `http://localhost:8000/api/v1/docs`
- Admin Django: `http://localhost:8000/admin/`

## Acessar containers

```bash
# Shell do container da API
docker-compose exec app bash

# Shell Django
python manage.py shell_plus --ipython

# Rodar migrações manualmente
docker-compose exec app python manage.py migrate
```

## Dockerfile

O `Dockerfile` é multi-stage:

- `builder`: instala dependências e copia o código.
- A imagem final roda Uvicorn com `core.asgi:application`.

Existem também Dockerfiles especializados:

- `Dockerfile.worker`: entrypoint do Celery worker.
- `Dockerfile.beat`: entrypoint do Celery beat.

## Arquivos relacionados

- [`docker-compose.yml`](../../docker-compose.yml)
- [`Dockerfile`](../../Dockerfile)
- [`Dockerfile.worker`](../../Dockerfile.worker)
- [`Dockerfile.beat`](../../Dockerfile.beat)
- [`Makefile`](../../Makefile)

## Pontos de atenção

- O target `builder` é usado no `docker-compose.yml`; em produção (Railway), o target pode ser diferente.
- O `.env` é montado em todos os containers; certifique-se de que não contém secrets desnecessários para desenvolvimento.
- O volume `postgres_data` persiste dados entre execuções. Use `docker-compose down -v` com cuidado.

## Recomendações

- Use a stack Docker para testar tasks Celery e webhooks localmente.
- Não use Docker Compose em produção; use as configurações do Railway.
- Mantenha os Dockerfiles alinhados com as versões do `requirements/base.txt`.
