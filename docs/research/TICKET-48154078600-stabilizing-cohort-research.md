# Research — coorte de estabilização antes da atribuição na abertura

**Data:** 2026-09-04

**Origem:** investigação do ticket HubSpot `48154078600`

**Fase:** research; nenhuma implementação, configuração, migration, deploy ou mutação externa foi executada

**Artefato de entrada:** `docs/investigations/TICKET-48154078600-reopened-conversation-sat-investigation.md`

## 1. Decisão recomendada

A melhor abordagem é introduzir uma **barreira curta e delimitada para formar a coorte** antes de distribuir a fila acumulada fora do expediente:

1. preservar a proteção atual de estabilização do agente (`2` amostras e `30s` por padrão);
2. quando a primeira distribuição da fila da abertura encontrar, simultaneamente, agentes já elegíveis e agentes da mesma coorte ainda em `stabilizing`, não reservar nem atribuir conversas imediatamente;
3. agendar uma reconciliação autoritativa para o primeiro instante em que a coorte puder concluir a estabilização;
4. liberar a distribuição quando a coorte terminar ou quando atingir um prazo máximo curto e explícito;
5. no prazo máximo, seguir somente com os agentes comprovadamente elegíveis; agentes ainda incertos continuam excluídos, preservando o fail-closed.

Essa solução combina as duas ideias propostas — **aguardar a finalização** e **acelerar a reavaliação** — sem reduzir globalmente a segurança do SAT e sem permitir espera indefinida.

Não é recomendado:

- reduzir globalmente `AVAILABILITY_REQUIRED_SAMPLES` para `1` ou `AVAILABILITY_STABLE_SECONDS` para `0`;
- bloquear toda atribuição sempre que qualquer agente estiver em `stabilizing` durante o dia;
- fazer `sleep` dentro de worker Celery;
- criar afinidade automática com o owner anterior como parte deste ajuste sem uma decisão de produto separada.

## 2. Escopo e pergunta de research

### Pergunta principal

Como evitar que a fila preservada durante a madrugada seja drenada pelo primeiro subconjunto de agentes que conclui a estabilização, sem aumentar materialmente o tempo normal de atribuição nem enfraquecer as proteções de ausência e disponibilidade?

### Dentro do escopo

- estado `stabilizing` do SAT;
- abertura do horário operacional;
- fila criada antes da abertura e preservada fora do expediente;
- coordenação entre heartbeat, reconciliação autoritativa e Matchmaker;
- fairness da seleção de agentes;
- limites de tempo, concorrência, fallback e observabilidade;
- implicações para testes e rollout de uma futura implementação.

### Fora do escopo

- replay ou reatribuição do ticket `48154078600`;
- alteração do owner atual no HubSpot;
- regra de continuidade com o owner do ciclo anterior;
- lifecycle/watchdog e limpeza de `current_error`;
- ativação de `CONVERSATION_CYCLES_ENFORCED`;
- RLS das tabelas de calendário;
- mudança de flags, banco, Railway, HubSpot ou workflows.

## 3. Evidências confirmadas

### 3.1 O ticket que motivou o research foi atribuído corretamente

A investigação de entrada prova que:

- a reabertura gerou um novo ciclo;
- a fila foi preservada entre 05:04 e a abertura do expediente;
- o SAT atribuiu o ticket a Gabriel às 09:00:53 BRT;
- houve transferência humana para Esther 34 segundos depois;
- a aparente ausência de atuação do SAT era efeito do owner atual e da remoção normal da linha consumida da fila.

Portanto, este research não corrige falha de reabertura. Ele trata uma possível **corrida de formação da coorte elegível na abertura**, capaz de produzir uma distribuição operacionalmente indesejada.

### 3.2 A estabilização atual é deliberadamente fail-closed

Em `apps/support/sat_service.py`:

- um sinal remoto `available` inicia ou incrementa `availability_sample_count`;
- o agente só fica elegível quando satisfaz simultaneamente a quantidade mínima de amostras e o tempo estável;
- enquanto isso, recebe `eligibility_reason = stabilizing`;
- com enforcement ativo, `stabilizing` mantém `status_enum = away`.

Os defaults em `core/settings/base.py` são:

