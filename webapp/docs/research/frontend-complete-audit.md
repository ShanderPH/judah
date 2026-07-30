# Research — auditoria completa do frontend Judah WebApp

> Data da análise: 2026-07-29
> Escopo: research somente; nenhuma correção, migração, deploy ou alteração de contrato foi executada.
> Base analisada: código local do backend Judah e do `webapp`, documentação do repositório, dependências instaladas, guias versionados do Next.js 16.2 e documentação atual do HeroUI v3 via Context7.

## 1. Resumo executivo

O webapp é um painel administrativo funcional em Next.js App Router, React 19, HeroUI v3 e Tailwind CSS v4. A arquitetura BFF adotada é correta em princípio: o navegador fala com Route Handlers internos, e access/refresh tokens ficam em cookies `HttpOnly`. A interface cobre dashboard, fila, autoatribuição, agentes e métricas com dados reais do Judah.

O sistema, porém, ainda não deve ser tratado como um painel administrativo production-ready. A auditoria encontrou riscos críticos de autorização no backend consumido, vulnerabilidades altas na cadeia do Next.js, vazamento de refresh token por URL, ausência de proteção CSRF explícita nas mutações do BFF, proxy excessivamente permissivo, divergência entre versões declaradas e instaladas, custo alto de renderização/animação e uma implementação global de scroll que deliberadamente degrada a rolagem nativa.

Principais conclusões:

1. **P0 — mutações administrativas públicas no backend:** `POST /support/queue/sync-novo/`, `POST /support/special-schedules/` e `DELETE /support/special-schedules/{id}` usam `auth=None`.
2. **P0 — controle de acesso inconsistente:** leituras administrativas de agentes, e-mails, gestores, métricas, time logs e reatribuições exigem apenas JWT, não papel manager/admin; a UI exibe as mesmas rotas e ações para `viewer`, `agent`, `manager` e `admin`.
3. **P1 — dependências vulneráveis:** `npm audit --omit=dev` reportou duas dependências high (`next` e `sharp`) e múltiplos advisories; a versão instalada do Next é 16.2.4, embora `package.json` exija 16.2.10.
4. **P1 — refresh token em query string:** o webapp chama `/auth/refresh?refresh=...`, expondo o token a access logs, traces, APM, histórico e ferramentas de observabilidade.
5. **P1 — BFF sem allowlist/CSRF explícito:** o catch-all `/api/backend/[...path]` encaminha GET/POST/PATCH/PUT/DELETE para qualquer path sob a API Judah e se apoia apenas em `SameSite=Lax`; não valida `Origin`/`Sec-Fetch-Site`, não aplica allowlist nem RBAC por recurso.
6. **P1 — scroll lento causado pelo próprio frontend:** o provider global cancela todo evento `wheel` e interpola o movimento com fator 0,12, competindo com containers internos e com `scroll-behavior: smooth`.
7. **P1 — LGPD e observabilidade:** dados pessoais operacionais estão disponíveis além do princípio de necessidade; respostas integrais/erros de terceiros podem ser registrados sem sanitização consistente; não há política aparente de retenção, mascaramento, consentimento ou trilha de auditoria no webapp.
8. **P2 — arquitetura muito client-side:** todas as telas principais carregam dados após hidratação, com vários requests paralelos e duplicados por rota, perdendo parte dos benefícios de Server Components, streaming e autorização server-side.
9. **P2 — superfície incompleta:** não há gestão de usuários, papéis, gates, ferramentas, conectores, knowledge base, igrejas ou agentes de IA, apesar de esses domínios existirem no backend ou no objetivo declarado do produto.

## 2. Metodologia e limites

Foram inspecionados:

