# Release conjunto #134 + proof durável — somente planejamento

Nenhuma ação deste runbook foi executada em produção. Nenhum deploy/configuração Railway/HubSpot/Redis de produção foi alterado.

## Gate operacional indispensável

A gravação inline legada do pre-deploy **não pode continuar escrevendo** `{ready, checked_at}` com TTL 86400: o novo reader rejeita proof sem fingerprint/schema. Usar o comando versionado após obter exports autoritativos atuais da configuração **publicada**, preservando as etapas existentes de migrations/preflight. API, worker e beat precisam receber a mesma revisão de `HUBSPOT_PROVIDER_CONFIG_JSON` em secret storage. Manifests reais ficam fora do checkout público. O formato e a preparação estão em `private-contract.md`.

```bash
python manage.py record_hubspot_webhook_readback --published-webhooks /tmp/published-webhooks.json --published-app /tmp/published-app.json
```

Os caminhos acima são os arquivos a produzir pelo passo de readback real do pre-deploy. Não substituir por cópia do manifest desejado nem por export histórico local. O comando não busca nem publica config: valida os exports obtidos pelo mecanismo autoritativo existente e falha no mismatch de qualquer lado.

Durante a preparação do release, Felipe deve revisar a configuração real dos serviços Railway para substituir a gravação inline e impedir writers legados. Nesta etapa não houve leitura de variáveis nem alteração de configuração Railway. Manter `enforce`, capabilities, roster, SAT, capacity e authority. Não adicionar timer que apenas renove checked_at.

## Sequência recomendada

1. Revisar #134 e hotfix como um release único; verificar que HEAD de #134 ainda é 952ca9fd6639a4f66f7782ea9af20c4b6bbb80f3. Se mudar, atualizar integração e repetir gates.
2. Preparar aprovação específica de release/deploy e da alteração operacional de pre-deploy acima. Não promover #134 isoladamente. Suspender triggers automáticos de deploy durante os merges, se existirem.
3. Integrar #134 e depois hotfix em main na mesma janela controlada, preservando os commits por merge (evitar squash/rebase que mude o histórico validado). Conferir árvore final em relação à branch conjunta; se merge alterar código, repetir gates no novo SHA.
4. Fixar um SHA final para API, worker e beat; preflight + exports publicados atuais + comando versionado precisam passar antes de liberar runtime dessa versão. Proof gravado deve ter schema_version=1, ready=true, fingerprint do SHA e TTL=-1.
5. Promover os três serviços para o mesmo SHA somente com autorização. Observar fila, matchmaker, SAT, roster, capabilities, attempts e recovery bounded; não executar replay/repair/backfill nem PATCH real como smoke sem autorização específica.
6. Readiness: age/stale/status/warnings devem aparecer. `hubspot_webhook_config_stale` é warning; missing/invalid/mismatch continuam blockers. Nenhuma rejeição de runtime em produção/produção por falta de proof.

Uma alternativa que reduz passos é um único PR de release contendo a branch conjunta (inclui #134), encerrando #134 como incorporado somente após aprovação. Nunca liberar só metade do release.

## Rollback

Reverter o release completo (#134 + hotfix) para o SHA anterior conhecido em todos os serviços, com autorização separada. Reexecutar readback publicado no fluxo apropriado à versão de rollback; versão antiga volta a ter limite de 24h mesmo se a chave nova não tiver TTL. Não desligar enforce e não usar preenchimento manual da chave como rollback. Rollback planejado, não exercitado em Railway nesta etapa.

## Riscos residuais

- Redis sem TTL remove a expiração arbitrária, mas flush, eviction ou perda de persistência continuam podendo apagar evidência; ausência bloqueia por segurança. Não há garantia de durabilidade de banco transacional.
- Um snapshot validado não detecta alterações publicadas externas posteriores: stale gera warning e pede coleta autoritativa. Não foi criado readback runtime periódico.
- Mudança em qualquer campo ou ordem de array dos manifests completos muda fingerprint e exige novo readback. Canonização ignora ordem das chaves e whitespace de JSON, não ordem dos arrays.
- Em versões simultâneas com contratos privados diferentes, cada reader valida seu fingerprint; divergência bloqueia a versão incompatível. Evitar writers inline/legados durante rollout. O fingerprint agora inclui `contract_version`; obter readback novo antes da promoção, inclusive se app/webhooks não mudaram.
- O comando imprime somente o proof. O CLI `apps.integrations.hubspot.webhook_config` também usa o contrato do ambiente e reporta drift por flags e contagens, sem nomes privados de scopes/propriedades.
