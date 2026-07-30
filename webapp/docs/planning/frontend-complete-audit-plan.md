# Master plan — frontend production readiness

> Request proposta: `refactor/webapp-production-readiness`
> Ciclo: F
> Fase atual: `PLAN_APPROVAL`
> Data: 2026-07-29
> Fonte principal: `docs/research/frontend-complete-audit.md`
> Estado: aguardando aprovação explícita do Felipe para iniciar `IMPLEMENT`

## 1. Objetivo

Elevar o Judah WebApp de painel administrativo funcional para uma superfície administrativa segura, autorizada, observável, performática e verificável, preservando a arquitetura em que o navegador acessa o backend Judah somente por uma camada server-side/BFF e nunca se conecta diretamente ao Supabase.

O trabalho começa pela contenção dos riscos P0/P1. Expansão funcional e refinamento visual só entram depois que autenticação, autorização, transporte de tokens, proxy, dependências e controles de segurança estiverem comprovadamente seguros.

## 2. Limite de aprovação

A aprovação deste documento autoriza apenas o início da fase `IMPLEMENT` e do Gate B abaixo, em branch não protegida. Ela não autoriza:

- deploy em staging ou produção;
- merge, push ou abertura/publicação de PR;
- execução de testes conectados a banco não local;
- migração, backfill, replay, sync de HubSpot ou mutação direta de banco;
- rotação de tokens ou inspeção de logs de produção;
- ativação de CSP enforcement, feature flag, rate limit ou MFA em produção.

Cada uma dessas ações permanece como gate próprio e exige autorização explícita quando chegar o momento.

## 3. Resultado esperado

Ao final do plano:

- nenhuma mutação administrativa estará pública;
- cada endpoint administrativo terá contrato explícito de papéis/capabilities, com testes positivos e negativos;
- refresh token, access token, senha e `Authorization` não trafegarão em URL nem serão persistidos em logs;
- o BFF aceitará somente combinações conhecidas de método e path e rejeitará mutações de origem incompatível;
- a sessão e as rotas autenticadas serão validadas server-side;
- a interface renderizará navegação, dados e ações conforme capabilities, sem substituir o enforcement do backend;
- Next.js, `eslint-config-next`, `sharp` e lockfile estarão reconciliados e sem vulnerabilidade high/critical conhecida;
- o scroll será nativo, as cargas duplicadas serão removidas e falhas parciais ficarão isoladas por widget;
- paginação, contagem e freshness refletirão o contrato real do backend;
- fluxos críticos atenderão WCAG 2.2 AA e terão evidência automatizada e em browser;
- ações sensíveis terão confirmação, motivo, idempotência quando aplicável e trilha de auditoria;
- staging e produção serão avaliados separadamente, com rollback documentado antes de deploy.

## 4. Escopo

### Incluído

- autenticação e refresh entre WebApp e Judah;
- autorização backend e minimização de payloads administrativos;
- capabilities expostas pela sessão e usadas pela UI;
- BFF, cookies, proteção de origem/CSRF e security headers;
- logs sanitizados e trilha de auditoria de ações sensíveis;
- dependências, lockfile e CI do WebApp;
- proteção server-side das rotas autenticadas;
- paginação, tratamento de falhas e arquitetura de carregamento;
- scroll, animação, fontes, blur/grain e Web Vitals;
- acessibilidade, design tokens e estados dos componentes existentes;
- documentação, testes, browser verification, staging smoke e rollback.

### Fora de escopo desta request

- criar gestão de secrets no navegador;
- adicionar telas de usuários, igrejas, knowledge base, conectores, gates ou agentes de IA sem contrato backend aprovado;
- reescrever o painel inteiro ou trocar HeroUI/Tailwind;
- usar `support/tickets/*` antes de revalidar seu contrato;
- alterar regras de autoatribuição, filas ou ciclos além do necessário para proteger os endpoints administrativos;
- tratar liveness/readiness como prova de conclusão de sync, assignment ou integração;
- executar qualquer ação operacional de produção durante `PLAN` ou automaticamente durante `IMPLEMENT`.

