# Verificação local — Gates E e F

> Data local: 2026-07-29
> Branch: `refactor/webapp-production-readiness`
> Escopo: implementação local; nenhum deploy, push, PR, merge ou mutação administrativa externa.

## Resultado

| Verificação | Resultado |
|---|---|
| Vitest | 19 passed em 8 arquivos |
| ESLint | passou sem warnings |
| TypeScript strict | passou |
| Next production build | passou; 15 rotas |
| Audit produção | zero vulnerabilidades |
| `git diff --check` | passou |
| HTTP `/login` | 200 + security headers/CSP report-only |
| HTTP rota inexistente | 404 |
| HTTP `/dashboard` anônimo | 307 para `/login?next=%2Fdashboard`, `no-store` |

## Evidência funcional automatizada

- O contrato paginado preserva `count`, `next`, `previous` e `results` do Django Ninja.
- A fila usa offset real de 40 itens e controles acessíveis anterior/próxima, permitindo alcançar registros além do primeiro lote.
- Teste de falha simulada em analytics comprova que health e queue continuam disponíveis e que a fonte degradada é sinalizada.
- Leitura inicial das páginas dashboard, agents, metrics e auto-assignment ocorre pela DAL `server-only` diretamente no Judah, sem Route Handler interno.
- Leituras obsoletas são canceladas por `AbortSignal`; retry com backoff existe somente para GET e para falhas transitórias selecionadas.
- Writes mantêm `Idempotency-Key` e não recebem retry automático.

## Performance e acessibilidade implementadas

- Removidos `SmoothScrollProvider`, `wheel.preventDefault`, grain animado e background attachment fixo.
- Blur do shell reduzido; pesos/fontes não usados removidos do bundle.
- Charts possuem tabela textual equivalente e respeitam reduced motion.
- Filtro de status usa `RadioGroup`/`Radio` HeroUI v3.
- Sync, inativação/reativação e assign/reassign apresentam confirmação; force-reassign exige motivo.
- Adicionados boundaries de loading, erro de segmento, erro global e 404.
- Tokens semânticos principais foram normalizados para `oklch`; catálogo mínimo documentado.

## Bloqueios de V-04/V-05

O browser sub-agent seguiu a runtime oficial, mas nenhuma instância de navegador estava disponível (`No browser is available`; descoberta `[]`). Por isso não há screenshot/recording, axe autenticado, screen reader, INP/LCP/CLS, long tasks ou validação manual desktop/mobile. Esses itens continuam obrigatórios antes de declarar Gates E/F integralmente verdes ou iniciar Gate G.

Staging, produção, HSTS, CSP enforcement e qualquer operação administrativa real permanecem fora desta execução.

## Regressão corrigida — envelope de paginação (2026-07-30)

O contrato efetivo do paginador Django Ninja é `{items, count}`. A DAL server-side introduzida no Gate E assumia `{results, count, next, previous}`, fazendo páginas autenticadas quebrarem ao acessar `results[0]` mesmo com resposta HTTP válida.

A normalização compartilhada agora:

- aceita `{items, count}` e `{results, count, next, previous}`;
- preserva links fornecidos pelo backend;
- deriva anterior/próxima por `limit/offset` para o envelope do Ninja;
- rejeita envelopes sem array para que a degradação por fonte seja acionada.

Verificações após o hotfix:

| Verificação | Resultado |
|---|---|
| Vitest | 21 passed em 8 arquivos |
| ESLint | passou |
| TypeScript strict | passou |
| Next production build | passou; 15 rotas |
| `git diff --check` | passou |
| Login local autenticado | HTTP 200 |
| Dashboard, autoassignment, metrics, agents e queue | HTTP 200, sem `Cannot read properties of undefined` |
| Browser visual | bloqueado: `No browser is available` |

## Regressões ASGI, sessão e warnings (2026-07-30)

- `CONN_MAX_AGE=0` foi aplicado aos perfis base e produção; o teste de settings exige o contrato em staging/produção.
- Respostas 5xx de autenticação não são mais convertidas em sessão inválida e não apagam cookies.
- O BFF tenta refresh e repete uma resposta 401 uma vez antes de retornar ao login.
- O `AppShell` não atualiza estado durante renderização e o script de tema usa o contrato de hidratação atual do Next.
- Soak local: 360 carregamentos autenticados de dashboard/métricas, zero falhas. Em 32 amostras pós-carga, `pg_stat_activity` permaneceu em `total=1`, `active=1`, `idle=0` (a conexão da própria medição).
- API indisponível: sessão retornou 502 sem `Set-Cookie`. Access adulterado + refresh válido: sessão retornou 200 e rotacionou ambos os cookies.
- Backend: 961 passed, 11 skipped, cobertura 90,41%. Frontend: 24 testes, lint, typecheck, build e audit verdes.

V-04 não está formalmente fechado porque Web Vitals/long tasks e desktop/mobile exigem browser. V-05 segue bloqueado: a descoberta final da runtime oficial retornou `[]`. Gate G continua fora de escopo e não autorizado.

## Restauração da engine GSAP e Playwright MCP (2026-07-30)

- `gsap@3.15.0` e `@gsap/react@2.1.2` foram restaurados com registro centralizado.
- Componentes usam `useGSAP`, escopo por `ref`, cleanup de contexto, `contextSafe` para callbacks tardios e `gsap.matchMedia()` para `prefers-reduced-motion`.
- GSAP voltou a controlar entrada/transição de rotas, fade dos tokens do tema claro/escuro, feedback de hover/press/foco de botões, fades/staggers, cards, contadores, gráficos, sidebar, login e carrossel.
- Animações priorizam `transform`, `opacity` e `filter`; scroll continua nativo e nenhum listener cancela `wheel`.
- O carrossel pausa o autoplay após interação manual e não inicia autoplay com reduced motion.
- O alvo clicável dos indicadores permanece geometricamente estável enquanto apenas o indicador interno anima, permitindo automação e alvo mínimo adequado.

Verificação desta iteração:

| Verificação | Resultado |
|---|---|
| Vitest | 24 passed em 8 arquivos |
| ESLint | passou sem warnings |
| TypeScript strict | passou |
| Next production build | passou; 15 rotas |
| Audit de produção | zero vulnerabilidades |
| `git diff --check` | passou |
| Playwright MCP | operacional; abriu `about:blank` e navegou para `/login` |
| Smoke de interação | clique real no Slide 2, conteúdo correto e `aria-pressed=true` |
| Evidência de GSAP | slide ativo com opacity 1 e transform matrix em execução |
| Console do browser | zero errors e zero warnings |

O bloqueio ambiental `No browser is available` continua verdadeiro para a runtime do in-app Browser, mas não impede mais a automação: o Playwright MCP está registrado e operacional. V-05 ainda não está concluído porque o smoke desta iteração foi público; faltam sessão autenticada, desktop/mobile, teclado, axe/screen reader, Web Vitals e gravação. Gate G continua não iniciado e não autorizado.

### Iteração visual do tema

O reveal circular foi removido após revisão visual. A troca de tema agora interpola diretamente, por 550 ms, os tokens de superfícies, textos, bordas, campos, backdrop e sombras com `sine.inOut`. Não existe overlay nem movimento da página; o ícone usa somente um crossfade discreto. Reduced motion continua aplicando o tema imediatamente.
