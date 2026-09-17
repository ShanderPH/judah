# Plano mestre — hotfix de remediação do security assessment

## 1. Controle da mudança

| Campo | Valor |
| --- | --- |
| Request | `hotfix/security-assessment-remediation` |
| Ciclo | M — hotfix de segurança |
| Branch de trabalho | `hotfix/security-assessment-remediation` |
| Base verificada | `main` / `origin/main` em `6f663265369fca7d2efccc780434cc5cdd4f0a61` |
| Destino | PR urgente diretamente para a branch protegida `main`, sem branch intermediária |
| Fonte | `docs/security-assessment.md`, 16/09/2026 |
| Estado deste artefato | VERIFY — correções implementadas em 17/09/2026; gates locais verdes, browser real pendente |

Neste repositório, a branch principal se chama `main`. Portanto, “merge direto na master” significa um PR de hotfix da branch acima diretamente para `main`. Não haverá commit direto na branch protegida, bypass de revisão, push forçado ou merge antes dos gates deste plano.

## 2. Objetivo e resultado esperado

Corrigir, em uma única mudança pequena e auditável, os quatro achados confirmados no assessment:

| ID | Severidade | Falha confirmada | Estado desejado |
| --- | --- | --- | --- |
| SEC-01 | Média | Três endpoints Django de métricas permitem viewer/agent apesar da política manager/admin | Sem identidade: 401; viewer/agent: 403; manager/admin: 200 |
| SEC-02 | Média | O handler de visitor token chama HubSpot sem exigir `sandbox.use` | Papéis sem a capability recebem 403 e causam zero chamadas ao provedor |
| SEC-03 | Baixa | O readiness público devolve `str(exc)` de dependências | Resposta mantém apenas estados/códigos estáveis; detalhes redigidos ficam nos logs internos |
| SEC-04 | Baixa | `next=/\\host/path` pode ser normalizado para outra origem | Todo redirect resolvido permanece na origem confiável e em path interno permitido |

O hotfix preservará contratos legítimos: paginação e schemas de métricas, emissão do visitor token para admin, semântica HTTP 503 do readiness degradado, refresh de cookies e redirect para caminhos internos.

## 3. Escopo

### Incluído

- Testes de regressão escritos e executados antes de cada alteração de produção.
- Autorização server-side manager/admin em `list_reports`, `get_report` e `list_queue_metrics`.
- Autorização por capability `sandbox.use` no Route Handler do visitor token, antes de ler credencial operacional ou chamar `fetch`.
- Contrato público sanitizado do readiness com log interno redigido e `request_id`, se disponível no padrão atual do backend.
- Resolução e validação same-origin do parâmetro `next`, incluindo formas codificadas e normalização de barra invertida.
- Testes focados, suíte completa, lint, type check, build e verificação local HTTP/browser compatíveis com os riscos.
- Documentação de rollback e evidência de verificação antes do PR.

### Fora deste hotfix

- PV-01 a PV-07 e HD-01 a HD-07, por ainda dependerem de validação, política organizacional ou mudança de escopo.
- Upgrade de Django, lock/SBOM e SCA integral. O assessment recomenda a atualização, mas não comprovou exploração no JUDAH; isso deve seguir em PR próprio para não acoplar uma alteração ampla de dependências às quatro correções concentradas.
- Mudanças de HMAC, migrations, RLS/grants, banco, Redis, HubSpot, Jira, n8n, Railway ou secrets.
- Alteração de políticas de papéis/capabilities, criação de tenant ou refactor geral de autenticação.
- Testes de carga, exploração de CVEs, chamadas a provedores reais ou testes contra bases não locais.

## 4. Princípios obrigatórios de implementação

1. **TDD estrito por achado:** criar o teste de regressão, executar e registrar RED pelo motivo esperado; somente então editar código de produção; executar GREEN; por fim refatorar sem mudar o contrato e executar GREEN novamente.
2. **Menor camada responsável:** aplicar autorização no endpoint que protege o recurso; manter a proteção do BFF como defesa em profundidade. Sanitizar o readiness no ponto em que o erro é transformado em resposta. Validar redirect após resolução pelo parser de URL.
3. **Clean Code:** funções pequenas com uma responsabilidade, nomes orientados ao contrato de segurança, guard clauses, dependências existentes e ausência de abstrações genéricas sem segundo uso real.
4. **Negar por padrão:** sessão ausente continua 401; sessão sem privilégio retorna 403; destino de redirect inválido cai em `/dashboard`; erro de probe nunca é refletido ao cliente.
5. **Sem vazamento de dados:** não registrar tokens, cookies, credenciais, bodies sensíveis ou mensagens de exceção sem passar pela política de redação existente.
6. **Sem efeitos remotos:** mocks/fakes interceptam HubSpot e dependências; o browser usa somente duas origens locais controladas. `fetch` real deve falhar o teste caso seja acionado.
7. **Preservação do workspace:** tocar e adicionar somente os arquivos listados neste plano. As deleções e arquivos não rastreados preexistentes não pertencem ao hotfix.