```text
AVAILABILITY_STABLE_SECONDS=30
AVAILABILITY_REQUIRED_SAMPLES=2
SAT_HEARTBEAT_INTERVAL_SECONDS=30  # piso de 20s
AVAILABILITY_FRESHNESS_SECONDS=60
```

O teste `test_available_requires_stability_then_returns_online` confirma o contrato de duas etapas: primeira observação em `stabilizing`, segunda observação após a janela em `eligible`.

### 3.3 O período fora do expediente reinicia a estabilização

`_materialize_off_hours_availability()`:

- força o agente para `away` / `outside_working_hours`;
- limpa `availability_online_since`;
- zera `availability_sample_count`.

Logo, na abertura todos os agentes precisam formar uma nova evidência de disponibilidade. Isso é seguro, mas cria uma largada sincronizada sujeita a pequenas diferenças de polling, resposta do provedor, login e execução do worker.

### 3.4 O primeiro agente que se torna elegível pode disparar o drain

Ao detectar transição para elegível, `sat_heartbeat()` incrementa `agents_came_online` e registra, via `transaction.on_commit`, `task_matchmaker_drain_queue.delay()`.

O Matchmaker:

- retorna sem drenar quando não existe agente elegível;
- quando existe ao menos um elegível, percorre a fila em loop limitado;
- não verifica se outros agentes estão em `stabilizing`;
- classifica apenas o conjunto já elegível por `last_assignment_at`, carga e desempate determinístico.

Assim, a fairness funciona corretamente **dentro do conjunto visível**, mas não protege contra um conjunto ainda incompleto.

### 3.5 O caminho de ticket individual também precisa respeitar qualquer barreira

`task_matchmaker_assign_single()` executa uma reconciliação autoritativa com `force_refresh=True` e chama `matchmaker_assign_next(ticket_id)` diretamente. Portanto, uma proteção colocada somente em `task_matchmaker_drain_queue()` seria incompleta: um webhook concorrente poderia contorná-la.

Uma implementação futura deve aplicar a decisão no caminho comum anterior à reserva do agente/linha, idealmente no protocolo de reserva durável, e não apenas no wrapper do drain periódico.

## 4. O problema sistêmico

O SAT hoje responde à pergunta:

> “Este agente individual já tem evidência suficiente para receber uma conversa?”

Na abertura, também é necessário responder:

> “O conjunto de agentes que já se apresentou para esta abertura está suficientemente formado para começar a distribuir a fila acumulada?”

Sem essa segunda decisão, a sequência possível é:

```text
09:00:00  Agentes A e B recebem a primeira amostra; ambos stabilizing
09:00:30  A conclui a janela; B ainda não conclui por jitter/entrada tardia
09:00:30  A fica eligible e dispara o drain
09:00:31  A recebe parte ou toda a fila acumulada
09:00:40  B conclui a estabilização, tarde demais para participar da distribuição
```

Isso não é erro de elegibilidade de A. É uma corrida entre **formação da coorte** e **consumo irreversível da fila**.

### Efeitos possíveis

- concentração da fila no primeiro agente elegível;
- perda de fairness na abertura;
- transferência humana logo após a atribuição;
- percepção de que o SAT escolheu o agente errado;
- aumento de ruído operacional e métricas de transferência;
- uso rápido de capacidade antes que o time completo fique visível.

## 5. Limitações da evidência deste caso

### Confirmado

- o contrato e os tempos padrão de estabilização no código;
- o reset da janela fora do expediente;
- o drain acionado na transição do primeiro agente elegível;
- a ausência de uma barreira de coorte no Matchmaker;
- a atribuição a Gabriel e a transferência posterior para Esther.

### Provável

- a atribuição às 09:00:53 é temporalmente compatível com a formação da primeira coorte após a abertura;
- diferenças pequenas entre agentes na conclusão de `stabilizing` podem alterar o conjunto usado pelo ranking.

### Não verificado

- o snapshot histórico completo de `eligibility_reason`, `availability_online_since` e `availability_sample_count` de Esther e dos demais agentes exatamente antes de 09:00:53;
- se Esther estava em `stabilizing`, `away`, ausente ou havia acabado de se disponibilizar naquele instante;
- se a transferência ocorreu por continuidade deliberada, acordo operacional ou preferência individual.

A solução recomendada é sustentada pelo comportamento sistêmico do código, mas não deve ser descrita como correção comprovada da transferência específica sem recuperar esse snapshot histórico.

