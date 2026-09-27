# Verificação

## Gates locais

- `ruff check .`: passou.
- `ruff format --check .`: passou (364 arquivos).
- `mypy .` com ambiente local de teste: passou (362 arquivos).
- `python run_tests_local.py`: 939 passaram, 46 pulados; cobertura 91,31%.
- `pytest apps/support/tests/test_reconcile_ticket_closures.py -q`: 18 passaram.
- `python run_checks.py`: passou em SQLite em memória; nenhuma migração pendente; checks Django sem problemas.
- `pre-commit run --files ...` nos arquivos desta request: passou.
- `pre-commit run --all-files`: falhou por formatação anterior em `install.cmd` e cinco SVGs do `webapp/public/`. As edições automáticas desses arquivos foram revertidas no worktree isolado.

## Dry-run anterior, antes do filtro de ciclo local

Projeto `JUDAH`, ambiente `production`, serviço `judah`; deploy `ad6508cb-7fa2-4157-9fb9-863ce75cf2e3` no SHA `7d30f8631b4904c3c34f6bef9a0938292d9490b0`.

```bash
railway run --project 18881041-8d59-4c99-a93b-c6f4f308e650 --environment production --service 981ec2f2-1e73-401b-bfab-7ffea3996b66 --no-local -- /home/felipe-teixeira/Workbench\ Febrate/judah/.venv/bin/python manage.py reconcile_ticket_closures --limit 100 --offset 0
```

`railway run` executou o código desta branch local com variáveis do serviço em produção. Não houve deploy nem execução de `--apply`.

```json
{"ambiguous":0,"applicable_current":0,"applicable_historical":0,"applied":0,"conflict":0,"duplicate":23,"identity_unavailable":0,"legacy_skipped":154,"no_cycle":77,"provider_unavailable":0,"reopen_not_materialized":0,"scanned":100}
```

O lote estava completo quanto à disponibilidade do provedor. Os 77 casos `no_cycle` motivaram o filtro de candidatos antes da paginação. Nenhum offset adicional foi executado.

## Dry-run com filtro de ciclo local antes da paginação

Alvo confirmado novamente via Railway CLI: projeto `JUDAH` (`18881041-8d59-4c99-a93b-c6f4f308e650`), ambiente `production` (`c3a77e65-5cd8-4d6d-9c15-cf2fe811102e`), serviço `judah` (`981ec2f2-1e73-401b-bfab-7ffea3996b66`), deploy `ad6508cb-7fa2-4157-9fb9-863ce75cf2e3` com status `SUCCESS` e SHA `7d30f8631b4904c3c34f6bef9a0938292d9490b0`.

```bash
railway run --project 18881041-8d59-4c99-a93b-c6f4f308e650 --environment production --service 981ec2f2-1e73-401b-bfab-7ffea3996b66 --no-local -- /home/felipe-teixeira/Workbench\ Febrate/judah/.venv/bin/python manage.py reconcile_ticket_closures --limit 100 --offset 0
```

`railway run` executou o código local da branch com variáveis de produção. Exit code `0`; nenhum deploy ou `--apply`.

```json
{"ambiguous":0,"applicable_current":0,"applicable_historical":0,"applied":0,"conflict":0,"duplicate":100,"identity_unavailable":1,"legacy_skipped":154,"no_cycle":125,"provider_unavailable":0,"reopen_not_materialized":0,"scanned":100}
```

O lote elegível está completo quanto à disponibilidade do provedor (`provider_unavailable=0`). Os 100 candidatos foram classificados como duplicatas. Os 154 eventos legados e os 126 eventos sem ciclo temporalmente resolvível observados no prefixo examinado não consumiram posições do lote. Nenhum próximo offset foi executado.