## 5. Estratégia técnica e sequência TDD

### V-01 — Congelar os contratos vulneráveis em testes RED

Criar primeiro os testes abaixo, sem alterar arquivos de produção:

- `apps/analytics/tests/test_api.py`: matriz das duas rotas para anonymous/viewer/agent/manager/admin, incluindo relatório por data e preservação do schema/paginação.
- `apps/support/tests/test_metrics_api.py`: ampliar a cobertura de `/support/queue/metrics/` com a mesma matriz de papéis e manter os testes atuais de serialização.
- `webapp/src/lib/auth/visitor-token-route.test.ts`: invocar `POST` com sessão simulada para os quatro papéis; exigir 401 sem sessão, 403 e zero `fetch` para viewer/agent/manager, e uma única chamada simulada para admin. Verificar que nenhum segredo de servidor aparece no JSON.
- `apps/health/tests/test_api.py`: substituir a expectativa que hoje aceita `db down`, `cache down` e `jwt broken`; exigir 503, status público estável e ausência dos marcadores/exceções sintéticas.
- `webapp/src/lib/auth/refresh-route.test.ts`: invocar o handler com sessão simulada e cobrir `/dashboard`, query/fragment internos, `//host`, `/\\host`, barras invertidas codificadas, esquema absoluto, controles, string inválida e ausência de `next`.

Registrar em `03-verification/01-red-baseline.md` o comando, o teste que falhou e por que a falha demonstra cada vulnerabilidade. Uma falha por import, fixture ou configuração não conta como RED válido; o teste precisa alcançar a decisão de segurança.

**Gate V-01:** os testes preexistentes continuam verdes e cada novo teste vulnerável falha pelo comportamento descrito no assessment. Nenhum código de produção pode ser editado antes deste gate.

### BE-01 — Corrigir SEC-01 na autoridade Django

Arquivos previstos:

- `apps/analytics/api.py`
- `apps/support/api.py`
- testes definidos em V-01

Aplicar `require_manager_or_admin` às duas operações analytics e a `list_queue_metrics`. Manter o JWT global e a política do BFF; não duplicar consultas de capability no frontend e não mover autorização para services de leitura sem contexto de request.

Ordem de decorators deverá preservar a assinatura inspecionada pelo Django Ninja e a paginação. O padrão já usado no módulo support é a referência local; os testes precisam provar que a combinação autorização + paginação não altera o JSON de sucesso.

**Gate BE-01:** 401/403/200 coerentes nas três rotas, manager/admin preservam resposta e viewer/agent não acionam a consulta de dados quando isso puder ser verificado sem fragilidade.

### FE-01 — Corrigir SEC-02 antes da chamada HubSpot

Arquivos previstos:

- `webapp/app/api/hubspot/visitor-token/route.ts`
- `webapp/src/lib/auth/visitor-token-route.test.ts`

Reutilizar `hasCapability` e `CAPABILITIES.sandboxUse`. Fazer a checagem imediatamente após confirmar a sessão e antes de ler a configuração do provedor ou executar `fetch`. Retornar uma resposta genérica 403 pelo padrão de respostas sensíveis já usado no webapp.

Não alterar o payload HubSpot, identidade derivada da sessão, escopos, token de servidor, portal ou fluxo da página `/sandbox-chat`.

**Gate FE-01:** viewer/agent/manager retornam 403 e `fetch` permanece em zero; admin preserva o fluxo; sessão ausente permanece 401; logs e payloads não contêm segredo.

### BE-02 — Corrigir SEC-03 sem quebrar probes

Arquivos previstos:

- `apps/health/api.py`
- `apps/health/tests/test_api.py`

Separar o detalhe interno do contrato público. Cada probe deve mapear exceções para um valor público estável, por exemplo `error`, mantendo o nome lógico do check necessário aos monitores. Registrar internamente o tipo do erro, o check e o request ID por meio do logger/redactor existente, sem incluir credenciais ou serializar a exceção na resposta.

Antes de escolher os campos finais, inventariar os consumidores versionados do JSON e documentar qualquer ajuste. A rota continua pública para health checks, com 200 quando saudável e 503 quando qualquer dependência obrigatória falha.

**Gate BE-02:** os marcadores sintéticos e mensagens de driver não aparecem em body/headers; o status 503 e a identificação estável do check degradado são preservados; o log interno é útil e redigido.

