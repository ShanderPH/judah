# Verification results

Executado localmente em Python 3.14, com SQLite privado e credenciais
placeholder. Nenhum comando acessou banco ou serviço remoto.

| Gate | Resultado |
| --- | --- |
| Regressões focadas | 151 passed |
| Suíte completa | 936 passed, 10 skipped |
| Cobertura completa | 90.13% (mínimo 90%) |
| Ruff lint | All checks passed |
| Ruff format | 338 files already formatted |
| Mypy completo | 335 source files, sem erros |
| Django system check | 0 issues |
| Migration drift | No changes detected |
| `git diff --check` | sem erros |

## Cenários de regressão adicionados

- Reabertura de placeholder `QUEUE_PENDING` e instância `CLOSED` em rota de IA.
- Resposta após reabertura de thread fechada com rota atual verificada.
- Supressão de redelivery de um turno já respondido.
- Preservação do estado terminal e do erro original em falha do pipeline.
- Recuperação transacional de colisão da chave de idempotência.
- Preservação do ticket conhecido quando a associação da thread é omitida.
- Supressão segura quando a rota muda, com contexto operacional no log.
- Retries intermediários em `warning` e exaustão em `error`.
- Decisões esperadas fora do expediente em `info`.
- Configuração do Celery preservando os handlers JSON em staging e produção.

## Gate ainda aberto

O smoke real HubSpot permanece pendente até o merge da PR em `main` e o deploy
controlado do SHA exato. A correção não está ativa em nenhum ambiente remoto
antes desse deploy.
