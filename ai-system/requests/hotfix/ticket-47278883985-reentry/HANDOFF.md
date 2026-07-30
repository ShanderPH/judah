# HANDOFF — ticket 47278883985

## Resultado

O hotfix está implementado e validado localmente. A reentrada deixa de depender
de uma associação ausente, participação humana histórica não bloqueia um turno
posterior do visitante, fechamento exige resposta realmente conclusiva e o
handoff fora do expediente usa sua rota própria. A detecção de mensagens agora
usa eventos por ocorrência e possui reconciliação por `message_id`. Notificações
sem direção são confirmadas pela thread, eventos fora de ordem não podem
retroceder o lifecycle e efeitos no ticket exigem revalidação da thread e do
turno do cliente.

PR: `https://github.com/ShanderPH/judah/pull/97` (base `main`).
O commit de código `2597bf454d4f4e143294f942a91dfc256cab45ed`
passou em todos os checks locais e remotos.

## Arquivos principais

- `apps/ai_agents/services/hubspot.py`
- `apps/ai_agents/services/decision_policy.py`
- `apps/ai_agents/agents/supervisor.py`
- `apps/ai_agents/services/execution.py`
- `apps/ai_agents/services/lifecycle.py`
- `apps/ai_agents/services/watchdog.py`
- `apps/ai_agents/tasks.py`
- `apps/webhooks/api.py`
- `apps/webhooks/services.py`
- `apps/webhooks/handlers/hubspot_handler.py`
- `hubspot-app/`
- `common/logging.py`
- `core/settings/base.py`
- `apps/support/management/commands/provision_support_agent.py`
- `.env.example`
- `docs/setup/environment-variables.md`
- `docs/services/ai_agents.md`

## Segurança operacional

- Não houve push, deploy, replay, movimentação de ticket ou upload de projeto
  HubSpot nesta extensão do hotfix.
- O `--execute` autorizado provisionou em produção o agente
  `suporte_inchurch` com owner `81908844`, sem duplicar registros e preservando
  o papel do usuário.
- Antes de produção, rotacionar qualquer credencial Redis já exposta.
- Confirmar que o workflow HubSpot associado ao estágio fora do expediente
  encaminha a conversa para o N1 no próximo período de atendimento.
- Publicar somente o projeto `Judah HubSpot Integration`, que concentra todos
  os webhooks de produção e é a fonte ativa de `conversation.newMessage`.
- Manter apenas `HUBSPOT_APP_SECRET` para autenticação dos webhooks de produção;
  nenhuma variável adicional de secret do Salomão-V1 é necessária.
- Fazer deploy e upload somente depois de publicar/revisar o diff exato; em
  seguida executar o smoke autenticado antes de considerar o gate concluído.

## Provisionamento concluído

O comando autorizado foi executado no Railway de produção. A verificação
confirmou um único usuário e um único `Agent`, owner/e-mail corretos,
`auto_assign=true`, capacidade `5`, estado `offline` e papel `viewer`
preservado.

## Smoke recomendado após deploy em staging

1. Criar uma conversa nova e obter uma resposta da IA.
2. Fazer uma pergunta que exija esclarecimento e confirmar que o ticket não
   fecha.
3. Inserir/remover participação humana e enviar um turno posterior do visitante;
   confirmar que o turno novo é processado somente se owner estiver vazio.
4. Fora do expediente, pedir um humano e confirmar mensagem, pipeline, estágio,
   nota interna e ausência de resposta tardia da IA.
5. Verificar logs sem credenciais ou traceback remoto serializado.
6. Responder em menos de quatro segundos após a mensagem do Salomão e confirmar
   que o novo `message_id` produz exatamente uma resposta.
7. Pedir para enviar áudio e confirmar que o ticket permanece aberto.
8. Criar comentário interno e confirmar que ele não acorda a IA.