### FE-02 — Corrigir SEC-04 validando o destino resolvido

Arquivos previstos:

- `webapp/app/auth/refresh/route.ts`
- `webapp/src/lib/auth/refresh-route.test.ts`

Encapsular a decisão em uma função pura e pequena que recebe o valor não confiável e a URL base. Resolver com `URL`, rejeitar barras invertidas/caracteres de controle, exigir igualdade exata de `origin` e aceitar apenas protocolo HTTP(S) herdado da aplicação e pathname iniciado por `/`. Em qualquer erro ou divergência, retornar `/dashboard` na origem da request.

Usar a URL validada apenas depois dessa comparação. Não criar allowlist de hosts por variável nova neste hotfix e não alterar o fluxo de sessão/cookies.

**Gate FE-02:** nenhum caso malicioso produz origem externa; paths internos, query e fragment válidos permanecem funcionais; sessão ausente continua indo para `/login` e limpando cookies.

### R-01 — Refactor controlado

Depois de todos os gates verdes:

- remover duplicação somente quando a extração deixar o contrato mais explícito;
- manter helpers junto ao único domínio que os usa;
- confirmar type hints nas funções públicas Python e tipos estritos TypeScript, sem `Any`/`any` novo;
- pesquisar `TODO`, `FIXME`, `print(` e `console.log` nos arquivos tocados;
- executar novamente todos os testes focados antes de ampliar a verificação.

Refactor que ultrapasse os arquivos previstos, altere arquitetura ou revele necessidade de mais de cinco arquivos de produção promove o trabalho para Ciclo F e interrompe o hotfix para nova aprovação.

## 6. Matriz de aceite

| Cenário | Resultado obrigatório |
| --- | --- |
| Métricas sem JWT | 401 |
| Métricas com viewer ou agent | 403 em todas as três operações |
| Métricas com manager ou admin | 200, schema e paginação preservados |
| Visitor token sem sessão | 401, zero chamadas HubSpot |
| Visitor token viewer/agent/manager | 403, zero chamadas HubSpot |
| Visitor token admin | Contrato atual preservado com exatamente uma chamada mockada |
| Readiness saudável | 200 e checks estáveis |
| Readiness degradado | 503, check identificável, nenhum `str(exc)`, hostname ou marcador sintético no body |
| Refresh com path interno | Same-origin, cookies preservados |
| Refresh com `//`, `/\\`, `%5C`, esquema, controle ou URL inválida | Fallback same-origin `/dashboard` |
| Refresh sem sessão | `/login` same-origin e cookies limpos |

## 7. Verificação segura

### Backend local descartável

O comando canônico abaixo força SQLite privado e placeholders sintéticos. Ele deve ser usado para a suíte backend completa; nenhuma `DATABASE_URL` remota pode estar ativa:

```powershell
.venv\Scripts\python.exe run_tests_local.py
```

Antes de qualquer execução alternativa, confirmar que `common.database_safety.assert_safe_test_database` aceita o destino e que o host é local. Testes contra banco não local exigem pré-aprovação explícita e não fazem parte deste plano.

### Webapp

