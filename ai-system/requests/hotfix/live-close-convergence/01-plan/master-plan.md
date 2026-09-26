# Convergência live de fechamento e occupancy

Plano autorizado pela solicitação P0 de 2026-09-26. Ciclo M. Base: `da124c841b30487d51a58b1ef289811795e0808a`.

## Critérios de aceite

- BE-01: uma observação de provider só confirma occupancy `closed` junto do fechamento do ciclo atual e da `ClosedConversation`, na mesma transação. Sem horário válido ou classificação aplicável, a observação falha e mantém o estado anterior.
- BE-02: a task de fechamento não confirma execução quando o runtime não tem autoridade. Falhas transitórias propagam para retry.
- BE-03: falha inesperada do lifecycle aborta o fechamento inteiro; duplicata continua idempotente e fechamento histórico preserva reabertura posterior.
- BE-04: outcome estruturado distingue consumo do webhook, classificação, aplicação e rejeição. Detector read-only conta ciclos recentes com occupancy fechada e sem projeção fechada.
- V-01: teste RED/GREEN da observação sem ocorrência e da falha de lifecycle.
- V-02: modos `off`, `shadow`, `enforce`; concorrência em PostgreSQL local; suíte, ruff, mypy, migration drift e diff.
- OPS-01: após merge e deploy do mesmo SHA em API/worker/beat, medir separadamente backlog anterior e ciclos/fechamentos novos. Reparador histórico permanece manual e dry-run.

Sem migração, tabela nova ou escrita em produção nesta request.