## 5. Baseline confirmado

- Next.js está declarado como `16.2.10`, mas a árvore instalada auditada estava em `16.2.4`.
- O `npm audit --omit=dev` registrou vulnerabilidades high em `next` e `sharp`.
- `POST /support/queue/sync-novo/`, `POST /support/special-schedules/` e `DELETE /support/special-schedules/{id}` usam `auth=None`.
- Leituras administrativas em `apps/support/admin_api.py` não aplicam RBAC de forma uniforme.
- `RefreshRequest` já existe no backend, porém `/auth/refresh` ainda recebe `refresh` como parâmetro simples/query.
- `app/api/backend/[...path]/route.ts` é um proxy genérico para cinco métodos e qualquer path.
- `proxy.ts` não inclui `/agents` entre os prefixos protegidos.
- `SmoothScrollProvider` cancela globalmente eventos `wheel` com listener não passivo.
- `requestPaginated` descarta navegação real e fabrica `next/previous = null`.
- loaders de overview usam `Promise.all`, portanto uma falha complementar pode derrubar a visão inteira.
- o CI raiz não possui lane explícita de lint, typecheck, build, testes e audit do `webapp`.
- não há suite frontend/component/E2E versionada nem evidência de browser autenticado.

## 6. Arquitetura-alvo

```text
Browser
  -> rota autenticada protegida server-side
  -> Route Handler específico ou allowlist estrita do BFF
       - valida sessão/capability
       - valida método + path + content type + tamanho
       - valida Origin/Sec-Fetch-Site nas mutações
       - adiciona access token server-side
       - faz refresh com JSON body, nunca por URL
       - registra correlation ID sem PII/secrets
  -> Judah API
       - autentica JWT
       - autoriza recurso + ação + papel/capability
       - minimiza o schema de resposta
       - registra ação sensível de modo auditável
```

Server Components/DAL devem buscar o snapshot inicial diretamente do Judah no servidor. Eles não devem chamar os Route Handlers internos. Client Components ficam restritos a interação, atualização incremental e mutações.

## 7. Decisões de contrato a congelar no início do IMPLEMENT

### DEC-01 — matriz RBAC

Adotar como baseline conservador, sujeito à aprovação de produto antes de abrir acesso adicional:

| Recurso/ação | viewer | agent | manager | admin |
|---|---:|---:|---:|---:|
| Health operacional mínimo | leitura | leitura | leitura | leitura |
| Dashboard agregado sem PII | leitura | leitura | leitura | leitura |
| Fila/tickets com contato e owner | não | somente escopo próprio, se houver contrato | leitura | leitura |
| Agentes, gestores, time logs e reatribuições | não | não | leitura | leitura |
| Criar/alterar/inativar agente | não | não | sim | sim |
| Manual assign/force reassign | não | não | sim | sim |
| Sync NOVO | não | não | sim | sim |
| Special schedules — escrita | não | não | sim | sim |
| Configuração sensível/capabilities | não | não | conforme contrato | sim |

Nenhum endpoint deve autorizar por ausência do atributo `role`. Service accounts, se necessários, precisam de identidade/capability explícita.

### DEC-02 — transporte do refresh

Fazer rollout compatível em três passos: backend aceita `RefreshRequest` no body; WebApp passa a usar exclusivamente o body; compatibilidade por query é removida e coberta por teste de rejeição. A remoção só ocorre após confirmar que não há outro consumidor autorizado.

### DEC-03 — BFF

Preferir handlers de domínio explícitos. Se o custo imediato exigir manter o catch-all, ele só poderá operar com tabela versionada de método + template de path + capability + content type + limite de body. Path traversal, path não listado e método não listado retornam erro sem chegar ao Judah.

### DEC-04 — audit trail

Antes de criar migration, verificar se existe ledger administrativo reutilizável. `ToolCallAuditLog` não deve ser reutilizado para ações humanas genéricas. Se não houver contrato adequado, criar um ledger append-only próprio, com ator, ação, recurso, alvo, motivo, resultado, correlation ID, idempotency key e timestamps, sem payload sensível bruto.

### DEC-05 — sandbox HubSpot