- roteamento e routers Django Ninja em `core/urls.py`;
- contratos de autenticação, support/admin, analytics, health e AI;
- schemas Pydantic/Django Ninja e tipos TypeScript;
- Route Handlers do BFF, cookies, proxy, sessão e logout;
- páginas, features, hooks, componentes, design tokens, animações e dependências;
- documentação histórica em `ai-system/requests/feat/webapp-frontend`;
- guias locais da versão instalada em `node_modules/next/dist/docs/`;
- documentação atual de HeroUI v3 e Next.js via Context7;
- `eslint`, `tsc --noEmit`, `next build`, `npm ls` e `npm audit --omit=dev`.

Limitações:

- não foram executados requests contra produção, Supabase ou HubSpot;
- não houve login com credencial real nem mutação de dados;
- o ambiente recusou manter o servidor Next local em segundo plano, portanto não foram produzidos Lighthouse, Core Web Vitals, gravação de scroll ou auditoria visual autenticada;
- a análise de comportamento visual combina código, CSS, contratos dos componentes e build. A validação em browser deve ser um gate obrigatório do planning/verification.

## 3. Arquitetura atual

### 3.1 Fluxo de autenticação

```text
Browser
  -> POST /api/auth/login { identity, password }
  -> Next Route Handler
  -> POST Judah /auth/login { username, password }
  <- access + refresh JWT
  <- cookies HttpOnly, SameSite=Lax, Secure em production

Browser
  -> /api/backend/<path>
  -> Next catch-all adiciona Authorization: Bearer <access>
  -> refresh automático após 401
  -> Judah API
```

Pontos positivos:

- JWTs não são persistidos em `localStorage`/`sessionStorage` nem expostos ao JavaScript do browser;
- cookies são `HttpOnly`, `SameSite=Lax` e `Secure` em produção;
- logout tenta invalidar o refresh no backend e sempre limpa os cookies;
- código sensível de backend está marcado com `server-only`;
- o browser não se conecta diretamente ao Supabase.

Gaps:

- cookies de access e refresh usam `Path=/`, ampliando a superfície; o refresh pode ter path mais restrito;
- não há prefixo `__Host-`, expiração absoluta ligada ao token, proteção contra reutilização no BFF ou binding da sessão;
- o `proxy.ts` verifica somente a presença do cookie, não sua validade; isso é aceitável como check otimista, mas não como autorização;
- `/agents` não consta em `protectedPrefixes`; o `AuthBoundary` cliente eventualmente redireciona, mas a proteção server-side fica inconsistente;
- o layout autenticado é um Client Component boundary que valida a sessão somente após hidratação, causando loading obrigatório, requests adicionais e possível exposição estrutural da rota;
- não existe matriz RBAC no frontend, e a API interna não valida papel por operação.

### 3.2 Cobertura de integração

| Domínio | Backend atual | Frontend atual | Avaliação |
|---|---|---|---|
| Auth | login, refresh, logout, me, profile, password, register, user detail | login, session, logout | Parcial; sem perfil, troca de senha, gestão de usuários e papéis |
| Health | liveness e readiness | usa liveness/status rail | Parcial; readiness não é exibido como camada separada |
| Queue | status, pending, assigned, health, metrics, sync | integrado | Amplo, mas paginação é truncada e writes não têm proteção suficiente |
| Agents | CRUD, activate/inactivate, metrics, time logs | CRUD parcial, activate/inactivate, métricas | Integrado, mas RBAC/UI e contrato de status divergem |
| Assignment | manual assign e force reassign | integrado | Ações sensíveis aparecem para todos os papéis |
| Schedules | leitura e CRUD | somente leitura | Parcial; API backend de escrita é pública |
| Analytics | reports | integrado | Parcial; sem filtros/paginação reais, exportação ou drill-down |
| Tickets | CRUD legado | não integrado | Decisão conservadora correta; contrato precisa ser revalidado |
| Church | list/detail | ausente | Gap funcional |
| Knowledge | list/detail/search | ausente | Gap funcional e busca pública requer revisão |
| AI agents | chat, triage, Salomão e webhooks condicionais | ausente | Gap funcional para gestão/observabilidade de agentes |
| Conectores | HubSpot/Jira/Supabase/Pinecone no backend | apenas sandbox HubSpot | Não há painel de configuração/saúde/auditoria |
| Gates/flags | flags e readiness distribuídos no backend | apenas snapshots textuais | Não há console de gates com contrato explícito |