## 6. Requisitos para uma solução segura

Uma abordagem aceitável deve:

1. preservar a fila e não aplicar owner antes da decisão;
2. manter agentes incertos inelegíveis;
3. não depender de espera bloqueante no worker;
4. nunca aguardar indefinidamente por agente oscilante ou atrasado;
5. limitar o comportamento especial à fila/coorte relevante;
6. manter FIFO entre conversas prontas;
7. manter o ranking atual depois de formar a coorte;
8. funcionar nos caminhos de drain e ticket individual;
9. ser segura sob tarefas concorrentes, retries e reinício de worker;
10. possuir fallback pelo Beat caso o callback acelerado não execute;
11. não transformar uma espera intencional em `failure_code=no_eligible_candidate`;
12. expor métricas suficientes para comparar atraso e redução de transferências;
13. permitir desligamento rápido por configuração própria;
14. não exigir alteração de HubSpot nem enfraquecer o readback pré-efeito.

## 7. Alternativas avaliadas

| Alternativa | Latência | Segurança de disponibilidade | Fairness na abertura | Complexidade | Veredito |
|---|---:|---:|---:|---:|---|
| A. Manter como está | melhor para o primeiro elegível | alta | baixa com coorte incompleta | baixa | não resolve |
| B. Reduzir globalmente amostras/tempo estável | muito baixa | baixa | média | baixa | rejeitar |
| C. Esperar enquanto existir qualquer `stabilizing` | imprevisível | alta | alta em teoria | média | rejeitar sem limite/escopo |
| D. Barreira delimitada somente para backlog de abertura | curta e limitada | alta | alta | média | boa |
| E. Barreira delimitada + rechecagem autoritativa acelerada | curta, próxima do baseline | alta | alta | média/alta | **recomendada** |
| F. Afinidade com owner anterior em reaberturas | variável | depende da elegibilidade | não trata coorte | alta/produto | separar |

### A. Manter o comportamento atual

Preserva a menor latência possível para o primeiro agente elegível, mas aceita a corrida e não atende à recomendação operacional.

### B. Diminuir globalmente a estabilização

Configurar uma amostra ou zero segundos faria todos os agentes disponíveis entrarem no pool na primeira leitura. Porém, remove a proteção contra sinais transitórios, login incompleto e oscilação do provedor. Como a proteção foi introduzida junto do enforcement fail-closed, esse trade-off é desproporcional.

### C. Bloquear diante de qualquer `stabilizing`

É intuitiva, mas perigosa sem delimitação. Durante o dia, um único agente que alterna presença poderia atrasar todas as conversas. Um agente que entra tarde não deve reabrir continuamente a barreira. Também faltaria uma regra clara para falha de API, ausência, saída do agente e deadline.

### D. Barreira somente na abertura

Resolve o problema de conjunto incompleto e mantém o comportamento normal durante o restante do expediente. Ainda pode depender do próximo tick de 30s/60s para retomar, o que adiciona jitter evitável.

### E. Barreira + rechecagem acelerada

Mantém a janela de evidência existente, mas agenda a próxima leitura exatamente quando ela pode concluir, em vez de aguardar passivamente o próximo drain. A fila não é consumida durante a barreira. O Beat continua como safety net.

### F. Continuidade com owner anterior

Pode ser uma regra válida para reaberturas, mas responde a outra pergunta. No ticket analisado, o owner foi removido no fechamento e `prior_observed_owner_id` da tentativa era nulo. Identificar o “owner anterior correto” pode exigir histórico do ciclo/thread e uma definição de produto para tickets proativos, transfers, ausências e capacidade. Não deve ser embutido implicitamente neste ajuste.

## 8. Desenho recomendado

### 8.1 Conceitos

**Backlog de abertura:** conversa elegível cuja `entered_queue_at` é anterior ao início da janela operacional corrente.

**Coorte de abertura:** agentes ativos, com auto-assign habilitado, identidade válida e capacidade, observados como remotamente `available` durante a primeira reconciliação autoritativa da janela e que estejam `eligible` ou `stabilizing`.

**Barreira ativa:** existe backlog de abertura, existe ao menos um agente elegível e existe ao menos um agente da coorte ainda em `stabilizing`, antes do deadline.

