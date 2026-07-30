# V-02 — verificação local do Gate C

Data: 2026-07-29. Ambiente local, SQLite privado; nenhuma rede de negócio ou base remota.

| Comando/prova | Resultado |
|---|---|
| `uv run ruff check apps/auth_user` | passou |
| `uv run mypy apps/auth_user` | passou, 24 arquivos |
| `uv run python run_tests_local.py` | 961 passed, 11 skipped |
| cobertura | 90,43% |
| `npm.cmd run test` | 10 passed, 4 arquivos |
| `npm.cmd run lint` | passou |
| `npm.cmd run typecheck` | passou |
| `npm.cmd run build` | passou |
| `git diff --check` | passou |

## Provas de segurança

- Refresh body/rotation/replay/query rejection cobertos por integração Django.
- Método/path, origem, content type, limite de body e capability cobertos por Vitest.
- `/dashboard`, `/agents` e `/sandbox-chat` sem cookie retornaram redirect 307 para login.
- Path BFF não listado retornou 404; mutação cross-site retornou 403.
- Busca de `refresh?refresh=` encontrou somente o teste negativo backend.
- Authorization permanece apenas em módulos server-side que chamam Judah/HubSpot.

A skill de browser falhou ao inicializar (`kernel assets` indisponíveis), logo não foi possível registrar screenshot/recording autenticado. Essa prova continua obrigatória antes do release. `npm audit --omit=dev` apontou duas highs em Next/sharp, explicitamente roteadas ao Gate D.
