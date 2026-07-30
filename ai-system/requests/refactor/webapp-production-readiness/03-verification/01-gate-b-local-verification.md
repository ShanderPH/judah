# Verificação local — Gate B

Data: 2026-07-29. Python 3.14.4, Django 5.2.15 e SQLite privado do runner nativo.

| Gate | Resultado |
|---|---|
| Ruff check/format | passou |
| Mypy | passou, 7 arquivos |
| Testes | 956 passed, 11 skipped |
| Cobertura | 90,42%, mínimo 90% atingido |
| Django system check | 0 issues |
| Migration drift | no changes detected |
| `git diff --check` | passou |

Foram provados 401 anônimo, 403 viewer/agent, sucesso manager/admin, 422 sem write, replay sem repetir efeito, 409 para chave divergente, rollback quando o ledger falha, audit de falha e ausência de PII no JSON negado.

O `ResourceWarning` do SQLite no encerramento do runner é preexistente e não causou falha. Browser verification não se aplica ao Gate B backend-only.
