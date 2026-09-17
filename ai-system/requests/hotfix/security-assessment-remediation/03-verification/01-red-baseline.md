# V-01 — RED antes de código de produção

2026-09-17, Python 3.14.4; HEAD e main remoto confirmados em
`6f663265369fca7d2efccc780434cc5cdd4f0a61`.

## Comandos e resultados

Backend focado, SQLite privado, configuração sintética do runner:

```powershell
$env:JUDAH_TEST_DATABASE_URL='sqlite:///./.test-security.sqlite3'
$env:PYTEST_ADDOPTS='apps/analytics/tests/test_api.py apps/support/tests/test_metrics_api.py apps/health/tests/test_api.py --no-cov -q'
.venv/Scripts/python.exe run_tests_local.py
```

Resultado: **13 failed, 15 passed**. SEC-01: viewer/agent recebem 200 nas três
rotas; relatório inexistente chega a 404 em vez de negar antes da consulta.
SEC-03: readiness inclui `db down`, `schema unavailable`, `cache down` e
`RuntimeError: jwt broken` em vez de `error`.

Suíte completa, antes de qualquer alteração em produção:

```powershell
$env:PYTEST_ADDOPTS='-q --tb=short -p no:cacheprovider'
.venv/Scripts/python.exe run_tests_local.py
```

**13 failed, 831 passed, 43 skipped**, 92,76s; cobertura **90,54%**.
As 13 falhas são exatamente as regressões novas. Os testes preexistentes
executados permanecem verdes. Os skips não equivalem a validação PostgreSQL.

Cinco casos adicionais isolam cada probe e verificam contexto de log e ausência
de credenciais sintéticas. Executados em outro SQLite privado antes do patch:
`PYTEST_ADDOPTS='apps/health/tests/test_api.py --no-cov -q -p no:cacheprovider'`.
Resultado: **6 failed, 3 passed**; as quatro dependências refletem a mensagem
e conversation_cycles expõe `RuntimeError` em vez de código estável.

Webapp, diretório `webapp`:

```powershell
npm.cmd test -- src/lib/auth/visitor-token-route.test.ts src/lib/auth/refresh-route.test.ts
npm.cmd test
```

Focado: **20 failed, 14 passed**. Completo: **20 failed, 42 passed**, 11 arquivos.
SEC-02: viewer/agent/manager recebem 200; sem configuração recebem 503 antes
de autenticação/autorização. SEC-04: backslash e tab redirecionam à segunda
origem local; codificações e caminhos normalizados não recebem fallback.
Todos os 28 testes preexistentes do webapp passaram.

A primeira execução tinha uma premissa incorreta no teste: NextRequest normaliza
127.0.0.1 para localhost. Ajustado somente o teste e repetido RED; essa falha de
harness foi descartada. `fetch` está integralmente substituído por mock.

## Gate

V-01 satisfeito: regressões atingem as decisões vulneráveis, sem falhas de
import/configuração no RED aceito. Nenhum arquivo de produção foi alterado antes
desses resultados. As deleções/arquivos preexistentes permanecem fora do escopo.