### 3.3 Drift de documentação e contratos

O baseline histórico de maio afirma que não existiam logout, CRUD de agentes, métricas detalhadas e atribuição manual. O código atual já contém esses endpoints e o frontend passou a consumi-los. Parte do README ainda repete as lacunas antigas. A documentação de endpoints está mais atual, mas afirma que todo `admin_api` requer manager/admin, o que não corresponde aos decorators reais.

Há também drift de versão:

- `package.json`: Next 16.2.10;
- `node_modules` e build: Next 16.2.4;
- `package-lock.json`: raiz declara 16.2.10, árvore instalada permanece 16.2.4;
- README: Next 16.2.4;
- `eslint-config-next`: 16.2.10.

Esse estado invalida a premissa de build reprodutível e faz o projeto compilar/testar contra uma versão diferente da declarada.

## 4. Achados detalhados

### SEC-01 — mutações administrativas sem autenticação — P0

Evidência no backend:

- `sync-novo`: `auth=None` em `apps/support/api.py`;
- criação de special schedule: `auth=None`;
- exclusão de special schedule: `auth=None`.

Impacto:

- qualquer cliente que alcance a API pode disparar backfill/sincronização do HubSpot;
- qualquer cliente pode criar, sobrescrever ou excluir exceções de calendário;
- alterações de calendário podem afetar elegibilidade, operação e roteamento;
- risco de abuso, indisponibilidade lógica, alteração não autorizada e quebra de accountability/LGPD.

Orientação para planning:

- remover `auth=None` de todas as mutações administrativas;
- aplicar `require_manager_or_admin` ou permissão granular mais restrita;
- adicionar rate limit, idempotency key quando aplicável e audit event imutável;
- testar 401, 403, sucesso autorizado e replay;
- não tratar a proteção do webapp como substituta da proteção backend.

### SEC-02 — RBAC insuficiente em leituras administrativas — P0

`list_agents`, `retrieve_agent`, métricas agregadas, time logs e reatribuições não usam `require_manager_or_admin`. Como o router herda apenas JWT global, qualquer conta autenticada, inclusive `viewer`/`agent`, pode consultar e-mails de agentes/gestores, owner IDs, status, produtividade e histórico operacional.

O frontend agrava o problema ao renderizar a mesma navegação e os mesmos botões para todos os papéis. Writes podem falhar tardiamente no backend, mas dados de leitura continuam acessíveis.

Orientação:

- definir matriz recurso × ação × papel como contrato versionado;
- aplicar autorização no backend em toda operação e revalidar no Route Handler/BFF;
- filtrar navegação e ações somente como UX, nunca como controle único;
- minimizar schemas por papel: viewer não deve receber e-mail/gestor se não necessário;
- criar testes de contrato para cada role.

### SEC-03 — refresh token em URL — P1

`refreshBackendTokens()` constrói `/auth/refresh?refresh=${encodeURIComponent(refreshToken)}`. Query strings são frequentemente capturadas por access logs, proxies, traces, APM e error reporting. O backend aceita o refresh como parâmetro simples, mas isso não torna a URL um transporte seguro.

Orientação:

- alterar o backend para aceitar `RefreshRequest` no corpo JSON e o BFF para enviar `{"refresh":"..."}`;
- sanitizar logs e bloquear query parameters sensíveis;
- rotacionar/blacklist após uso e testar replay;
- verificar se tokens atuais já apareceram em logs e definir resposta a incidente/rotação se confirmado.

### SEC-04 — senha visível em “Copy as cURL” — análise da alegação — P2/P1 operacional

