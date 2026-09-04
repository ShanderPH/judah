# Contexto — estabilização da coorte na abertura

## Fonte canônica

- Research: `docs/research/TICKET-48154078600-stabilizing-cohort-research.md`
- Investigação anterior: `docs/investigations/TICKET-48154078600-reopened-conversation-sat-investigation.md`
- Ticket de origem: HubSpot `48154078600`
- Branch local: `hotfix/stabilize-cohort-48154078600`
- Base observada ao criar o artefato: `d55e9a4f39fbff043fc7176a4059b27ea7276932`

## Fatos confirmados que governam o plano

1. O ticket motivador foi atribuído pelo SAT; este hotfix não corrige reabertura nem owner histórico.
2. Fora do expediente, o SAT zera `availability_online_since` e `availability_sample_count`.
3. A elegibilidade individual exige, por padrão, duas amostras e 30 segundos de estabilidade.
4. O primeiro agente elegível pode disparar o drain enquanto outro agente ainda está em `stabilizing`.
5. `task_matchmaker_assign_single()` e `task_matchmaker_drain_queue()` convergem em
   `reserve_next_assignment()`; o gate precisa existir nesse caminho comum.
6. Reserva, capacidade e `AssignmentAttempt` são persistidos antes do efeito HubSpot; a barreira precisa
   decidir antes desses writes.
7. `resolve_now()` informa aberto/fechado, mas não expõe ainda um objeto tipado com o início do intervalo
   operacional ativo.
8. O cenário histórico exato de Esther imediatamente antes de 09:00:53 não foi recuperado. A primeira
   verificação deve provar a corrida sistêmica em fixture determinística, sem afirmar uma causalidade
   histórica que os dados não sustentam.

## Limites desta request

- Inclui: backlog anterior à abertura, coorte curta e fechada, deadline, recheck autoritativo, concorrência,
  métricas, configuração própria, testes e rollout.
- Exclui: replay do ticket, mudança de owner, continuidade com owner anterior, ciclos, lifecycle/watchdog,
  HubSpot app/workflow, n8n e qualquer recuperação de backlog.
- Pytest somente contra SQLite local para unidade ou PostgreSQL/Redis descartáveis. `conftest.py:isolate_db`
  apaga dados e torna qualquer database não local proibido sem pré-aprovação explícita.
- O worktree já continha drift não relacionado antes destes artefatos. Nenhum desses paths pode ser
  restaurado, removido, staged ou publicado por esta request.

## Referências técnicas atuais consultadas

- Django 5.2: `transaction.atomic()`, `transaction.on_commit()` e `select_for_update()`; concorrência deve
  usar transações reais e conexões separadas.
  <https://docs.djangoproject.com/en/5.2/topics/db/transactions/>
- Celery 5: mensagens podem ser redeliveradas; tarefas que toleram retry/redelivery devem ser idempotentes.
  <https://docs.celeryq.dev/en/stable/userguide/tasks.html>
- Celery 5: `eta`/`countdown` agenda execução futura; como o atraso desta request é curto e delimitado,
  ele é apropriado, mas não substitui o fallback periódico.
  <https://docs.celeryq.dev/en/stable/userguide/calling.html>
