# Revisão independente

2026-09-17. Revisor: sub-agent `security_review`, somente leitura, distinto do
implementador. Inspecionou os cinco arquivos de produção e regressões do hotfix.
Não substitui a revisão humana exigida para merge.

## Achado e resolução

P2 em SEC-04: decodeURIComponent recursivo rejeitava percent literal legítimo,
por exemplo `/metrics?q=100%25`. Reproduzido pelo implementador: **2 failed,
24 passed** no arquivo refresh-route.test.ts antes da correção.

Correção: validar encoding original uma vez e inspecionar escapes percentuais
nas formas subsequentes sem interpretar percent literal como erro de sintaxe.
A URL original é usada no redirect depois da comparação de origem. Acrescentados
casos positivos de percent em query/path/fragment e UTF-8.

Resultado focado final: **38 passed**. Revisor reinspecionou o diff final e
encerrou sem outros achados bloqueantes. Sua revisão foi estática; os testes
foram executados pelo implementador e os resultados estão no relatório de gates.

## Pontos conferidos

- Decorators de autorização não alteram contratos paginados.
- Capability precede configuração e chamada HubSpot.
- Exceções do readiness não são serializadas; request ID corresponde ao middleware.
- Redirect mantém comparação de origem e encoding original.

Política conservadora residual: controles/backslashes codificados também são
rejeitados em query/fragment, conforme o plano. Proxies e headers efetivos
permanecem fora do escopo.