Não foi encontrado código que monte ou mostre um cURL, coloque senha em URL, logue `payload.password` ou persista a senha. O browser envia a senha no body JSON de `POST /api/auth/login`; ao usar “Copy as cURL” no DevTools, a ferramenta local reconstrói a requisição e inclui o body, portanto a senha aparece no comando copiado. `type="password"` protege apenas a apresentação do campo, não o payload de rede.

Isso não é, isoladamente, vazamento público do produto. Torna-se incidente quando:

- o site é servido sem HTTPS;
- o cURL é colado em ticket/chat/log ou executado em shell com histórico compartilhado;
- extensões, gravações de tela ou suporte remoto capturam o DevTools;
- observabilidade registra request bodies;
- o usuário reutiliza a senha em outros sistemas.

Orientação:

- HTTPS/HSTS obrigatório e nunca documentar comandos com credencial literal;
- mascarar/redigir `password`, `access`, `refresh`, `Authorization` em logs/APM;
- documentação de suporte deve usar placeholders ou leitura interativa de secret;
- rate limiting, lockout progressivo, detecção de credential stuffing e MFA para administradores;
- considerar Server Action/schema de validação, mas reconhecer que qualquer login por senha envia a credencial ao servidor e continuará visível ao dono do browser no DevTools.

### SEC-05 — BFF catch-all e CSRF — P1

O Route Handler `/api/backend/[...path]` encaminha qualquer path e cinco métodos HTTP, adiciona o JWT e copia o body. Não existe allowlist de endpoints, matriz método/path, limite de body específico, validação de `Origin`/`Referer`/`Sec-Fetch-Site` ou token anti-CSRF. `SameSite=Lax` reduz ataques cross-site comuns, mas não cobre todos os cenários (same-site subdomain compromise, browsers/clientes não conformes e evolução futura de integrações).

Orientação:

- substituir o proxy irrestrito por handlers/allowlist de operações conhecidas ou, no mínimo, validar path + método;
- rejeitar mutações com origem não confiável e `Sec-Fetch-Site` incompatível;
- aplicar CSRF token para ações sensíveis quando o modelo de ameaça exigir;
- limitar tamanho e content types; não encaminhar blindly;
- revalidar autenticação/autorização em cada Route Handler sensível.

### SEC-06 — headers e CSP ausentes — P1

`next.config.ts` está vazio. Não há CSP, HSTS, `frame-ancestors`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` nem política de cache explícita para respostas sensíveis. O root layout usa script inline com `dangerouslySetInnerHTML`, e o sandbox injeta script HubSpot dinamicamente; ambos exigem uma CSP desenhada com nonce/hash e allowlist precisa.

Orientação:

- implementar CSP em report-only primeiro, depois enforcement;
- usar nonce/hash para bootstrap de tema e liberar apenas domínios HubSpot necessários na rota sandbox;
- `frame-ancestors 'none'` para o painel, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`;
- HSTS somente após confirmar HTTPS e subdomínios;
- `Cache-Control: no-store` em sessão, auth e dados pessoais.

### SEC-07 — logs e dados de terceiros — P1

Há vários `console.error` server-side com objetos de erro completos. O handler HubSpot registra os primeiros 500 caracteres do body de erro. Dependendo do fornecedor, esse body pode conter IDs, e-mail, contexto ou detalhes de credencial. O backend também registra identidade de login (até 80 caracteres) e mensagens de exception.

Orientação:

- logger estruturado central, com allowlist de campos e redaction automática;
- nunca registrar body bruto de auth/HubSpot nem query strings sensíveis;
- request/correlation ID sem PII;
- política de retenção, acesso e descarte de logs alinhada à LGPD;
- remover `console.error` ad hoc após integrar telemetria sanitizada.

### DEP-01 — Next/sharp vulneráveis e install drift — P1

