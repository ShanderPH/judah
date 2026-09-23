# Diagnóstico de produção

Na abertura de 22/09/2026, as primeiras nove autoatribuições foram distribuídas somente entre dois
agentes: cinco para o owner `92706437` e quatro para o owner `1372450856`. Um terceiro agente ficou
elegível depois da abertura. Como `OPENING_COHORT_BARRIER_MODE=shadow`, a barreira apenas observou a
coorte incompleta e não adiou o consumo da fila.

No mesmo período, mudanças manuais de owner não foram refletidas nos contadores ou no histórico local.
Foram observados 221 webhooks de `hubspot_owner_id`: nenhum continha `previousValue`; 90 continham
`sourceId`, mas esse campo identificava a origem/ator do evento, não o owner anterior.

## Causa raiz corrigida

`task_handle_owner_change` usava `sourceId` como fallback do owner anterior. O stale guard comparava esse
valor com `AssignedConversation.hubspot_owner_id` e descartava a transferência. Em `shadow`, a
reconciliação lia corretamente o owner atual no HubSpot, mas não projetava o contador; o writer legado
era justamente o caminho descartado pelo guard incorreto.

A origem contábil confiável já existe na projeção local bloqueada. O owner atual vem da reconciliação
autoritativa em `shadow`; `previousValue`, quando realmente presente, continua sendo usado somente para
rejeitar eventos atrasados.

## Relação com o rollout da coorte

O hotfix anterior corrigiu o encerramento das coortes quando a fila já estava vazia. Esta ocorrência
confirmou o efeito operacional restante do modo `shadow`: ele não impede que a fila seja consumida antes
de todos os membros iniciais estabilizarem. A ativação de `OPENING_COHORT_BARRIER_MODE=enforce` deve
ocorrer apenas depois do deploy deste hotfix e do smoke descrito no handoff.