Classificar a rota como ferramenta de teste/suporte, definir ambientes permitidos, capability, rate limit e domínios CSP. Ela não será tratada como funcionalidade pública nem receberá gestão de credenciais no browser.

## 8. Gates e tarefas

## Gate A — aprovação do plano

Estado atual: **aguardando aprovação**.

Critérios de saída:

- escopo, matriz RBAC conservadora e sequência de PRs aceitos;
- confirmação de que a implementação pode alterar backend e `webapp` na mesma request;
- branch `refactor/webapp-production-readiness` criada a partir da base aprovada;
- worktree revalidada para separar drift preexistente;
- `STATUS.md` canônico movido para `IMPLEMENT`, sem tocar branch protegida.

Rollback: não aplicável; nenhuma implementação foi iniciada.

## Gate B — contenção P0 de autorização backend

Objetivo: fechar imediatamente endpoints administrativos públicos e leituras administrativas indevidas, sem depender do WebApp.

### BE-01 — matriz de autorização executável

- Revisar todos os endpoints em `apps/support/api.py`, `apps/support/admin_api.py`, `apps/analytics/api.py` e `apps/auth_user/api.py`.
- Associar método + recurso a papel/capability explícito.
- Corrigir `common/permissions.py` para negar identidades sem papel explícito.
- Manter públicos somente probes ou webhooks cuja autenticação própria esteja comprovada; `auth=None` não será removido mecanicamente de webhooks HMAC.

Aceite:

- chamadas anônimas aos três writes identificados retornam 401;
- viewer/agent recebem 403 nos recursos administrativos não permitidos;
- manager/admin mantêm somente as ações previstas na matriz;
- nenhuma regressão em HMAC de HubSpot/Jira; qualquer alteração nesses verificadores exige aprovação separada.

### BE-02 — proteger sync e special schedules

- Remover `auth=None` dos writes administrativos.
- Aplicar `require_manager_or_admin` ou capability equivalente.
- Definir idempotência/replay de `sync-novo` e criação de agenda.
- Registrar ator, motivo, alvo, resultado e correlation ID.

Aceite:

- testes 401, 403, sucesso autorizado, payload inválido e replay;
- nenhuma chamada externa real durante testes;
- falha de auditoria não pode produzir write sem rastreabilidade definida.

### BE-03 — minimizar leituras administrativas

- Proteger list/detail de agentes, métricas, time logs e reatribuições.
- Separar schema agregado sem PII de schema administrativo quando viewer/agent ainda precisarem de dados.
- Não retornar e-mail, manager email, owner ID ou identificadores de contato sem necessidade de negócio.

Aceite:

- matriz de campos por papel coberta por testes;
- ausência de PII validada no JSON, não apenas ocultada na UI.

### V-01 — regressão backend do Gate B

- `ruff check` e `ruff format --check` nos arquivos alterados;
- `mypy` no escopo alterado;
- testes focados de permissions, support/admin e auth;
- suite local via runner nativo com banco descartável e sem conexão não local;
- `manage.py check --fail-level WARNING` e `makemigrations --check --dry-run`.

Rollback:

- reverter decorators/capability map mantendo evidência dos testes;
- nenhuma alteração em dados existentes;
- se houver ledger novo, migration deve ter `down` seguro e deploy próprio, nunca `DROP` ad hoc.

## Gate C — refresh, sessão e fronteira BFF

Depende de: Gate B aprovado e verde.

### BE-04 — refresh token em JSON body

- Alterar `/auth/refresh` para usar `RefreshRequest`.
- Validar rotação/blacklist e comportamento de replay conforme configuração real do Simple JWT.
- Remover suporte por query somente depois da migração do consumidor.
- Garantir que logs e erros não incluam o token.

### FE-01 — sessão server-only e cookies

- Atualizar `src/lib/auth/server-session.ts` para enviar refresh no body.
- Centralizar leitura/renovação/limpeza de cookies em uma DAL server-only.
- Avaliar `__Host-`, `Secure`, `HttpOnly`, `SameSite`, path mínimo e expiração alinhada ao JWT.
- Diferenciar sessão ausente, expirada, inválida e backend indisponível.

