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

## Plano pós-merge da correção de provenance (`0036`)

1. Em PostgreSQL local isolado e sandbox HubSpot (staging Railway, se provisionado), conferir a definição atual de `assignment_logs_assignment_type_check` e os valores distintos de `assignment_logs.assignment_type`. Aplicar `0036` antes de atualizar API, worker e beat. Confirmar que o novo CHECK aceita `auto`, `automatic`, `manual` e os seis valores de `AssignmentProvenance`; conferir `showmigrations support` e os três serviços no mesmo SHA. A migration usa `NOT VALID` seguido de `VALIDATE` antes de retirar o CHECK antigo. Ela registra se havia CHECK anterior para restaurá-lo no reverse; reverse só é permitido se não existirem linhas com valores canônicos exclusivos. O rollback operacional preferido mantém o schema aditivo.
2. Repetir em produção após aprovação de deploy, com captura de definição do CHECK antes/depois, tempo de lock e erros de migration. Usar a identidade `judah_schema_migration` pelo executor privilegiado do Supabase: `judah_production_runtime` não é owner de `assignment_logs` e não pode executar `ALTER TABLE`. Registrar `support.0036` no histórico de migrations antes do deploy Railway; `railway_predeploy` deve encontrá-la aplicada. Suspender promoção se validação falhar ou se API/worker/beat divergirem em SHA. Não realizar backfill junto do deploy.
3. Para `48989048943`, coletar **readback atual** de HubSpot e snapshot local antes de qualquer reprocessamento: owner, stage, `entered_novo_at`, `updated_at`, ocorrências, ciclo, occupancy, logs, attempts e capacidade dos agentes envolvidos. Hoje o snapshot local está `unassigned`, sem log; não reproduzir owner histórico por inferência. Após autorização específica de replay, se HubSpot comprovar owner atual e o ciclo temporal corresponder, chamar uma vez `owner_reconciliation_service.reconcile_ticket("48989048943", source="authorized_reprocess")`, repetir a mesma chamada e comparar identidades/contagens. Se o owner continuar ausente, registrar bloqueio de evidência e não criar `AssignmentLog`. As ocorrências `repair_required` não são retomadas automaticamente pela task; decidir separadamente seu destino com prova temporal do provider. Não chamar `task_repair_assignment_attempts`: não há attempt nesse caso.
4. Canário controlado com ticket de teste autorizado: registrar estado inicial, produzir uma mudança de owner sem attempt nem intenção administrativa, capturar readback imediatamente e executar reconciliação. Exigir exatamente um ciclo da entrada comprovada, uma occupancy ativa no mesmo ciclo, um log `unknown_external` sem attempt, uma transferência `unknown_external` se houver owner anterior, e contador igual à união de ocupações/reservas. Repetir evento/readback; nenhum segundo ciclo, log, transferência ou incremento. Validar provenance de attendant quando houver instância humana vinculada; não inventar presença sem instância.
5. Validar cadeia HubSpot, occurrence, cycle, occupancy/capacity, provenance e métricas por identidade de ticket/ciclo, com tempos e status. Comparar agregação antes/depois sem contar owner anterior sem mensagem humana comprovada. Parar no primeiro `IntegrityError`, duplicata, ciclo divergente, diferença de capacidade, ocorrência pendente envelhecida ou métrica sem evidência. Manter o canário isolado até duas leituras consecutivas convergirem e o retry permanecer idempotente.

**V-03 fecha** somente com prova sandbox documentada de leitura, PATCH autorizado, readback, webhook, associação de ator/mensagem/ticket e lifecycle completo, incluindo duplicata/retry; flag `HUBSPOT_TICKETS_WRITE_VERIFIED=true` e teste live não bastam. **ARCH-03 fecha** somente após migration aplicada/verificada, auditoria por rota/modo demonstrando um writer por fato, ausência de CHECK/choices conflitantes em PostgreSQL, e canário convergente de provenance, capacidade e métricas. Até lá, manter ambos abertos.
