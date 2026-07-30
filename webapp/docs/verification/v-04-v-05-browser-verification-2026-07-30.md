# V-04/V-05 — verificacao autenticada em browser

> Data: 2026-07-30
> Ambiente: exclusivamente local, `http://127.0.0.1:3000`, API local e SQLite descartavel
> Perfil: administrador local `ui-verification-admin@local.judah.test`
> Viewports: desktop `1440x1000` e mobile `390x844`

## Resultado

**V-04 e V-05 estao fechados para o release candidate local.** A verificacao foi feita em uma unica sessao serializada do Playwright MCP, autenticada com a fixture descartavel. Nenhuma atribuicao, sincronizacao, inativacao, force-reassign ou outra mutacao administrativa foi confirmada.

Esta evidencia nao substitui smoke pos-deploy, Web Vitals de usuarios reais nem integracoes externas em producao.

## V-04 — performance e resiliencia

| Criterio | Evidencia | Resultado |
|---|---|---|
| Desktop e mobile autenticados | dashboard e fila renderizados nas duas viewports | passou |
| Falha parcial isolada | `queue-health` retornou 500 na fixture SQLite; dashboard, fila, agentes, metricas e autoatribuicao continuaram navegaveis | passou |
| Paginacao alem de 40/100 | terceira pagina exibiu `Mostrando 81-105 de 105`, `Anterior` habilitado e `Proxima` desabilitado | passou |
| Requests equivalentes | trace final em dashboard, agentes, metricas, autoatribuicao e fila: zero RSC duplicado e zero API duplicada | passou |
| LCP | 512 ms | passou |
| INP | 88 ms | passou |
| CLS | 0,00320 | passou |
| Long tasks | uma amostra de 51 ms | registrado, sem bloqueio |
| Frame gaps | 1; maximo 62,5 ms | registrado, sem bloqueio |

O trace final foi repetido depois de desabilitar prefetch nos links administrativos e de marca duplicados. Cada rota apresentou os headings esperados e nenhum warning de console. Na fila houve somente o erro de recurso 500 esperado de `support/queue/health`, documentado pela fixture como estado degradado local.

## V-05 — browser e acessibilidade

- Axe WCAG 2/2.1/2.2: zero violacao serious/critical em dashboard, fila, agentes, metricas, autoatribuicao e pagina de acesso negado.
- As accessibility snapshots expuseram landmarks, headings, navegacao, tabela/caption, progressbar, radiogroup, dialog e nomes acessiveis dos controles criticos.
- Teclado mobile: `Tab` focou `Abrir menu`; `Enter` abriu o drawer e moveu foco para `Fechar menu`; `Escape` fechou e devolveu foco para `Abrir menu`.
- Reduced motion: `prefers-reduced-motion: reduce` foi reconhecido; a troca de tema usou transicoes instantaneas de 0,01 ms e havia zero animacao em execucao apos 200 ms.
- O dialogo `Atribuir ticket manualmente` identificou `UI-VERIFY-081`, exigiu agente destino, manteve `Confirmar` desabilitado e foi cancelado sem mutacao.
- Estados observados: success na fila; empty em listas sem historico/analytics; degraded/error isolado por `queue-health`; forbidden em `/forbidden`; loading transitorio nos snapshots antes da hidratacao.
- A inspecao de semantica foi feita pela arvore de acessibilidade do Playwright MCP; nao foi utilizado leitor de tela nativo do sistema operacional.

## Fluxos criticos

| Rota | Evidencia funcional |
|---|---|
| `/dashboard` | dados da fixture, aviso degradado e widgets restantes utilizaveis |
| `/queue` | 105 registros, tres paginas, busca/filtros e confirmacao segura |
| `/agents` | pagina autenticada e cadastro local de dois agentes |
| `/metrics` | pagina autenticada e empty states de analytics local |
| `/auto-assignment` | observabilidade, regras e acao sensivel sem confirmacao |
| `/forbidden` | heading `Acesso nao autorizado` e axe sem serious/critical |

## Artefatos

- `docs/verification/artifacts/v04-v05-dashboard-desktop.jpg`
- `docs/verification/artifacts/v04-v05-dashboard-mobile.jpg`
- `docs/verification/artifacts/v04-v05-queue-page3-desktop.jpg`
- `docs/verification/artifacts/v04-v05-queue-mobile.jpg`
- `docs/verification/artifacts/v04-v05-forbidden-desktop.jpg`
- `docs/verification/artifacts/v04-v05-pagination-final.json`
- `docs/verification/artifacts/v04-v05-perf-final-desktop.json`
- `docs/verification/artifacts/v04-v05-network-final-cross-route.json`
- `docs/verification/artifacts/v04-v05-reduced-motion-final.json`
- `docs/verification/artifacts/v04-v05-console-final-build.log`

## Limites e proximo gate

- O 500 de `queue-health` e o eventual 503 do sandbox HubSpot sao efeitos intencionais de SQLite/credenciais placeholder; nao comprovam saude externa.
- A CSP local permanece report-only e registra mensagens informativas de inline scripts; o trace final teve zero warning e zero erro inesperado de JavaScript.
- V-06 ainda deve validar o deploy Vercel, headers efetivos, smoke autenticado e rollback no SHA publicado.