### FE-02 — allowlist e proteção de mutações

- Substituir ou restringir `app/api/backend/[...path]/route.ts` conforme DEC-03.
- Validar `Origin`, `Host` e `Sec-Fetch-Site` em POST/PUT/PATCH/DELETE.
- Aceitar somente content types e tamanhos esperados.
- Não encaminhar cookies, headers hop-by-hop ou paths arbitrários.
- Retornar 404/405/413/415/403 de modo determinístico.

### FE-03 — capabilities na sessão e rotas

- Expor capabilities derivadas do backend no payload mínimo de sessão.
- Proteger server-side todas as rotas autenticadas, incluindo `/agents` e `/sandbox-chat`.
- Renderizar navegação e ações por capability; manter 401/403 do servidor como autoridade.
- Evitar comparações de role espalhadas pelos componentes.

### V-02 — contratos de segurança WebApp

- testes unitários do matcher método/path;
- testes de Origin/Sec-Fetch-Site, content type, body limit e path não permitido;
- testes de cookie/refresh sem token em URL;
- testes por role/capability para rota, menu e botão;
- busca automatizada por `refresh=`, `Authorization`, `password` e logs inseguros no escopo alterado.

Rollback:

- feature flag server-side para a allowlist durante staging, default deny em produção;
- manter endpoint antigo apenas durante a janela compatível definida em DEC-02, sem prolongar a exposição;
- limpar cookies e forçar novo login se a semântica de sessão mudar de forma incompatível.

## Gate D — supply chain, headers, logs e CI

Depende de: Gate C aprovado e verde.

### FE-04 — dependências reproduzíveis

- Atualizar Next.js e `eslint-config-next` em conjunto para versão corrigida/suportada.
- Reconciliar `sharp`, `package-lock.json`, README e árvore instalada.
- Usar instalação determinística com `npm ci`.
- Ler os guias da versão instalada em `node_modules/next/dist/docs/` e consultar documentação atual antes de qualquer mudança de API do Next.

Aceite:

- `npm ls` sem `ELSPROBLEMS`;
- versão executada igual à declarada no lock;
- `npm audit --omit=dev` sem high/critical, ou exceção formal com owner, justificativa e prazo;
- lint, typecheck e build verdes após upgrade.

### FE-05 — CSP e headers

- Implementar CSP inicialmente em report-only.
- Usar nonce/hash no bootstrap de tema e allowlist mínima na rota HubSpot.
- Configurar `frame-ancestors`, `object-src`, `base-uri`, `form-action`, `X-Content-Type-Options`, `Referrer-Policy` e `Permissions-Policy`.
- Aplicar `Cache-Control: no-store` a auth, sessão e respostas com dados pessoais.
- HSTS somente após validação da topologia HTTPS/subdomínios.

### BE-05 / FE-06 — logging sanitizado e correlação

- Usar logger estruturado com allowlist/redaction para senha, tokens, Authorization, cookies, query sensível e bodies de terceiros.
- Remover `console.error` ad hoc server-side.
- Propagar correlation ID sem PII entre WebApp e Judah.
- Definir retenção/acesso/descarte fora do código e registrar a decisão operacional.

### OPS-01 — lane WebApp no CI

- Adicionar instalação determinística, lint, `tsc --noEmit`, testes, build e audit ao CI.
- Falhar em drift de lock e vulnerabilidade acima da política aprovada.
- Guardar relatórios de teste/a11y sem publicar secrets ou bodies.

### V-03 — staging de segurança

- validar headers e CSP report-only por rota;
- confirmar que login, refresh, logout e expiração funcionam;
- confirmar que sandbox carrega somente no ambiente/capability permitidos;
- confirmar ausência de token/query e redaction em logs de staging;
- executar smoke por viewer, agent, manager e admin.

Rollback:

- CSP permanece report-only até evidência suficiente;
- headers independentes podem ser revertidos sem desfazer RBAC;
- downgrade de dependência somente para versão comprovadamente segura e com lock reproduzível.

