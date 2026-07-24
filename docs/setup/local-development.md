# Desenvolvimento Local

## Resumo

Guia para configurar e executar o JUDAH localmente, incluindo dependências, variáveis de ambiente, migrações e execução dos serviços (API, worker, beat).

## Contexto

O JUDAH é desenvolvido em Python 3.14, Django 5.2 e usa PostgreSQL + Redis. O frontend é um app Next.js separado em `webapp/`.

## Pré-requisitos

| Dependência | Versão | Notas |
|-------------|--------|-------|
| Python | 3.14 (exata) | Obrigatório; `pyproject.toml` exige `>=3.14` |
| PostgreSQL | 16 | Pode ser local ou Supabase |
| Redis | 7 | Broker, cache e session store |
| Docker + Compose | latest | Opcional, mas recomendado |
| Node.js | 20+ | Apenas para o frontend (`webapp/`) |

## 1. Clone e virtual environment

```bash
git clone <repo-url>
cd judah
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate
```

## 2. Instalar dependências

```bash
make install
# Equivalente a:
# pip install -r requirements/dev.txt
# pre-commit install
```

## 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` com as credenciais. Veja [`environment-variables.md`](./environment-variables.md) para a lista completa.

Mínimo para desenvolvimento:

```bash
DJANGO_SECRET_KEY=dev-secret-key-change-me
DJANGO_DEBUG=True
DATABASE_URL=postgresql://judah:judah_dev_password@localhost:5432/judah_dev
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=sk-...
HUBSPOT_ACCESS_TOKEN=...
HUBSPOT_APP_SECRET=...
```

## 4. Criar banco de dados (se usar Postgres local)

```bash
createdb judah_dev
```

Ou use o container do Docker Compose.

## 5. Migrações e superusuário

```bash
make migrate
make superuser
```

## 6. Executar a API

```bash
make run
# Equivalente a:
# uvicorn core.asgi:application --host 0.0.0.0 --port 8000 --reload
```

Acesse:

- API: `http://localhost:8000/api/v1/`
- OpenAPI/Swagger: `http://localhost:8000/api/v1/docs`
- Django Admin: `http://localhost:8000/admin/`

## 7. Executar Celery Worker

Em outro terminal:

```bash
make celery
# Equivalente a:
# celery -A core.celery worker --loglevel=info --queues=celery,ai_tasks
```

## 8. Executar Celery Beat

Em um terceiro terminal:

```bash
make celery-beat
# Equivalente a:
# celery -A core.celery beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

## 9. Executar o frontend

```bash
cd webapp
npm install
# Crie .env.local com JUDAH_API_URL=http://127.0.0.1:8000/api/v1
npm run dev
```

Acesse `http://localhost:3000`.

> **Nota:** o frontend Next.js está em `webapp/` e não faz parte do setup Python/Django.

## 10. Stack completa com Docker Compose

Se preferir subir tudo de uma vez:

```bash
make docker-up
```

Isso sobe: API (porta 8000), PostgreSQL (5432), Redis (6379), Celery Worker e Celery Beat.

```bash
make docker-logs   # acompanhar logs
make docker-down   # parar tudo
```

## Arquivos relacionados

- [`.env.example`](../../.env.example): template de variáveis.
- [`Makefile`](../../Makefile): comandos de desenvolvimento.
- [`run.ps1`](../../run.ps1): comandos equivalentes no Windows.
- [`docker-compose.yml`](../../docker-compose.yml): stack local.
- [`requirements/dev.txt`](../../requirements/dev.txt): dependências de desenvolvimento.
- [`webapp/README.md`](../../webapp/README.md): setup do frontend.

## Pontos de atenção

- **Nunca use `DATABASE_URL` apontando para produção ao rodar testes.** O `conftest.py` deleta linhas das tabelas de suporte antes de cada teste.
- O `DJANGO_DEBUG=True` habilita bypass de assinatura de webhook quando `HUBSPOT_APP_SECRET` está vazio. Não use em produção.
- A API de IA (`/api/v1/ai/`) só é montada quando `AI_ROUTING_ENABLED=true`.
- O target `agentos` de `run.ps1` (`apps.ai_agents.agent_os:app`) refere-se a um arquivo que **não existe** no repositório atual.
- O pre-commit roda apenas `ruff`; `mypy` não é executado automaticamente apesar de listado no `AGENTS.md` como tooling obrigatório.
- A cobertura mínima do CI é 50%, enquanto `pyproject.toml` define 80%.

## Recomendações

- Use Docker Compose para reduzir diferenças entre ambientes.
- Mantenha um `.env` separado para cada ambiente (dev, staging, prod).
- Configure o pre-commit para garantir lint e formatação antes de cada commit.
