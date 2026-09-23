# Rollout e rollback

## Pós-deploy

1. Confirmar API, worker e Beat no mesmo SHA do merge e com deploy `SUCCESS`.
2. Executar `repair_assignment_attempts --limit 100` no runtime autoritativo.
3. Executar `bootstrap_support_capacity` com acesso ao Redis público quando o comando for iniciado fora da rede privada do Railway.
4. Confirmar: zero tentativas `repair_required`, zero reservas `held`, sete agentes com capacidade identificada fresca e sem divergência de contador.
5. Confirmar `/readyz` saudável e observar um ciclo de heartbeat/reconciliação sem novos erros.
6. Somente depois desses gates, alterar `SUPPORT_CAPACITY_MODE=enforce` de forma consistente em API, worker e Beat.

## Rollback

- Antes do enforce: reverter o commit do hotfix; não há migração para desfazer.
- Depois do enforce: retornar `SUPPORT_CAPACITY_MODE=shadow` nos três serviços, redeployar e então reverter o commit.
- Não apagar ocupações, reservas ou tentativas; esses registros são evidência operacional para nova reconciliação.
