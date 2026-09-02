# Gates de rollout — INCIDENT-48108294672

Este documento é somente um checklist. Ele não autoriza nenhuma operação.

1. Corrigir o gate de `mypy` e obter revisão de código/domínio/security.
2. Autorizar SP-06 read-only e confirmar o projeto/build HubSpot canônico.
3. Implementar/validar INT-01 somente após essa confirmação.
4. Autorizar e executar V-04 em staging/sandbox, com readback e rollback funcional.
5. Autorizar separadamente push/PR, merge e deploy effects-off.
6. Confirmar API/worker/beat no mesmo SHA, migrations/readiness/repair/PII verdes.
7. Autorizar separadamente configuração HubSpot, canário e cada degrau de reativação.
8. Recovery permanece fora do live drain e requer uma autorização por coorte.

Stop conditions: mismatch de schema, freshness ausente, SHA divergente, owner manual sobrescrito, efeito duplicado, capacity drift, aumento de repair, PII em sink, backlog fora da coorte ou health funcional indisponível.

Rollback funcional: desligar effects primeiro, preservar ledger/attempts/fila, reconciliar in-flight por readback e nunca desfazer owner confirmado cegamente.
