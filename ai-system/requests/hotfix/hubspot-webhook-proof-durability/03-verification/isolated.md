# Verificação isolada sobre main 0ca25b8

- Suite Python: 1.040 passed, 51 skipped, 90,85% coverage (piso 90%).
- PostgreSQL 16 local: 104 passed; provider, proof, capacity contention, durable protocol e runtime guard.
- Redis 8.6 local db15, chave UUID exclusiva: 1 passed; TTL=-1, payload confirmado por releitura, cleanup da própria chave.
- Proof regressions: 36 passed, 1 skipped (Redis opt-in, executado em gate separado).
- Ruff: clean; format: 385 arquivos clean; mypy: 382 arquivos clean.
- Django checks: zero issues. Migration drift: No changes detected.
- Pre-commit aplicável: todos os hooks passaram nos sete arquivos Python do hotfix.
- Pre-commit all-files: whitespace pré-existente em install.cmd e cinco SVGs. Correções automáticas desfeitas somente nesses arquivos no worktree isolado; não fazem parte do hotfix.

A primeira tentativa PostgreSQL com `judah_ci_webhook_proof` não satisfazia a regex do trigger de testes; falhou com InsufficientPrivilege. Nome corrigido para judah_ci_20261002_1, testes repetidos sem alterar trigger nem assertions.

Os testes completos posteriores à integração incluem os mesmos cenários e os testes de #134. Nenhuma redução de cobertura/assertion.
