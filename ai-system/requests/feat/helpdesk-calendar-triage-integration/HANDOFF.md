# HANDOFF — Helpdesk Calendar + triagem nativa

## Resumo do implementado

- Calendário publicado integrado ao contexto tipado e ao handoff do sistema nativo do PR #105.
- Regras legadas migradas para regras editáveis, com prioridade, múltiplos intervalos e ausência.
- Mensagens de ausência normalizadas para o contrato de canais do HubSpot.
- `/calendar` redesenhada com largura integral, card de comando único, dias maiores e detalhe/edição em modal.
- BFF e permissões atualizados, incluindo DELETE sem exigência indevida de corpo JSON.

## Arquivos modificados

Principais grupos:

- `apps/support/{models.py,schemas.py,api.py,helpdesk_calendar/,migrations/0028_*.py}`
- `apps/ai_agents/{contracts.py,api/webhooks.py,services/execution.py,services/hubspot.py}`
- `apps/support/agent_sync_service.py`
- `webapp/src/features/helpdesk-calendar/`
- `webapp/src/components/layout/app-shell.tsx`
- `webapp/src/lib/api/{client.ts,bff-policy.ts}`
- `webapp/app/(app)/calendar/`
- testes backend e frontend associados

## Como testar localmente

```powershell
docker compose up -d db redis
.\run.ps1 run
```

Em outro terminal:

```powershell
Set-Location webapp
npm run dev
```

Verificações automatizadas:

```powershell
uv run ruff check .
.venv\Scripts\python.exe run_tests_local.py
Set-Location webapp
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

## Roteiro visual obrigatório

1. Autenticar como manager/admin e abrir `http://127.0.0.1:3000/calendar`.
2. Confirmar que o Status Rail não aparece e que o conteúdo ocupa a largura disponível.
3. Confirmar o card de comando único e alternar mês/semana.
4. Verificar dias com dois intervalos e horários completos, em desktop e viewport estreito.
5. Clicar em um dia, validar o modal e abrir a edição pelo lápis.
6. Editar uma regra migrada, salvar e confirmar atualização da grade/lista.
7. Criar ausência com `**negrito**`, emoji e link; reabrir e validar persistência.
8. Desativar uma regra de teste e confirmar seu desaparecimento da resolução efetiva.

Salvar screenshot/recording em `03-verification/` antes de mudar o STATUS para `DONE`.

## Riscos e áreas frágeis

- A materialização de regras legadas deve ser conferida contra dados reais de staging.
- Mensagens reais dependem das capacidades do canal configurado no HubSpot.
- O transporte de WhatsApp Business nativo é um risco conhecido e não foi validado por esta implementação.
- Regras de mesma prioridade usam UUID como desempate determinístico; orientar operadores a usar prioridades distintas em exceções concorrentes.
- A validação visual permanece pendente porque não havia navegador conectado nesta sessão.

## Integrações críticas para VERIFY

- Snapshot de calendário no webhook e refresh antes do handoff.
- Pipeline/estágio normal versus fora de horário.
- Plain text e rich text de ausência em webchat/custom channel.
- Transporte de WhatsApp Business nativo: o endpoint Conversations legado não possui suporte oficial e precisa de decisão/prova em staging.
- Edição das regras geradas pela migration `0028`.