```powershell
Set-Location webapp
npm.cmd test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

As dependências já instaladas devem ser usadas. Não executar `npm install`, alterar lockfile ou acessar rede como parte deste hotfix.

### Qualidade Python e segurança

```powershell
.venv\Scripts\ruff.exe check apps common core
.venv\Scripts\ruff.exe format --check apps common core
.venv\Scripts\mypy.exe apps core common
.venv\Scripts\ruff.exe check apps common core --select S --no-cache
```

O resultado SAST deve ser comparado apenas nos arquivos tocados e com o baseline do assessment; o hotfix não tentará corrigir os 2.115 alertas históricos em massa.

### HTTP/browser local

Em uma aplicação local descartável, o VERIFY deve repetir a matriz de papéis nas três rotas Django e usar uma única instância serializada de browser para confirmar que os redirects maliciosos nunca navegam para a segunda origem local controlada. Capturar a evidência em `03-verification/`, sem tokens nos screenshots, URLs ou logs.

## 8. Fluxo colaborativo e integração em `main`

1. Revalidar `git status`, `HEAD`, base de `origin/main` e a watch list antes de iniciar Implementation.
2. Se `origin/main` avançar, atualizar a branch de forma não destrutiva e repetir RED/GREEN; nunca usar `reset --hard` ou sobrescrever alterações preexistentes.
3. Um implementador por domínio de arquivo. Backend e webapp podem avançar em paralelo apenas quando não houver arquivos compartilhados; o browser permanece serializado.
4. Commits pequenos e Conventional Commits, em inglês, por exemplo `fix(security): enforce metrics authorization` e `fix(webapp): constrain auth redirects`.
5. Preencher `HANDOFF.md` antes de VERIFY e atualizar `STATUS.md` em cada transição.
6. Revisão obrigatória por outro colaborador com foco em bypass, ordem de decorators, chamadas externas e vazamento de mensagens.
7. Abrir PR de hotfix diretamente para `main`, incluindo a matriz de aceite, evidência RED/GREEN, comandos executados, riscos e rollback. Não misturar as deleções/arquivos não rastreados já existentes.
8. Exigir branch protection, checks verdes e aprovação humana. Merge preferencial por squash depois dos gates; sem auto-merge se houver drift ou falha intermitente.

## 9. Deploy, observabilidade e rollback

Antes do merge, registrar em `05-deployment/rollback.md` o SHA anterior e o procedimento de reversão por revert do commit/PR. Não há migration nem mudança de dados; o rollback esperado é somente de código.

Após merge e deploy autorizado:

1. Confirmar que API, worker e beat executam o SHA esperado, sem assumir que um deploy verde prova o comportamento.
2. Fazer smoke test seguro de 401/403/200 com contas sintéticas autorizadas; não usar credenciais em logs.
3. Verificar health/readiness: 200 saudável ou 503 sanitizado durante falha controlada em ambiente de staging. Não induzir falha em produção.
4. Confirmar que a emissão admin de visitor token continua funcional em sandbox formal e que nega papéis inferiores antes do provedor. Essa chamada externa exige autorização operacional separada.
5. Observar por pelo menos 15 minutos taxas de 401/403/5xx, falhas de readiness e erros de refresh, sem alterar flags ou provedores.

Reverter se manager/admin perder acesso legítimo, probes ficarem incompatíveis com o monitor, refresh interno entrar em loop ou o fluxo admin da sandbox quebrar. Uma elevação esperada de 403 para chamadas antes indevidas não é, isoladamente, motivo de rollback.

## 10. Riscos residuais e decisões pendentes

- Consumidores diretos desconhecidos podem depender indevidamente das métricas com viewer/agent; confirmar em logs/configuração autorizados antes do deploy, sem relaxar a política no hotfix.
- Monitores podem interpretar mensagens textuais do readiness; preservar nomes dos checks e alinhar o parser antes do merge.
- A origem confiável usada por SEC-04 será a própria `request.url`; proxies e headers efetivos continuam tema de PV-03 e não devem ser inferidos neste patch.
- A capability `sandbox.use` permanece exclusiva de admin conforme contrato atual. Alterá-la exige decisão de produto e segurança.
- O assessment é um arquivo local não rastreado e marcado como uso interno restrito. Sua inclusão no PR deve respeitar a classificação definida pelo responsável; o hotfix não o adicionará automaticamente ao stage.
- O risco de supply chain do Django deve virar uma request separada e prioritária, com upgrade, lock/SBOM, SCA e regressão funcional próprios.

## 11. Definition of Done

- [x] Evidência RED válida para SEC-01 a SEC-04 criada antes de código de produção.
- [x] Correções mínimas implementadas e refatoradas com todos os testes GREEN.
- [ ] Matriz de aceite completa em backend direto, Route Handlers e browser local quando aplicável.
- [x] Ruff, formatação, mypy, Vitest, ESLint, TypeScript e build limpos.
- [x] SAST focado sem novo achado nos arquivos tocados.
- [x] Nenhum TODO/FIXME/print/console.log, segredo, token ou exceção interna introduzido.
- [x] `HANDOFF.md`, evidências em `03-verification/`, rollback e `STATUS.md` atualizados.
- [ ] Diff contém somente arquivos do hotfix; drift preexistente permanece fora do stage/PR.
- [ ] Revisão humana e branch protection aprovadas.
- [ ] PR mergeado diretamente em `main` e smoke pós-deploy autorizado concluído.

## 12. Ponto de parada deste ciclo

Este artefato encerra Planning. A branch foi criada, mas nenhum teste, código de produção, commit, push, PR, merge, deploy ou mutação externa foi executado. Implementation começa somente após aprovação explícita deste plano e deve iniciar por V-01, os testes RED.

Atualização de execução em 17/09/2026: o parágrafo acima registra o encerramento
histórico de Planning. O usuário autorizou a execução; implementação e gates
automatizados locais foram concluídos. Consultar `03-verification/04-final-gates.md`
e `STATUS.md` para o estado atual e o bloqueio de browser real. Não marcar DONE
nem promover draft/merge/deploy enquanto os gates pendentes não forem satisfeitos.
