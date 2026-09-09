# Verificação local do hotfix

Branch `hotfix/manual-assignment-capacity`, base `8a9f9ae00ca75a539617ac650bab4529e64cf4c1`. Python **3.14.4**, PostgreSQL **16**, Redis **8.6**, Django 5.2.15. Nenhum teste usou banco remoto ou provider real.

## Resultado final

**866 testes passaram, nenhum skip, cobertura 90,89%, em 229,53s**, na execução final `verified-suite.log`. Inclui PostgreSQL 16, Redis 8.6 e worker Celery real. Ruff limpo; mypy sem erros em 351 arquivos. A execução foi feita após a correção dos timestamps do teste de retry; nenhuma alteração posterior de código de produção.

Ruff: limpo. Mypy: configuração do projeto preservada, sem reduzir regras. `makemigrations support --check --dry-run`: nenhuma mudança pendente. `git diff --check`: limpo nos arquivos de código.

Os arquivos `.log` citados são evidências locais ignoradas pelo Git; este relatório versionado consolida seus resultados e os comandos de reprodução.

## Evidência por contrato

| Critérios | Evidência local |
|---|---|
| AC-01/02 | Task real de owner; `previousValue` incorreto, ator em `sourceId`, repetição, A→B→A→B e remoção de owner |
| AC-03 | Manual sem fila não cria atendimento; entrada comprovada usa o contrato de ciclo existente |
| AC-04 | Ocupação com fila na falha específica; precondition não sobrescreve owner conhecido mais recente |
| AC-05/06 | Carteira remota cheia veta seleção real; segundo candidato progride; reserva e owner confirmado contam uma unidade; ausência em Search exige readback |
| AC-07 | Timeout conserva reserva; retry exige `released`; repair lê owner sem repetir PATCH; confirmação repetida antes de finalizar ciclo não gera manual concorrente |
| AC-08 | Fechamento sem ciclo, owner removido, observação antiga e reabertura com ciclo anterior não conciliado; histórico anterior não é reescrito |
| AC-09 | PostgreSQL: última vaga, primeira ocupação concorrente, dupla compensação, scan vs reserva, webhook manual vs precondition automático e threads de admin vs webhook |
| AC-10 | Paginação, total incompleto/limite, duplicação de IDs, erro HTTP, Search com lag, desconhecido posteriormente cadastrado e arquivamento confirmado após 404 |
| AC-11 | Suíte completa inclui single/drain/retry, canário, ausência/calendário, barreira de abertura e falhas por item |
| AC-12 | Default off, shadow sem alterar contador/decisão legada, erro de shadow não bloqueia handler, bootstrap idempotente; migration reverse/forward local |
| AC-13 | Ruff/mypy, auditoria dos writers, handoff e runbook; tabelas/guards/RLS inspecionados após migração PostgreSQL |

## Concorrência e worker

- Barreiras/eventos determinísticos e conexões de threads distintas no PostgreSQL. Os testes asseguram que o provider é chamado fora de transações.
- Worker Celery real com Redis descartável: falha transitória, retry publicado e consumido, e uma ocupação persistida.
- Os dois testes existentes de SAT e handoff da barreira também foram executados com `JUDAH_TEST_REDIS_URL`; não ficaram apenas em modo eager.
- Query real sobre 2.000 ocupações locais retornou a contagem correta com uso de índice e dentro do limite local de 2s. Isso verifica o caminho SQL, não a latência ou orçamento real do HubSpot.

## Comando da suíte completa

```powershell
$env:JUDAH_TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/judah_test'
$env:JUDAH_TEST_REDIS_URL='redis://127.0.0.1:56379/0'
$env:JUDAH_CAPACITY_REDIS_URL='redis://127.0.0.1:56379/0'
Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue
.venv\Scripts\python.exe run_tests_local.py
```

O runner impõe credenciais fictícias de teste e valida o host/nome do banco. Para mypy, o mesmo ambiente foi usado sem executar pytest:

```powershell
$env:JUDAH_TEST_DATABASE_URL='sqlite:///./.test.sqlite3'
.venv\Scripts\python.exe -c "import os,runpy,pytest,subprocess,sys; os.environ['DJANGO_SETTINGS_MODULE']='core.settings.test'; pytest.main=lambda args: subprocess.call([sys.executable,'-m','mypy','apps','core','common']); runpy.run_path('run_tests_local.py',run_name='__main__')"
.venv\Scripts\ruff.exe check apps core common
```

## Falhas encontradas e corrigidas

1. Quatro reproduções vermelhas antes da implementação: transferência ignorada, manual sem fila, fila failed e reserva com carteira cheia.
2. Primeira suíte completa: mock de ticket sem metadata e cobertura 89,51%. O cliente passou a aceitar metadata ausente e a cobertura foi ampliada com cenários funcionais de falha/retry/bootstrap; o mínimo de 90% foi mantido.
3. Revisão final: reserva convertida antes de finalizar o ciclo poderia gerar uma projeção manual numa segunda leitura. Corrigido e coberto com ciclo real.

4. Elegibilidade e ranking: dois testes inicialmente falharam (`ranking-red.log`) e passaram após a correção (`ranking-green.log`). A consulta pública continua excluindo agentes cheios; a seleção atualiza as carteiras antes de aplicar a regra do último owner automático.

5. Rodada final intermediária: 865 testes passaram e um teste de retry falhou por misturar relógio fixo e timestamps reais no provider simulado (`final-validation.log`, cobertura 90,90%). Os snapshots do teste passaram a usar o relógio controlado; a proteção de produção contra snapshot antigo foi preservada. Reprodução corrigida: `retry-clock-green.log`.

## Limites da evidência

As fronteiras HTTP foram simuladas. O gate de custo e tráfego representativo do HubSpot, privilégios reais dos serviços e E2E de staging/produção permanecem externos, como previsto no plano. A interface e um ticket do incidente não foram informados; não se afirma causa única nem frequência em produção.

Não houve publicação, deploy, alteração de configuração remota ou reconstrução de dados históricos. Os artefatos de release/rollback estão preparados para revisão separada.