Resultado de `npm audit --omit=dev`: 2 vulnerabilidades high. A versão instalada (`next@16.2.4`, `sharp@0.34.5`) está no intervalo vulnerável; o audit propõe Next 16.2.12. Não foi aplicada atualização nesta fase.

Orientação:

- atualizar Next/ESLint config em conjunto para uma versão corrigida e suportada;
- regenerar lock de forma determinística e executar `npm ci`, lint, typecheck, build, testes e browser smoke;
- revisar advisories aplicáveis à arquitetura (Proxy bypass é especialmente relevante);
- configurar Dependabot/Renovate, audit em CI e política de SLA por severidade.

### PERF-01 — causa do scroll lento — P1

`SmoothScrollProvider` instala listener global de `wheel` com `{ passive: false }`, chama `preventDefault()` e acumula `deltaY` em um alvo. Cada frame percorre apenas 12% da distância restante. Consequências:

- sensação de atraso e cauda longa após parar a roda;
- perda da física nativa de mouse/trackpad e das preferências do sistema;
- bloqueio do fast path de scroll do compositor;
- conflito com containers `overflow-y-auto` da sidebar/status rail: o handler global tenta mover `window`, não o container sob o cursor;
- `deltaMode` não é normalizado (pixels, linhas ou páginas);
- teclas, scrollbar drag e mudanças programáticas podem dessicronizar `target/current`;
- `html { scroll-behavior: smooth }` adiciona suavização a operações programáticas;
- backgrounds fixed, grain fullscreen animado e glass/backdrop blur tornam cada frame mais caro.

Orientação:

- remover o provider e preservar rolagem nativa como baseline;
- limitar `scroll-behavior: smooth` a navegação por âncora ou ações explícitas;
- se uma experiência especial for realmente necessária, aplicar biblioteca testada somente a um container definido, respeitando nested scroll, reduced motion, teclado e touch;
- medir INP, dropped frames e long tasks em hardware representativo antes/depois.

### PERF-02 — composição gráfica excessiva — P2

O root aplica simultaneamente:

- múltiplos radial gradients com `background-attachment: fixed`;
- pseudo-elemento de grain gigantesco (`inset: -120%`) animado continuamente;
- numerosos `backdrop-filter: blur(20px/28px) saturate(...)`;
- GSAP em login, cards, charts, intro e transições;
- listeners de pointer/RAF em cards.

Em notebooks integrados, alta resolução e mobile, isso pode elevar GPU memory, rasterização e consumo de energia. `prefers-reduced-motion` reduz duração CSS, mas nem todos os efeitos JS consultam a preferência.

Orientação:

- orçamento de animação/blur; grain estático ou desabilitado em mobile/reduced-data;
- respeitar reduced motion em todos os hooks GSAP;
- evitar animação de grandes áreas e propriedades que forçam repaint;
- bundle analyzer e lazy loading de GSAP/features não críticas;
- RUM para LCP, INP, CLS e long tasks.

### ARCH-01 — Client Components e requests duplicados — P2

Telas inteiras são Client Components e carregam dados após mount via `useApiQuery`. Dashboard executa oito chamadas paralelas; `StatusRail` faz mais três, algumas duplicadas. Navegar entre páginas refaz tudo com `cache: no-store`. Não há deduplicação, abort controller, retry/backoff, stale-while-revalidate ou cache de dados.

Orientação:

- buscar dados iniciais em Server Components/DAL quando possível;
- passar DTO mínimo para ilhas cliente;
- consolidar endpoints de overview no backend ou usar cache/deduplicação consciente;
- adicionar `AbortController` para desmontagem/race e estratégia explícita de retry;
- usar loading/error boundaries e streaming por seção;
- não chamar Route Handlers internos a partir de Server Components; chamar o backend/DAL diretamente no servidor.

### ARCH-02 — paginação falsa e perda de navegabilidade — P1

`requestPaginated` normaliza `{items,count}` para `{results,count,next:null,previous:null}`. As telas sempre pedem limites fixos (40/100) e não oferecem paginação ou cursor. Isso mascara registros além do limite e pode levar administradores a concluir que a lista está completa.