## Gate E — dados, resiliência e performance

Depende de: Gates B–D aprovados e verdes.

### FE-07 — remover scroll global e reduzir custo gráfico

- Remover `SmoothScrollProvider` e o `preventDefault()` global de wheel.
- Restringir `scroll-behavior: smooth` a ações explícitas.
- Garantir nested scroll, teclado, touch, scrollbar drag e reduced motion.
- Reduzir grain animado, fixed backgrounds, blur e GSAP conforme orçamento medido.
- Remover fontes/pesos e assets não usados.

Aceite:

- scroll nativo em window, sidebar, status rail, modal e tabelas;
- nenhuma regressão de foco/teclado/touch;
- INP p75 de laboratório abaixo de 200 ms nos fluxos críticos ou melhoria documentada contra baseline;
- evidência de long tasks/dropped frames antes/depois em desktop e viewport mobile.

### FE-08 — DAL e carregamento por seção

- Criar DAL server-only para snapshots iniciais autorizados.
- Migrar incrementalmente páginas para Server Components, mantendo ilhas cliente para interação.
- Não chamar Route Handlers internos a partir de Server Components.
- Adicionar loading/error boundaries e freshness por widget.
- Separar dados essenciais/complementares e evitar `Promise.all` monolítico.

### BE-06 / FE-09 — deduplicação e paginação real

- Confirmar envelope Django Ninja e parâmetros limit/offset/count.
- Preservar count e navegação no tipo TypeScript; remover `next/previous` inventados.
- Implementar controles acessíveis e “mostrando X de Y”.
- Levar filtros/search para o servidor em datasets grandes.
- Avaliar endpoint agregado somente se reduzir custo sem ampliar PII/RBAC.

### FE-10 — cliente resiliente

- Abort/cancel em desmontagem e corrida.
- Política explícita de retry/backoff apenas para operações idempotentes.
- Estados próprios para 401, 403, 404, 409, 429, 5xx e integração indisponível.
- Não repetir automaticamente mutações sensíveis.

### V-04 — performance e resiliência

- browser verification autenticada em desktop e mobile;
- falha simulada de analytics não pode derrubar health/queue;
- paginação prova acesso além de 40/100 itens em fixture local;
- navegação não duplica requests equivalentes sem justificativa;
- registrar bundle, LCP, INP, CLS e long tasks antes/depois.

Rollback:

- migração de páginas por rota, permitindo reversão isolada;
- nenhum cache de dados sensíveis sem chave de usuário/capability e política explícita;
- endpoint agregado, se criado, fica atrás de versão/flag até contrato validado.

## Gate F — UX segura, acessibilidade e design system

Depende de: Gate E aprovado e verde.

### FE-11 — ações sensíveis

- Confirmation dialog com alvo, efeito, motivo e idempotência para inativar, assign, force-reassign, sync e agendas.
- Step-up authentication somente se o modelo de ameaça e o backend suportarem.
- Feedback persistente para 409, falha parcial e estado desconhecido.
- Exibir ator, timestamp, motivo e correlation ID quando o ledger estiver disponível.

### FE-12 — WCAG 2.2 AA

- Normalizar controles com semântica React Aria/HeroUI adequada.
- Converter filtros customizados em radio/toggle group quando aplicável.
- Criar alternativa textual/tabular para charts.
- Validar foco após navegação, modal, erro e atualização.
- Cobrir contraste, zoom, teclado, screen reader e reduced motion.

Aceite:

- zero violação axe serious/critical nos fluxos críticos;
- login, dashboard, fila, autoassignment, agents, metrics e sandbox permitido operáveis por teclado;
- matriz de contraste AA para light/dark e estados interativos.

### FE-13 — tokens e catálogo mínimo

- Consolidar tokens semânticos em `oklch`, preservando HeroUI v3/Tailwind v4.
- Criar wrappers apenas para padrões Judah recorrentes.
- Documentar anatomy, variants, sizes, estados, motion e conteúdo.
- Adicionar catálogo/testes visuais mínimos dos componentes críticos.

### FE-14 — limpeza documental e código morto