**Deadline:** limite calculado a partir da primeira observação da coorte. Depois dele, o sistema não espera novos agentes; distribui apenas para quem estiver comprovadamente elegível.

### 8.2 Fluxo proposto

```text
Heartbeat/reconciliação autoritativa
        |
        v
Persiste eligible/stabilizing + timestamps/amostras
        |
        v
Tentativa comum de reserva de conversa
        |
        +-- não é backlog de abertura -----------------> fluxo atual
        |
        +-- backlog, sem stabilizing ------------------> fluxo atual
        |
        +-- backlog, eligible + stabilizing, no prazo -> DEFERIR SEM CLAIM/EFFECT
                                                        |
                                                        +-> agendar recheck no ETA
                                                        +-> Beat permanece fallback
        |
        +-- deadline atingido --------------------------> usar somente eligible
```

### 8.3 Como calcular o momento de rechecagem

Não reduzir `AVAILABILITY_STABLE_SECONDS`. Para cada agente em estabilização, o primeiro instante temporal possível é:

```text
availability_online_since + AVAILABILITY_STABLE_SECONDS
```

Como também são necessárias amostras, a rechecagem deve ocorrer após esse instante com pequena margem de jitter. Com os defaults atuais, o alvo é aproximadamente `31–35s` após a primeira observação, não um polling agressivo.

O prazo máximo sugerido para planejamento é derivado, não arbitrário:

```text
cohort_started_at
  + AVAILABILITY_STABLE_SECONDS
  + SAT_HEARTBEAT_INTERVAL_SECONDS
```

Com os defaults, isso limita a espera a cerca de `60s` após a primeira observação. A expectativa normal continua próxima de `30–35s`; o segundo intervalo existe apenas como tolerância para lease contention, jitter ou uma leitura inconclusiva.

Os valores finais precisam ser validados com a distribuição real de duração do heartbeat e latência da Users API antes do plano.

### 8.4 A coorte não deve crescer indefinidamente

Somente agentes observados no início da barreira pertencem à coorte. Um agente que se disponibiliza depois do `cohort_started_at` não estende o deadline. Ele pode participar caso conclua a estabilização antes da liberação, mas não mantém a fila bloqueada.

Estados que encerram a espera daquele agente:

- `eligible`: participa do ranking;
- `remote_away`, ausência ativa, fora do horário, inativo, auto-assign desabilitado, capacidade cheia ou dado inválido: não participa;
- ainda `stabilizing` no deadline: continua excluído, mas não bloqueia a fila.

### 8.5 Não usar espera bloqueante

O worker não deve dormir até o deadline. A tentativa retorna um resultado explícito, sem claim e sem efeito externo, e agenda uma tarefa idempotente com `countdown` para o ETA. Se essa mensagem se perder, os heartbeats de 30s e o drain de 60s reavaliam a condição.

### 8.6 Ponto de aplicação

A decisão deve ficar no caminho comum que antecede `reserve_next_assignment()` ou dentro de sua fase de decisão, cobrindo:

- `task_matchmaker_drain_queue`;
- `task_matchmaker_assign_single`;
- retries e chamadas compatíveis de `matchmaker_assign_next`.

O gate precisa ser revalidado imediatamente antes da reserva usando o relógio do banco ou um snapshot transacional coerente. O objetivo é impedir que duas tarefas concorrentes observem a barreira de forma diferente e uma delas aplique owner antes do prazo.

### 8.7 Resultado de domínio próprio

Não reutilizar `no_eligible_candidate`: há candidato elegível, mas a política decidiu aguardar a coorte. Um resultado como `deferred_stabilizing_cohort` deve ser distinto e não deve:

- incrementar tentativa de atribuição;
- gravar falha;
- adquirir claim;
- reservar capacidade;
- criar `AssignmentAttempt`;
- tocar o HubSpot.

Se for necessário evitar hot-loop por múltiplos triggers, pode-se usar `next_assignment_attempt_at` com o ETA da barreira, preservando uma razão neutra e auditável. A necessidade de persistência adicional deve ser decidida no plano após testar concorrência; o desenho básico pode ser derivado dos campos já existentes.

### 8.8 A seleção depois da barreira permanece igual

Ao liberar:

