# Verificação

## Gates locais

- `ruff check .`: passou.
- `ruff format --check .`: passou (364 arquivos).
- `mypy .` com ambiente local de teste: passou (362 arquivos).
- `python run_tests_local.py`: 937 passaram, 46 pulados; cobertura 91,25%.
- Após adicionar o teste da identidade ausente, o arquivo focado foi executado novamente: 17 passaram.
- `python run_checks.py`: passou em SQLite em memória; nenhuma migração pendente; checks Django sem problemas.
- `pre-commit run --files ...` nos arquivos desta request: passou.
- `pre-commit run --all-files`: falhou por formatação anterior em `install.cmd` e cinco SVGs do `webapp/public/`. As edições automáticas desses arquivos foram revertidas no worktree isolado.

## Dry-run com dados de produção

Projeto `JUDAH`, ambiente `production`, serviço `judah`; deploy `ad6508cb-7fa2-4157-9fb9-863ce75cf2e3` no SHA `7d30f8631b4904c3c34f6bef9a0938292d9490b0`.

```bash
railway run --project 18881041-8d59-4c99-a93b-c6f4f308e650 --environment production --service 981ec2f2-1e73-401b-bfab-7ffea3996b66 --no-local -- /home/felipe-teixeira/Workbench\ Febrate/judah/.venv/bin/python manage.py reconcile_ticket_closures --limit 100 --offset 0
```

`railway run` executou o código desta branch local com variáveis do serviço em produção. Não houve deploy nem execução de `--apply`.

```json
{"ambiguous":0,"applicable_current":0,"applicable_historical":0,"applied":0,"conflict":0,"duplicate":23,"identity_unavailable":0,"legacy_skipped":154,"no_cycle":77,"provider_unavailable":0,"reopen_not_materialized":0,"scanned":100}
```

O lote está completo quanto à disponibilidade do provedor. Os 77 casos `no_cycle` não são reparáveis sem evidência de ciclo; nenhum ciclo será reconstruído nesta request. Nenhum offset adicional foi executado.
