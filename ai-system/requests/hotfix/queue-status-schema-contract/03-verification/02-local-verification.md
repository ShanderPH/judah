# Verificação local

## Aprovado

- Branch atualizada por fast-forward para a `main` pos-PR #93 no SHA
  `9dd4bd4`; nenhuma migration concorrente foi mantida.
- A migration consolidada `support.0024_repair_queue_status_constraint` foi
  validada em PostgreSQL 16 descartavel com forward, rollback protegido e
  reaplicacao.
- O teste complementar do Matchmaker confirmou quarentena da cabeca ambigua e
  atribuicao do proximo ticket no mesmo dreno.
- Suite repo-native pos-integracao: `945 passed, 11 skipped`, cobertura total
  `90.28%`.
- Ruff lint/format: clean nos arquivos alterados; mypy: `340 source files`, sem
  issues; grafo de migrations e Django system checks aprovados.
- Builds Docker API, worker e beat pos-PR #93 aprovados; as tres imagens
  retornaram `agno==2.8.5` e `mcp==1.28.1`.

- Branch atualizada por fast-forward para a `main` pós-PR #92 no SHA
  `79fe982cc43d7c70d61af69904052ec392e1caa8`.
- O savepoint e seu teste público do PR #92 foram mantidos; a alteração e o
  teste privado duplicados deste hotfix foram removidos.
- Testes focados SQLite: `48 passed, 1 skipped`.
- PostgreSQL 16 descartável: migration forward/backward/reapply e recuperação
  de collision do lifecycle, `2 passed`.
- Suíte repo-native: `937 passed, 11 skipped`, cobertura total `90.13%`.
- Ruff lint: clean.
- Ruff format: 340 arquivos formatados corretamente.
- Mypy: `336 source files`, sem issues.
- `run_checks.py`: migrations locais, `makemigrations --check --dry-run` e
  `manage.py check --fail-level WARNING` aprovados.
- `git diff --check`: clean.
- Resolução PyPI com `requirements/test.txt`: `agno==2.8.5` e `mcp==1.28.1`.
- Builds Docker API, worker e beat aprovados; inspeção das três imagens retornou
  `2.8.5 1.28.1`.

## Pendente

- Railway auth ausente impede revalidar deployment SHA e a flag de ciclos.
- O teste do PR #92 comprova recuperação da colisão dentro da transação externa,
  mas não sincroniza duas transações/processos simultâneos. Essa prova estrita
  continua sendo uma validação adicional, não necessária para duplicar o teste
  determinístico já existente.

## Guardrail observado

Os testes usaram SQLite privado ou PostgreSQL 16 descartável em
`127.0.0.1:55432`. O safety check confirmou o destino local. Nenhum teste foi
apontado ao Supabase ou a qualquer banco remoto.
