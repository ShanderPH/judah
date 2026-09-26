# Baseline R0 — produção, somente leitura

Coletado em 2026-09-26 09:29 UTC pelo SQL versionado em `baseline.sql`, via Railway no serviço `judah`/ambiente `production`. A execução usou `BEGIN READ ONLY`, `statement_timeout = 15s` e terminou em `ROLLBACK`. Não houve mutação.

| Indicador | Valor |
|---|---:|
| AssignedConversation existentes | 888 |
| AssignedConversation com occupancy no estado closed | 853 |
| Cycles no estado assigned | 891 |
| Ocorrências calculadas de FECHADO no ledger | 4.465 |
| ClosedConversation existentes | 1.438 |
| Transições lifecycle para CLOSED | 2.507 |
| Ocorrências com timestamp válido e ciclo alvo não encontrado | 2.006 |
| Ocorrências cujo ciclo alvo está assigned e não tem ClosedConversation | 1.114 |
| Ocorrências cujo ciclo alvo tem AssignedConversation e não tem ClosedConversation | 1.108 |
| Ciclos **distintos** no grupo anterior | **861** |
| Ocorrências cujo ciclo alvo está closed e não tem ClosedConversation | 8 |
| Ocorrências sem ClosedConversation atribuídas a ciclos abertos nas últimas 24h | 16 |
| Ciclos **distintos** no grupo anterior | **15** |

As linhas de ocorrências contam entregas do ledger; um ciclo pode aparecer várias vezes. As contagens não provam que todos os 861 ciclos tenham a mesma causa dos 63 casos investigados, nem que os 2.006 sem ciclo sejam erros: eventos anteriores à materialização de ciclos também entram nesse grupo. O critério de rollout deve usar ciclos distintos abertos após o SHA novo, com verificação de amostra pelo provider e sem confundir duplicatas do webhook com novos tickets.

Nenhuma leitura individual, dado pessoal ou payload bruto foi exportado.
