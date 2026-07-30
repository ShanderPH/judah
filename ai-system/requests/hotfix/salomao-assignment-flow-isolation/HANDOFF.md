# Handoff — Salomão assignment flow isolation

## Resumo do implementado/corrigido

- Separada a ordenação de projeção da execução de ocorrências: entrada calculada em NOVO tardia mantém o cursor monotônico e segue uma política tipada para revalidação idempotente.
- Criadas `SALOMAO_SUPERVISOR_ENABLED` e `SALOMAO_WAITING_RECONCILIATION_ENABLED`, independentes de `AUTO_ASSIGNMENT_ENABLED`, com sinais explícitos em readiness.
- Rotas de IA desligadas, inelegíveis, sem adapter ou sem capacidade de resposta convergem pela tarefa canônica de handoff; `MESSAGE_VERIFY` não termina mais em `safe_noop`.
- Adicionada migration reversível que revoga `anon`/`authenticated` e habilita RLS nas 11 tabelas operacionais, preservando runtime/owner/BYPASSRLS.
- Adicionado comando read-only `audit_assignment_recovery_candidates` para classificar candidatos sem replay, enqueue ou mudança de owner/stage.

## Arquivos modificados

- `apps/ai_agents/services/lifecycle.py`
- `apps/ai_agents/tasks.py`
- `apps/health/api.py`
- `apps/webhooks/handlers/hubspot_handler.py`
- `apps/webhooks/services.py`
- `apps/support/management/commands/audit_assignment_recovery_candidates.py`
- `apps/support/migrations/0026_protect_operational_tables_rls.py`
- testes correspondentes em `apps/ai_agents/tests/`, `apps/webhooks/tests/` e `apps/support/tests/`
- `core/settings/base.py`
- `docs/services/webhooks.md`
- `docs/setup/environment-variables.md`

## Como testar localmente

```powershell
uv run ruff check .
$env:DJANGO_ENV='test'
$env:DJANGO_SECRET_KEY='typecheck-only-not-secret'
$env:DATABASE_URL='sqlite:///./.mypy.sqlite3'
.venv\Scripts\mypy.exe .
$env:JUDAH_TEST_DATABASE_URL='postgresql://judah:judah_dev_password@localhost:5432/judah_test'
.venv\Scripts\python.exe run_tests_local.py
git diff --check
```

Dry-run de recuperação, somente após fornecer credenciais read-only do ambiente pretendido:

```powershell
.venv\Scripts\python.exe manage.py audit_assignment_recovery_candidates --since 2026-07-30T00:00:00-03:00
```

## Riscos conhecidos / áreas frágeis

- Os defaults locais preservam compatibilidade (`true`), mas produção deve definir explicitamente as duas novas flags nos três serviços.
- A reverse migration restaura o snapshot explícito de privilégios padrão do Supabase e reabre acesso cliente; rollback exige gate operacional próprio.
- O comando de auditoria consulta HubSpot e não deve ser confundido com autorização para recovery.
- O worktree contém exclusões e arquivos não rastreados preexistentes, fora deste hotfix; não incluir em commit/PR.

## Pontos de integração críticos para VERIFY

1. Corrida owner `T+591 ms` antes de NOVO `T`: uma ocorrência, sem rewind.
2. Handoff com Supervisor desligado e preservação de autoridade humana.
3. `anon`/`authenticated` sem SELECT/TRUNCATE após forward, restaurados no reverse, e protegidos novamente no reapply.
4. Worker/beat com reconciliação desligada: backlog reportado e nenhuma chamada ao provider.
5. Readiness com as três capacidades independentes.