Orientação:

- modelar o envelope Django Ninja real e preservar limit/offset/count;
- implementar paginação, infinite scroll acessível ou virtualização conforme volume;
- exibir “mostrando X de Y”;
- filtros/search devem ser server-side para datasets grandes.

### ARCH-03 — falhas parciais derrubam overviews inteiros — P2

Os loaders usam `Promise.all`. Uma falha de analytics, metrics ou agents impede toda a dashboard/overview de renderizar, mesmo quando health e queue estão disponíveis.

Orientação:

- separar dados essenciais de complementares;
- usar boundaries por widget ou `Promise.allSettled` com estados degradados;
- diferenciar 401, 403, 404, 409, 429, 5xx e indisponibilidade de integração;
- indicar timestamp/freshness de cada snapshot.

### UX-01 — RBAC e ações perigosas — P1

Menu e botões administrativos são iguais para todos os roles. Inativar agente, autoassign, manual assign, force reassign e sync não têm confirmation dialog robusto, resumo de impacto ou step-up authentication. `sync-novo` é descrito como ação administrativa, mas é um botão direto.

Orientação:

- capability map fornecido pela sessão/backend, não comparações dispersas de strings;
- esconder/desabilitar com explicação conforme papel e manter enforcement servidor;
- confirmation para ações de impacto, incluindo alvo, efeito e idempotência;
- audit trail visível com ator, timestamp, motivo e correlation ID;
- feedback persistente e recuperação após 409/partial failure.

### UX-02 — acessibilidade e interação — P2

Pontos positivos: HeroUI v3/React Aria, labels, `aria-label` em icon buttons, `aria-current`, alerts e reduced motion CSS.

Gaps:

- alguns controles nativos usam `onClick` enquanto componentes HeroUI usam `onPress`; isso não é automaticamente inválido, mas deve haver consistência de foco/keyboard;
- filtros customizados deveriam ser radio group/toggle group semântico;
- charts são visuais e carecem de alternativa tabular/descrição completa;
- foco após navegação, modal e erros precisa de browser + screen reader verification;
- filtros horizontais com mask podem esconder affordance;
- não há testes automatizados de acessibilidade.

### UI-01 — aderência ao HeroUI v3 — P2

O projeto acerta os fundamentos v3:

- `@import "tailwindcss"` antes de `@import "@heroui/styles"`;
- sem `HeroUIProvider` legado;
- uso extensivo de componentes compostos (`Card.Header`, `Alert.Content`, `Modal.Dialog`, `Tabs.List`);
- `onPress` nos controles HeroUI;
- Tailwind CSS v4 e tokens CSS.

Gaps e tendências atuais:

- os tokens HeroUI v3 são orientados a cores semânticas e `oklch`; o tema Judah usa majoritariamente hex/rgb e duplica famílias `--color-*` e tokens semânticos;
- customizações profundas misturam contrato HeroUI, tokens próprios e classes utilitárias, aumentando risco em upgrades;
- raw HTML controls coexistem com React Aria sem abstração clara;
- faltam stories/catalog, testes visuais, matriz de estados e documentação do design system;
- `@fontsource/ibm-plex-mono` e `@fontsource/space-grotesk` estão instalados mas não usados; dez pesos de Inter/Montserrat são importados globalmente.

Orientação:

- consolidar tokens semânticos em `oklch`, com contraste verificado em light/dark/high-contrast;
- criar primitive wrappers somente onde houver regra Judah recorrente;
- documentar anatomy, variants, sizes, states, motion e content guidelines;
- remover pacotes/fontes não usados e limitar pesos/subsets;
- manter HeroUI v3 sem reintroduzir providers, APIs flat ou padrões v2.

### CODE-01 — resíduos, slop e código morto — P2/P3

Encontrados:

