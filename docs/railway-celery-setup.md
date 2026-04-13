# Configuração do Celery no Railway

Este documento descreve como configurar os serviços Celery Worker e Celery Beat no Railway para o projeto Judah.

## Arquitetura

O projeto requer 3 serviços no Railway:

| Serviço | Dockerfile | Função |
|---------|------------|--------|
| `judah-web` | `Dockerfile` | Servidor web (Gunicorn + Uvicorn) |
| `judah-worker` | `Dockerfile.worker` | Celery Worker (executa tasks) |
| `judah-beat` | `Dockerfile.beat` | Celery Beat (agenda tasks periódicas) |

## Passo a Passo para Criar os Serviços

### 1. Acesse o Dashboard do Railway

1. Vá para https://railway.app/dashboard
2. Selecione o projeto **judah-production**

### 2. Criar o Serviço Worker

1. Clique em **"+ New"** → **"GitHub Repo"**
2. Selecione o repositório `ShanderPH/judah`
3. Nas configurações do serviço:
   - **Name**: `judah-worker`
   - **Root Directory**: `/` (raiz)
   - **Config Path**: `railway.worker.toml`
4. Adicione as **mesmas variáveis de ambiente** do serviço web:
   - `DATABASE_URL`
   - `REDIS_URL`
   - `DJANGO_SECRET_KEY`
   - `HUBSPOT_ACCESS_TOKEN`
   - `HUBSPOT_APP_SECRET`
   - (todas as outras variáveis necessárias)
5. Clique em **Deploy**

### 3. Criar o Serviço Beat

1. Clique em **"+ New"** → **"GitHub Repo"**
2. Selecione o repositório `ShanderPH/judah`
3. Nas configurações do serviço:
   - **Name**: `judah-beat`
   - **Root Directory**: `/` (raiz)
   - **Config Path**: `railway.beat.toml`
4. Adicione as **mesmas variáveis de ambiente** do serviço web
5. Clique em **Deploy**

### 4. Verificar os Logs

Após o deploy, verifique os logs de cada serviço:

**Worker:**
```
[INFO] celery@xxx ready.
[INFO] Task support.task_poll_hubspot_agent_status received
```

**Beat:**
```
[INFO] beat: Starting...
[INFO] Scheduler: Sending due task poll-hubspot-agent-status
```

## Tasks Agendadas

As seguintes tasks são executadas automaticamente pelo Celery Beat:

| Task | Frequência | Descrição |
|------|------------|-----------|
| `task_poll_hubspot_agent_status` | A cada 3 minutos | Sincroniza status dos agentes do HubSpot |
| `task_sync_hubspot_team_members` | Diário às 06:00 | Sincroniza membros do time N1 |
| `task_aggregate_queue_metrics` | Diário às 00:05 | Agrega métricas da fila |
| `task_sync_novo_stage_tickets` | Diário às 08:00 | Sincroniza tickets no estágio NOVO |

## Troubleshooting

### Verificar se o Worker está processando tasks

```bash
# Via Railway CLI
railway logs -s judah-worker
```

### Verificar se o Beat está agendando tasks

```bash
railway logs -s judah-beat
```

### Forçar execução manual de uma task

```python
# Via Django shell
from apps.support.tasks import task_poll_hubspot_agent_status
result = task_poll_hubspot_agent_status.delay()
print(result.get())
```

## Variáveis de Ambiente Compartilhadas

Use **Railway Service Variables** ou **Shared Variables** para evitar duplicação:

1. No projeto, vá em **Settings** → **Shared Variables**
2. Adicione as variáveis comuns
3. Referencie nos serviços com `${{shared.VARIABLE_NAME}}`
