# Runbook de release e rollback — proposta, sem execução remota

## Pré-condições

1. Aplicar migrations aditivas `0033`, `0034` e `0035` primeiro em staging; confirmar RLS/trigger, runtime grants e nulidade dos horários externos sem prova. API, worker e beat devem usar o mesmo SHA.
2. Validar paths, payloads e scopes mínimos em sandbox HubSpot, inclusive um PATCH de ticket de teste autorizado. Manter `HUBSPOT_TICKETS_WRITE_VERIFIED=false` até a evidência ser anexada.
3. Obter exports **reais da configuração publicada** de app e webhooks e comparar com os manifestos locais usando `python manage.py record_hubspot_webhook_readback --published-webhooks <export-webhooks.json> --published-app <export-app.json>`. Guardar os exports fora do repo se contiverem dados sensíveis.
4. Conferir `HUBSPOT_N1_TEAM_ID`, preflight obrigatório, roster completo/fresco, pending dentro do limite, contagens por ciclo e ARCH-03. Ausência de evidência bloqueia promoção.

## Sequência

1. Deploy aditivo com `HUBSPOT_PROVIDER_CONTRACT_MODE=off`; confirmar API/worker/beat no mesmo SHA. Sem backfill.
2. Mudar para `shadow` depois do preflight; comparar roster antigo/novo e ocorrências com projeção efetiva durante janela representativa. Registrar cutover timestamp, coorte, writers ativos, pendências e 429/5xx.
3. Promover para `enforce` somente após sandbox, readback publicado, ARCH-03 e métricas por ciclo aprovados, com `SUPPORT_CAPACITY_MODE=enforce`. O gate de assignment exige writer canônico de capacidade, capability, roster e webhook readback frescos.
4. Após estabilidade live, executar apenas dry-run histórico por coorte delimitada. `--apply` exige autorização própria por lote.

## Stop conditions

Parar promoção em 401/403 obrigatório, roster parcial, drift de webhook, pending envelhecido, dois fechamentos, ciclo antigo ressuscitado, occupancy/capacidade divergentes, PATCH duplicado, 429 sustentado ou SHAs diferentes. Não liberar reserva/efeito ambíguo sem readback conclusivo.

## Rollback

Suspender efeitos de owner primeiro. Voltar modo para `shadow` ou `off`, mantendo ledger, ocorrências e migrations aditivas. Reconciliar attempts `external_applied` e reservas por leitura do provider antes de reabrir writer. Reverter adapter só se o contrato anterior continuar suportado e o preflight estiver verde. Reverse de dados não é rollback padrão de produção.

**Autorização separada:** publicar app/scopes, mutation HubSpot, migrations remotas, deploy, dry-run em dados reais e qualquer `--apply` dependem de decisão específica do Felipe conforme o master plan e `AGENTS.md` §11.