- `get_eligible_agents()` continua aplicando status, enforcement, freshness e capacidade;
- a verificação remota pré-efeito continua obrigatória;
- `get_ranked_eligible_agents()` mantém a regra de não repetir owner e a ordem por `last_assignment_at`, carga e ID;
- reserva, readback e finalização durável permanecem inalterados.

A mudança é temporal — **quando formar o pool** —, não uma nova regra de ranking.

## 9. Por que esta abordagem atende à preocupação de latência

O sistema atual já exige aproximadamente uma janela estável antes de considerar cada agente elegível. A recomendação não adiciona uma janela completa depois disso; ela:

- usa o ETA da janela já em curso;
- provoca a rechecagem no primeiro instante útil;
- limita o caso especial ao backlog anterior à abertura;
- libera no deadline mesmo se algum agente continuar incerto;
- mantém tickets comuns do restante do dia no fluxo atual.

Assim, o custo esperado é trocar uma distribuição possivelmente prematura por uma espera próxima do tempo que o próprio SAT já considera “normal” para confirmar disponibilidade.

## 10. Riscos e mitigadores

### Agente oscilante bloqueia a fila

**Mitigação:** coorte fechada e deadline obrigatório; após o prazo, somente elegíveis seguem.

### A API do HubSpot falha na rechecagem

**Mitigação:** fail-closed para o agente, mas não renovar o deadline; Beat tenta novamente e, no limite, a fila segue com os snapshots elegíveis/frescos que passarem pela verificação pré-efeito.

### Callback duplicado ou concorrente

**Mitigação:** tarefa idempotente, lease/fencing do SAT, gate comum antes da reserva e protocolo atual de claim/`AssignmentAttempt`.

### Callback se perde após commit

**Mitigação:** heartbeat e drain periódicos permanecem como fallback; não depender exclusivamente de ETA Celery.

### Barreira afeta tickets novos durante o dia

**Mitigação:** aplicar somente a linhas anteriores ao início da janela operacional corrente. Não usar “qualquer agente stabilizing” como gate global.

### Mudança gera head-of-line blocking

**Mitigação:** separar backlog de abertura de tickets que entraram depois. O plano deve decidir explicitamente se o gate pausa somente o batch de abertura ou toda a fila por até o deadline; a preferência é não atrasar tickets pós-abertura por causa do batch antigo.

### Clock drift

**Mitigação:** calcular gate/deadline com relógio do banco no ponto de reserva e manter timestamps timezone-aware.

### Maior uso da Users API

**Mitigação:** uma única rechecagem acelerada por coorte, deduplicada; não uma chamada por ticket nem polling curto contínuo.

### Diagnóstico insuficiente

**Mitigação:** registrar motivos e tempos agregados, sem PII, e preservar `AgentAvailabilityDecision` como trilha da elegibilidade individual.

## 11. Observabilidade mínima

Uma implementação futura deve expor:

- contador `assignment_cohort_barrier_started_total`;
- contador `assignment_cohort_barrier_released_total`, com motivo limitado (`all_settled`, `deadline`, `no_backlog`, `disabled`);
- histograma `assignment_cohort_barrier_duration_seconds`;
- gauge/campo agregado de agentes `eligible` e `stabilizing` no início/fim;
- quantidade de conversas do backlog protegidas pela barreira;
- atraso abertura → primeira atribuição;
- concentração das primeiras atribuições por agente;
- taxa de transferências humanas até 2 e 5 minutos após auto-assignment;
- número de callbacks acelerados e fallbacks pelo Beat.

Logs não devem incluir nome, e-mail, conteúdo de ticket ou payload remoto. IDs internos redigidos/contagens são suficientes.

## 12. Estratégia de teste para o futuro plano

### Unidade

1. backlog + `eligible` + `stabilizing` antes do deadline → defer sem claim/effect;
2. todos estabilizados → libera imediatamente;
3. deadline atingido + um ainda stabilizing → libera somente elegíveis;
4. agente fica `away` durante a espera → encerra sua participação sem estender prazo;
5. agente novo aparece depois do início → não estende deadline;
6. ticket pós-abertura → não entra na barreira;
7. nenhuma fila → não agenda recheck;
8. somente agentes stabilizing e nenhum elegível → comportamento de fila preservada;
9. motivo de defer não é persistido como falha.

