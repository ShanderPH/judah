# Handoff — security assessment remediation

## Implementado

- SEC-01: autorização manager/admin nas três rotas Django, com JWT, paginação e schemas preservados.
- SEC-02: `sandbox.use` antes de configuração/fetch HubSpot; sessão ausente 401 e capability ausente 403.
- SEC-03: erros públicos estáveis; logs estruturados só com check, tipo e request ID, sem mensagem da exceção.
- SEC-04: destino resolvido same-origin; rejeição de backslash/controles e formas codificadas; encoding legítimo preservado.
- TDD: baseline completo e regressões RED documentados; 33 testes backend focados e 38 webapp focados GREEN antes de VERIFY.

## Arquivos de código/teste

Todos relativos a `C:/Projetos Febrate/judah/`:

- `apps/analytics/api.py`, `apps/analytics/tests/test_api.py`
- `apps/support/api.py`, `apps/support/tests/test_metrics_api.py`
- `apps/health/api.py`, `apps/health/tests/test_api.py`
- `webapp/app/api/hubspot/visitor-token/route.ts`
- `webapp/app/auth/refresh/route.ts`
- `webapp/src/lib/auth/visitor-token-route.test.ts`
- `webapp/src/lib/auth/refresh-route.test.ts`

Documentação/evidências somente nesta request. Assessment restrito e drift preexistente não incluídos.

## Verificação local segura

```powershell
$env:JUDAH_TEST_DATABASE_URL='sqlite:///./.test-security.sqlite3'
$env:PYTEST_ADDOPTS='-q --tb=short -p no:cacheprovider'
.venv/Scripts/python.exe run_tests_local.py
.venv/Scripts/ruff.exe check apps common core
.venv/Scripts/ruff.exe format --check apps common core
.venv/Scripts/mypy.exe apps core common
```

Mypy exige settings test e variáveis sintéticas; usar o mesmo ambiente do runner,
sem credenciais ou banco remoto. No diretório `webapp`:

```powershell
npm.cmd test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

Browser sub-agent: duas origens exclusivamente locais, sessão sintética e handler
real transpilado; confirmar origem após redirect e contador zero na segunda
origem. Nunca acessar provedores reais. Registrar indisponibilidade de browser
explicitamente, sem chamar harness HTTP de E2E do Next.js.

## Prioridades para VERIFY e riscos

- Confirmar 401/403/200 das três rotas diretas e zero consulta do recurso para papéis negados.
- Confirmar zero fetch HubSpot para sessão/capability ausentes, inclusive sem configuração do provedor.
- Confirmar erro/hostname/segredo sintético ausente no body/headers/logs; logs mantêm correlação.
- Confirmar query/fragment, percent literal e escrita/limpeza de cookies preservados.
- Readiness mantém mensagens estáticas preexistentes de tabela ausente e o probe informativo de conversation_cycles não passa a alterar 200/503.
- Origem confiável continua sendo request.url; configuração de proxies está fora do hotfix.
- Browser real, revisão humana, PR/checks e deploy possuem gates próprios; não marcar DONE sem cumpri-los.
