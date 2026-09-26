# Causa raiz — fechamento live após PR #127

O campo `hs_v2_date_entered_*` vem da HubSpot CRM API como ISO-8601 UTC. No caso observado, `entered_novo_at=2026-09-26T12:04:38.221Z` e `entered_closed_at=2026-09-26T16:08:57.952Z`. `HubSpotClient.get_ticket_details()` entregava essas strings diretamente. `_provider_decision()` enviava `entered_novo_at` para `parse_stage_entry_timestamp()`, cujo contrato é exclusivamente epoch-ms de webhook. O fechamento válido era classificado como `identity_unavailable` antes da materialização.

O mesmo formato bruto alcançava `owner_reconciliation_service` ao abrir ciclos e ao aplicar fechamentos, além da busca da fila NOVO. A correção ocorre em `apps/integrations/hubspot/client.py`: respostas CRM entregam `datetime` UTC aware. Valor CRM presente, malformado ou sem timezone falha na fronteira; ausência continua `None`. O parser de webhook permanece estrito.

Nenhum reparo histórico ou escrita em produção faz parte deste hotfix.