### Integração Django/PostgreSQL/Redis/Celery

1. dois drains concorrentes antes do deadline não criam `AssignmentAttempt`;
2. webhook individual concorrente não contorna o gate;
3. callback duplicado produz no máximo um efeito por ciclo;
4. worker reinicia durante a espera e o Beat conclui o fluxo;
5. lease SAT contendido cai no fallback sem prolongar indefinidamente;
6. relógio do banco governa o deadline;
7. FIFO e `next_assignment_attempt_at` não geram head-of-line blocking;
8. uma coorte com vários agentes distribui usando o ranking existente;
9. falha da Users API mantém incertos fora e preserva a fila;
10. PostgreSQL enum e writers/fencing atuais não sofrem regressão.

### Cenários temporais essenciais

- agente A estabiliza em 30s, B em 31s;
- A estabiliza e B oscila até o deadline;
- A já elegível, B começa a estabilizar depois do início da coorte;
- abertura com backlog grande e capacidade parcial;
- ticket novo chega durante a barreira;
- mudança de intervalo SAT entre 20s e valor superior;
- mudança de calendário/feriado na fronteira de abertura.

## 13. Rollout sugerido para o plano posterior

1. adicionar decisão e telemetria em shadow mode, sem deferir;
2. medir por alguns dias quantas vezes a condição ocorreria e por quanto tempo;
3. validar baseline de abertura, latência da Users API e transferências rápidas;
4. habilitar enforcement somente para backlog de abertura;
5. usar stop conditions: aumento excessivo de espera, fila não drenada após deadline, crescimento de erros do provedor ou divergência de claims;
6. preservar kill switch próprio, independente de `AUTO_ASSIGNMENT_ENABLED`;
7. não misturar o rollout com regra de continuidade de owner ou enforcement global de ciclos.

## 14. Questões que o plano deve fechar

1. Qual é a definição autoritativa do início da janela operacional quando há múltiplas regras/intervalos no calendário?
2. A barreira deve proteger apenas linhas anteriores à abertura ou todo ticket recebido durante os primeiros segundos da janela?
3. Qual é o orçamento máximo aceitável de abertura → primeira atribuição: 45s, 60s ou outro valor medido?
4. A rechecagem acelerada deve chamar `sat_heartbeat(force_refresh=True)` para a equipe inteira ou um reconciliador de coorte?
5. `next_assignment_attempt_at` é suficiente para persistir o defer ou é necessário um estado explícito de coorte?
6. Como deduplicar o callback de ETA entre heartbeat, webhook e Beat sem criar um segundo writer de disponibilidade?
7. Qual métrica de transferência rápida representa melhora operacional?
8. A continuidade com owner anterior é desejada? Se sim, deve virar uma request própria com regra de produto explícita.

## 15. Critérios de aceite para o futuro plano

O plano de implementação só deve ser aprovado se demonstrar que:

- nenhuma atribuição externa ocorre enquanto a barreira aplicável está ativa;
- a espera é delimitada e não renovável por chegadas tardias;
- o deadline não enfraquece a elegibilidade individual;
- webhooks e drains periódicos passam pelo mesmo gate;
- não existe `sleep` de worker;
- callbacks duplicados e concorrência não duplicam owner effects;
- backlog de abertura e tickets pós-abertura têm comportamento definido;
- a proteção é desligável sem desativar todo o SAT;
- métricas permitem provar latência e efeito em transferências;
- testes reais usam PostgreSQL e Redis/Celery onde mocks/SQLite não provam concorrência e persistência.

## 16. Conclusão

A recomendação de aguardar agentes em `stabilizing` é correta para o **batch acumulado na abertura**, mas precisa de três guardrails: **coorte fechada, prazo máximo e rechecagem autoritativa agendada**.

O ajuste recomendado não acelera a elegibilidade reduzindo sua segurança. Ele acelera a **coordenação**: espera apenas a janela já exigida, reavalia no primeiro instante útil e então entrega ao ranking atual um conjunto mais completo de agentes. No deadline, segue com quem estiver comprovadamente elegível, impedindo que um agente instável ou atrasado paralise a operação.

Uma regra de continuidade para reaberturas pode reduzir transferências em casos como este, mas é uma decisão de produto separada e não deve ser usada como atalho para corrigir a corrida de coorte.