- Remover helpers/assets/dependências sem uso comprovado.
- Atualizar README e endpoints reais.
- Remover claims como “backend live” sem readiness comprovada.
- Adicionar `global-error`, boundaries, loading e not-found onde aplicável.

### V-05 — browser e acessibilidade

- browser sub-agent único e serializado;
- screenshots/recording em `03-verification/` para desktop/mobile;
- axe, teclado e screen reader nos fluxos críticos;
- regressão visual de estados loading/empty/error/forbidden/degraded/success.

Rollback:

- tokens/componentes migrados em lotes pequenos;
- snapshots visuais devem identificar regressão antes de remover compatibilidade antiga.

## Gate G — readiness de release e deploy

Depende de: todos os Gates B–F aprovados e verdes.

### OPS-02 — pré-deploy

- confirmar SHA e artefato construído;
- confirmar migrations pendentes e plano `down`, se houver;
- validar flags/configuração por ambiente;
- documentar rollback por PR/deployment;
- staging smoke aprovado;
- Sentry/telemetria sem novo erro durante janela definida;
- comunicar janela de deploy.

### V-06 — prova pós-deploy

Separar evidências de:

1. deployment do SHA correto;
2. liveness e readiness;
3. login/refresh/logout;
4. RBAC negativo e positivo por papel;
5. operação real do BFF/headers/CSP;
6. paginação, falha parcial e performance;
7. ação administrativa controlada, somente se explicitamente autorizada;
8. logs/audit trail sem secrets;
9. worker/beat e integrações, quando a mudança os afetar.

Critério de saída: `STATUS.md` só passa a `DONE` após evidência de todos os critérios aplicáveis. Green CI, HTTP 200/202 ou readiness isolada não bastam.

Rollback:

- rollback do deploy para SHA anterior conhecido;
- reversão de flags/configuração separada do rollback de código;
- migration rollback somente pelo procedimento aprovado;
- nenhuma repetição automática de sync, assignment ou ação administrativa.

## 9. Sequência de entrega recomendada

| Ordem | Entrega | Conteúdo | Dependência |
|---:|---|---|---|
| 1 | PR de contenção | BE-01, BE-02, BE-03, V-01 | aprovação do plano |
| 2 | PR auth/BFF | BE-04, FE-01, FE-02, FE-03, V-02 | PR 1 |
| 3 | PR supply chain/headers/CI | FE-04, FE-05, BE-05, FE-06, OPS-01, V-03 | PR 2 |
| 4 | PR performance/dados | FE-07 a FE-10, BE-06, V-04 | PR 3 |
| 5 | PR UX/a11y/design | FE-11 a FE-14, V-05 | PR 4 |
| 6 | release | OPS-02, V-06 | PRs anteriores e aprovação de deploy |

Cada PR deve ser pequeno o suficiente para rollback independente. A contenção P0 não deve aguardar o refactor visual/performance.

## 10. Arquivos e áreas prováveis

### Backend

- `apps/support/api.py`
- `apps/support/admin_api.py`
- `apps/support/schemas.py`
- `apps/support/tests/test_admin_api.py`
- `apps/support/tests/test_api_extended.py`
- `apps/auth_user/api.py`
- `apps/auth_user/schemas.py`
- `apps/auth_user/tests/test_api.py`
- `apps/auth_user/tests/test_api_direct.py`
- `apps/analytics/api.py`
- `common/permissions.py`
- `common/tests/test_permissions.py`
- novo ledger/migration somente após DEC-04

### WebApp

- `app/api/auth/*`
- `app/api/backend/[...path]/route.ts`
- `app/api/hubspot/visitor-token/route.ts`
- `app/(app)/layout.tsx`
- `app/layout.tsx`
- `app/globals.css`
- `proxy.ts`
- `next.config.ts`
- `src/lib/auth/*`
- `src/lib/api/*`
- `src/hooks/use-api-query.ts`
- `src/lib/motion/*`
- `src/components/layout/*`
- `src/features/*`
- `src/types/api.ts`
- `package.json` e `package-lock.json`

### DevOps/documentação