- `next.config.ts` placeholder vazio;
- assets padrão do scaffold Next (`next.svg`, `vercel.svg`, `globe.svg`, `file.svg`, `window.svg`) sem uso;
- fontes IBM Plex Mono e Space Grotesk instaladas sem import/uso;
- helper `staggerFadeUp` sem uso detectado;
- comentários e README historicamente desatualizados;
- string visual `v0.1.0 • backend live` é hardcoded e pode afirmar “live” sem prova de readiness;
- console errors ad hoc no servidor;
- não há testes frontend, E2E, component tests, Storybook ou CI específico visível no webapp;
- não há `global-error.tsx`, error boundaries por rota, `loading.tsx` ou not-found customizado.

Não foram encontrados `debugger`, `alert()` de browser, `console.log` cliente, TODO/FIXME relevantes, senha hardcoded ou token exposto no bundle. O `__debug__` do Django só é montado quando `DEBUG` está ativo; isso precisa permanecer impossível em produção.

### LGPD-01 — minimização, finalidade e direitos — P1

Dados tratados incluem e-mail/nome de usuário, e-mail de contato do ticket, e-mails de agentes e gestores, disponibilidade, produtividade, tempos, CSAT, reatribuições e identificação HubSpot. A interface não explicita finalidade, retenção, base legal, perfil autorizado, exportação/correção/exclusão ou auditoria de acesso.

Orientação:

- inventário de dados e data-flow por tela/endpoint;
- classificar controlador/operador e finalidade de cada integração;
- minimizar payloads e mascarar contato quando não necessário;
- autorização por função e trilha de acesso a dados pessoais;
- política de retenção/descarte para logs, métricas e histórico;
- processo para direitos do titular e incident response;
- privacy notice interno e registro de compartilhamento com HubSpot/OpenAI/Pinecone quando aplicável;
- não confundir criptografia em trânsito com conformidade LGPD completa.

## 5. Segurança do sandbox HubSpot

O token privado permanece server-side, o que é correto. O endpoint gera um visitor token após validar sessão e entrega ao browser somente o token efêmero. Riscos remanescentes:

- rota aceita qualquer papel autenticado;
- PII do usuário é enviada ao HubSpot sem capability específica;
- resposta de erro HubSpot é parcialmente logada;
- script externo é injetado sem CSP/SRI e com portal ID público;
- domínio staging está hardcoded em mensagem de diagnóstico;
- não há rate limit por usuário/IP.

Planning deve definir se sandbox é ferramenta administrativa, de suporte ou apenas teste não-production e aplicar papel, feature flag, ambiente, rate limit e logging adequados.

## 6. Qualidade e validações executadas

| Verificação | Resultado |
|---|---|
| `npm run lint` | Passou |
| `npx tsc --noEmit` | Passou |
| `npm run build` | Passou; 13 rotas geradas |
| Build/root | Warning: Turbopack inferiu `C:\Projetos Febrate` por múltiplos lockfiles |
| `npm ls` | Falhou com `ELSPROBLEMS`: Next 16.2.4 inválido para requisito 16.2.10 |
| `npm audit --omit=dev` | Falhou: 2 vulnerabilidades high (`next`, `sharp`) |
| Browser/Lighthouse | Não executado; servidor local não permaneceu disponível no ambiente |
| Backend/prod/Supabase | Não acessados; research read-only local |

## 7. Prioridades recomendadas para a etapa de planning

### Gate 0 — contenção de segurança

1. Proteger mutações públicas (`sync-novo`, special schedules).
2. Aplicar RBAC consistente às leituras administrativas e minimizar schemas.
3. Atualizar Next/sharp para versões corrigidas e reconciliar lockfiles.
4. Mover refresh token da query para body e avaliar logs existentes.
5. Definir allowlist do BFF, CSRF/origin checks, CSP e security headers.

### Gate 1 — sessão e autorização

