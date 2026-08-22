# JUDAH — Backend Unificado InChurch

JUDAH é o backend Django do Help Desk InChurch. Ele recebe webhooks de forma
durável e mantém o lifecycle operacional de tickets, filas, atribuição,
disponibilidade de agentes, calendário, métricas e integrações compartilhadas.

Identificação de clientes e triagem não são responsabilidades do JUDAH. A
implementação legada foi removida; uma integração posterior delegará essas
decisões ao n8n. Este repositório ainda não contém webhook, contrato, endpoint,
outbox, reconciliação ou placeholder para essa integração futura.

## Responsabilidades atuais

- ingestão durável e idempotente de webhooks HubSpot e Jira;
- lifecycle, auditoria de transições e ciclos de atendimento;
- fila `new_conversations`, conversas atribuídas e encerradas;
- Matchmaker, autoatribuição, capacidade simultânea e status dos agentes;
- `helpdesk_calendar`, ausências e horário de atendimento;
- métricas operacionais e analytics;
- atualização de `hubspot_owner_id` e demais integrações HubSpot compartilhadas;
- execução assíncrona pelo Celery e persistência PostgreSQL/Supabase;
- capacidades independentes de RAG, base de conhecimento e adaptador Salomão.

## Boundary futuro do n8n

Em uma etapa posterior, o n8n será responsável por coleta de dados,
identificação, confirmação de identidade, triagem e geração da decisão entregue
ao JUDAH. A implementação desse boundary não faz parte do estado atual.

## Stack

- Python 3.14
- Django 5.2 LTS e Django Ninja 1.6
- PostgreSQL/Supabase e Redis
- Celery Worker e Celery Beat
- Agno, OpenAI e Pinecone para capacidades de IA independentes
- Railway

## Estrutura principal

```text
apps/
  ai_agents/     # lifecycle compartilhado e capacidades independentes de IA
  analytics/     # métricas e relatórios
  auth_user/     # autenticação e autorização
  integrations/  # HubSpot, Jira, Pinecone, Salomão e Supabase
  knowledge/     # base de conhecimento
  support/       # filas, agentes, calendário, Matchmaker e métricas
  webhooks/      # ingestão, idempotência e dispatch operacional
core/            # settings, URLs, ASGI/WSGI e Celery
docs/            # documentação técnica e arquitetural
```

## Setup local

Pré-requisitos: Python 3.14, PostgreSQL 16+ e Redis.

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements/dev.txt
copy .env.example .env
python manage.py migrate
```

Nunca versione `.env` nem credenciais. Para subir o ambiente pelo fluxo oficial:

```powershell
.\run.ps1 run
```

## Processos

```powershell
python manage.py runserver
celery -A core.celery worker --loglevel=info --queues=celery,ai_tasks
celery -A core.celery beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

O endpoint canônico de HubSpot é `POST /api/v1/webhooks/hubspot/`. Não há
endpoints `/api/v1/ai/` de identificação ou triagem.

## Configuração relevante

As variáveis completas estão em `docs/setup/environment-variables.md`. Grupos
principais:

- Django: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_ENV`;
- banco/cache: `DATABASE_URL`, `REDIS_URL`;
- HubSpot: `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_APP_SECRET` e IDs operacionais;
- atribuição: `AUTO_ASSIGNMENT_ENABLED`, autoridade e limites de capacidade;
- IA independente: `OPENAI_API_KEY`, `PINECONE_API_KEY`,
  `SALOMAO_V1_BASE_URL`.

## Qualidade e testes

O runner oficial força SQLite local e recusa PostgreSQL remoto:

```powershell
.venv\Scripts\python.exe run_tests_local.py
.venv\Scripts\python.exe run_checks.py
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe apps core common
```

Antes de qualquer deploy, valide `manage.py check`, migrations, importação do
Celery, suíte completa e os testes de Matchmaker, filas, agentes, lifecycle e
HubSpot. Testes que possam conectar a banco não local exigem aprovação prévia.

## Segurança operacional

- webhooks HubSpot usam HMAC v1/v3;
- secrets existem somente em variáveis de ambiente;
- logs estruturados não devem conter PII ou credenciais;
- alterações de produção, deploy, push e migrations remotas requerem aprovação;
- nunca execute `DROP` ou `TRUNCATE` em produção sem autorização explícita.

As decisões arquiteturais estão em `docs/architecture/decisions.md`.
