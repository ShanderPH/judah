# Verificação

## Regressões reproduzidas

- A tentativa `repair_required` com ciclo encerrado e `compensated_at` preenchido permanecia não terminal.
- Três conversas históricas com lote máximo de uma identidade nunca convergiam porque cada execução reconstruía o mesmo conjunto completo.

Os dois testes falharam antes da implementação e passaram após o hotfix.

## Gates executados

- Testes focados e comandos: `61 passed, 4 skipped`.
- Suíte de suporte: `423 passed, 38 skipped`.
- Suíte completa SQLite: `866 passed, 43 skipped`.
- PostgreSQL 16 local: três regressões novas e oito testes de concorrência, `11 passed`.
- Ruff format: `358 files already formatted`.
- Ruff lint: sem achados.
- Mypy: `355 source files`, sem achados.
- Migration drift: `No changes detected`.
- `git diff --check`: sem achados.

## Resultado

O reparador persiste a transição terminal sem repetir o débito de capacidade. A reconciliação prioriza
portfólio remoto e reservas, processa o histórico restante em lotes retomáveis e deixa de reler
evidência terminal ausente de uma busca completa. O bootstrap explícito usa o limite configurado de
identidades e os timeouts individuais do HubSpot, sem o prazo de 20 segundos do caminho online.

Nenhuma migration ou configuração de produção foi alterada. `SUPPORT_CAPACITY_MODE` deve permanecer
em `shadow` até o deploy e a repetição dos gates de produção.