1. DAL server-only para sessão/capabilities.
2. Autorização em cada Route Handler e ação.
3. Proteção server-side completa de todas as rotas, incluindo `/agents`.
4. Capability-driven UI e testes por role.
5. Rate limiting/MFA/lockout para administração.

### Gate 2 — performance e arquitetura de dados

1. Remover smooth scroll global.
2. Server Components/streaming para dados iniciais.
3. Deduplicar calls e separar falhas por widget.
4. Paginação real e filtros server-side.
5. Reduzir grain, blur, fontes e GSAP; medir Web Vitals.

### Gate 3 — design system e acessibilidade

1. Consolidar tokens HeroUI v3/Tailwind v4 em semântica `oklch`.
2. Catálogo de componentes, estados e guidelines.
3. Axe + keyboard + screen reader + contrast matrix.
4. Alternativas textuais/tabulares para charts.
5. Reduced motion completo para CSS e GSAP.

### Gate 4 — cobertura funcional do produto

Priorizar com stakeholders quais superfícies pertencem ao webapp:

- usuários, papéis e permissões;
- gates/feature flags/readiness;
- conectores e suas credenciais/saúde sem expor secrets;
- agentes de IA, execuções, custos e auditoria;
- knowledge base e igrejas;
- ticket detail/lifecycle/handoff;
- observabilidade, incidentes e audit log.

Não criar controles até existir contrato backend autorizado, versionado e testável.

## 8. Critérios mínimos para o futuro master plan

O planning deve produzir tarefas com owner/layer, dependências, migrations quando necessárias, rollback e testes. Critérios mínimos:

- nenhum endpoint mutável administrativo público;
- matriz RBAC coberta por testes negativos e positivos;
- nenhum secret/token/password em URL ou logs;
- build usa exatamente as versões declaradas no lock;
- zero vulnerabilidade high/critical conhecida ou exceção formal com prazo;
- scroll nativo sem interception global e métricas de INP/frames registradas;
- paginação e contagem reais;
- falhas parciais não derrubam toda a dashboard;
- CSP/headers validados em staging, incluindo sandbox HubSpot;
- WCAG 2.2 AA para fluxos críticos;
- trilha de auditoria para ações sensíveis;
- evidência browser desktop/mobile e smoke pós-deploy separada de lint/build.

## 9. Decisões que o planning não deve assumir

- não assumir que `viewer` pode ver PII operacional só porque hoje recebe JWT;
- não assumir que `SameSite=Lax` encerra o tema CSRF;
- não assumir que HTTP 200/202 prova conclusão de sync, assignment ou integração;
- não assumir que todos os gates do backend devem ser mutáveis via UI;
- não implementar gestão de secrets no browser;
- não manter animação/smooth scroll por estética sem orçamento e medição;
- não executar migração, deploy, backfill, sync ou alteração de produção como parte automática do planning.

## 10. Referências técnicas consultadas

- guias versionados do Next.js 16.2: authentication, data security, CSP, Route Handlers, Proxy e production checklist em `node_modules/next/dist/docs/`;
- documentação atual do Next.js 16 via Context7 (`/vercel/next.js`);
- documentação/migração HeroUI v3 via Context7 (`/llmstxt/heroui_react_llms_txt`);
- código e schemas locais são a autoridade para os contratos efetivamente auditados.

## 11. Conclusão

O frontend possui uma base visual moderna e uma decisão arquitetural sólida ao interpor um BFF e cookies `HttpOnly`, além de boa adoção inicial do HeroUI v3. O risco atual não está na ausência de polimento: está nas fronteiras de autorização, transporte de token, proxy genérico, dependências vulneráveis e divergência entre contrato documentado e executável.

A próxima etapa deve começar por um master plan de segurança/contratos, seguido de sessão/RBAC, performance/arquitetura de dados e somente então expansão funcional e refinamento visual. Implementar novas telas antes dos Gates 0 e 1 ampliaria a superfície de risco e consolidaria contratos inseguros.
