# Fixture local para verificacao de interface

Esta fixture cria um administrador descartavel, dois agentes sinteticos e 105 atendimentos locais. Ela existe para validar autenticacao, permissoes, estados da interface e paginacao alem de 100 itens sem acessar Supabase, Railway, HubSpot ou qualquer banco compartilhado.

## Regras de seguranca

- Use somente SQLite sob `webapp/.playwright-mcp/` ou PostgreSQL local com nome `judah_test`/`judah_ci_*`.
- O script chama `common.database_safety.assert_safe_test_database` e recusa alvos nao descartaveis.
- Defina a senha apenas em `JUDAH_UI_TEST_PASSWORD`; nao grave a senha em arquivo, log, screenshot ou commit.
- Os identificadores `UI-VERIFY-*` e dominios `local.judah.test` sao reservados para essa fixture.
- Nao confirme atribuicao, inativacao, sync ou force-reassign durante uma verificacao somente leitura.

## Criacao idempotente

Execute a partir da raiz do repositorio Judah em PowerShell:

```powershell
$env:DJANGO_ENV = "test"
$env:DATABASE_URL = "sqlite:///./webapp/.playwright-mcp/judah_ui_verification.sqlite3"
$env:DJANGO_SECRET_KEY = "local-ui-verification-only"
$env:OPENAI_API_KEY = "local-ui-verification-only"
$env:PINECONE_API_KEY = "local-ui-verification-only"
$env:HUBSPOT_ACCESS_TOKEN = "local-ui-verification-only"
$env:HUBSPOT_APP_SECRET = "local-ui-verification-only"
$env:JUDAH_UI_TEST_PASSWORD = Read-Host "Senha descartavel da fixture"

.venv\Scripts\python.exe -m common.database_safety
.venv\Scripts\python.exe manage.py migrate --noinput
Get-Content webapp\scripts\seed_local_ui_verification.py | .venv\Scripts\python.exe manage.py shell
```

Login local: `ui-verification-admin@local.judah.test` com a senha informada no prompt. O script pode ser executado novamente: usuario, agentes e fila sao atualizados por chaves estaveis.

Inicie a API apontando para o mesmo `DATABASE_URL` e o WebApp com `JUDAH_API_URL=http://127.0.0.1:8000/api/v1`. A verificacao deve cobrir desktop/mobile, teclado, axe, console/rede, estados degradados e a terceira pagina da fila (`81-105 de 105`).

Com SQLite e credenciais externas placeholder, `/support/queue/health` pode ficar degradado e o token do sandbox HubSpot pode responder 503. Esses retornos so servem para provar isolamento de falhas; nao constituem evidencia de integracao externa saudavel.

## Limpeza

Encerre os processos locais e remova somente o arquivo exato da fixture:

```powershell
Remove-Item -LiteralPath webapp\.playwright-mcp\judah_ui_verification.sqlite3
Remove-Item Env:JUDAH_UI_TEST_PASSWORD
```
