# Hotfix: durabilidade do proof HubSpot

Escopo aprovado pelo usuário: remover expiração silenciosa, preservar enforce e todos os gates. Sem produção.

## Base

- main: 0ca25b842ef55607af210419a8c17c4b56d6074f.
- PR #134: 952ca9fd6639a4f66f7782ea9af20c4b6bbb80f3.
- Worktree isolado /tmp/judah-webhook-proof; alterações locais originais preservadas.
- Hotfix parte de main para validação isolada; integrar HEAD fixado de #134 após essa validação. Nenhum merge em main.

## Decisões

Redis na chave existente, timeout=None, sem migration/componente novo. SHA-256 do JSON canônico da revisão do contrato e dos manifests completos de app e webhooks. A fonte desejada é `HUBSPOT_PROVIDER_CONFIG_JSON`, fornecida por secret storage; nenhum manifest real será restaurado no repositório público. Falta de fingerprint/schema ou ready diferente de True bloqueia. Idade >24h gera observação e warning, nunca validade binária. Falha de runtime e de assignment têm eventos distintos.

## Continuação após remoção dos manifests

Base integrada: `62da400`, contendo #134/952ca9f e main/4ec547d. Worktree desta continuação: `/tmp/judah-proof-private`. A orientação final da conversa referenciada substitui a proposta de preservar contratos públicos por configuração privada, com testes sintéticos. A implementação adapta cinco arquivos de produção, além das configurações de testes e três módulos de regressão; não exige refactor arquitetural, migration nem publicação HubSpot. Configuração ausente/incompleta não pode liberar assignment nem causar erro 500 na readiness. Revisão, app ou webhooks alterados exigem readback novo. A preparação operacional e o release permanecem separados.

Escopo reavaliado (>5 arquivos): seis arquivos de produção são necessários para uma fonte de proof, comando, leitura, gate e dois callers que hoje duplicam o evento incorreto. Testes e evidência complementam o hotfix; nenhum refactor estrutural.

## Critérios de aceitação

1. Proof válido atual ou >24h permite assignment; ausência, invalidade, legacy e mismatch bloqueiam.
2. Snapshot gravado sem TTL destrutivo, checked_at preservado e sem renovação cega.
3. Ambos os exports precisam bater para ready=True; comando falha no drift ou export inválido.
4. Idade/stale/status e razões específicas visíveis; runtime_authority_rejected só para runtime indevido.
5. Fila preservada no bloqueio real; proof antigo não causa skipped_assignment_disabled.
6. Suite completa e gates locais isolados e conjuntos, PostgreSQL local descartável, webapp de #134.
7. Nenhum deploy/mutation/configuração externa.
8. Configuração privada ausente ou malformada bloqueia; readiness explica o motivo sem expor conteúdo.
9. Testes locais/CI usam somente contrato sintético; nenhuma leitura de `hubspot-app/` permanece no código.