- `.github/workflows/ci.yml`
- documentação de segurança, RBAC, privacy/log retention e rollback
- `ai-system/requests/refactor/webapp-production-readiness/*`

## 11. Estratégia de testes

### Backend

- unitários de permissions/capabilities;
- contratos 401/403/2xx por endpoint e papel;
- minimização de schema por papel;
- refresh body, token inválido, expirado, rotacionado e replay;
- idempotência/audit trail de writes;
- nenhuma rede real em testes.

### Frontend/BFF

- unitários do allowlist matcher e capability map;
- Route Handler tests para origem, método, path, body e redaction;
- component tests para visibilidade/estado de ações por capability;
- integração de sessão, expiração, refresh e logout;
- paginação e falha parcial;
- axe e navegação por teclado.

### E2E/browser

- fixtures locais para os quatro papéis;
- login, redirect e rota proibida;
- dashboard degradada;
- queue pagination;
- confirmação/cancelamento de ação sensível sem mutação externa;
- nested scroll desktop/mobile;
- sandbox somente na capability/ambiente permitidos.

### Comandos mínimos previstos

Os comandos exatos serão confirmados no início de `IMPLEMENT`, sem usar banco não local:

```powershell
# backend, pelo runner nativo do repositório
uv run ruff check .
uv run ruff format --check .
uv run mypy apps common core
uv run pytest <escopo-focado>

# webapp
npm.cmd ci
npm.cmd run lint
npx.cmd tsc --noEmit
npm.cmd test
npm.cmd run build
npm.cmd audit --omit=dev
```

Se a suite frontend ainda não tiver script `test`, a escolha e instalação do runner fazem parte do primeiro PR frontend e devem seguir a documentação atual da versão instalada.

## 12. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Bloquear consumidor legítimo ao fechar endpoints públicos | inventariar consumidores, testar contrato e fazer rollout compatível |
| RBAC quebrar dashboard atual | payload agregado mínimo e fixtures por papel antes de remover acesso |
| Refresh incompatível entre deploys | rollout backend → WebApp → remoção query |
| CSP bloquear HubSpot/fontes/scripts | report-only, relatório por rota e allowlist mínima |
| Cache vazar dados entre usuários | chavear por identidade/capability ou usar `no-store` |
| Retry duplicar mutação | retry automático somente em reads/idempotentes |
| Refactor de Server Components ampliar escopo | migrar uma rota por vez, com browser evidence |
| Audit trail armazenar PII/secrets | schema mínimo, redaction e testes de conteúdo proibido |
| Mudança de dependency introduzir breaking change | guias versionados, lock determinístico e smoke completo |
| Drift preexistente entrar na entrega | status/diff antes de cada commit e staging seletivo |

## 13. Critérios globais de aceite

- [ ] Todos os P0 fechados no backend, independentemente da UI.
- [ ] Matriz RBAC versionada e coberta por testes positivos/negativos.
- [ ] Nenhum secret/token/password em URL, log ou artefato.
- [ ] BFF default-deny para método/path desconhecido.
- [ ] Proteção server-side em todas as rotas autenticadas.
- [ ] Build usa exatamente as versões declaradas no lock.
- [ ] Zero high/critical conhecido ou exceção formal com prazo.
- [ ] Lint, typecheck, testes e build verdes em backend e WebApp.
- [ ] Scroll nativo e métricas de performance registradas.
- [ ] Paginação/count reais e falhas parciais isoladas.
- [ ] CSP/headers validados em staging.
- [ ] WCAG 2.2 AA nos fluxos críticos.
- [ ] Audit trail de ações sensíveis sem payload sensível.
- [ ] Browser evidence desktop/mobile registrada.
- [ ] Rollback documentado e testável antes do deploy.
- [ ] Deploy, health, comportamento funcional e integrações reportados como camadas separadas.

## 14. Próxima ação

**Felipe:** revisar e aprovar este master plan. Após a aprovação explícita, iniciar somente o Gate B (`BE-01` a `V-01`) em branch não protegida, revalidando primeiro o worktree e o inventário de consumidores. Nenhuma etapa posterior fica implicitamente autorizada.
