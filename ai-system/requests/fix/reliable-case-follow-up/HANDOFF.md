# Handoff

## Resumo

- Persiste o ID real da última mensagem recebida e usa uma chave de resposta
  canônica por conversa e turno.
- Impede que um sucesso de envio antigo seja reutilizado para uma mensagem
  nova e evita reprocessar um turno já respondido.
- Reconhece pedidos como “quero saber sobre o caso que reportei” antes de
  chamar o modelo e solicita protocolo ou ID da igreja local.
- Consulta um protocolo ou todos os casos da igreja com título, status e
  prioridade, filtrando etapas encerradas/canceladas.
- Complementa o HubSpot sandbox com o espelho N2 do Supabase.
- Responde intenção comercial com o formulário oficial, sem consumir tokens
  ou depender da interpretação do modelo.
- Agrupa mensagens consecutivas em um único turno com janela de silêncio de
  4 segundos e espera máxima de 12 segundos.
- Usa token atômico no Redis para descartar tarefas superadas e mantém o
  conteúdo durável no HubSpot/WebhookEvent.
- Instrui Supervisor e Salomão v1 a interpretar o lote completo como uma fala,
  preservando ordem e contexto.

## Arquivos modificados

- apps/ai_agents/api/webhooks.py
- apps/ai_agents/services/execution.py
- apps/ai_agents/services/protocol_lookup.py
- apps/ai_agents/tests/test_instance_identity.py
- apps/ai_agents/tests/test_protocol_lookup.py
- apps/ai_agents/tests/test_workflow_execution.py
- apps/ai_agents/agents/salomao_chat.py
- apps/ai_agents/agents/supervisor.py
- apps/ai_agents/services/commercial_contact.py
- apps/ai_agents/services/conversation_turn.py
- apps/ai_agents/services/hubspot.py
- apps/ai_agents/tasks.py
- apps/webhooks/handlers/hubspot_handler.py
- apps/webhooks/services.py
- core/settings/base.py

## Como testar

- python run_tests_local.py
- python -m ruff check apps/ai_agents/api/webhooks.py apps/ai_agents/services/execution.py apps/ai_agents/services/protocol_lookup.py
- python -m mypy apps/ai_agents/api/webhooks.py apps/ai_agents/services/execution.py apps/ai_agents/services/protocol_lookup.py

## Riscos e pontos de integração

- O staging não possui acesso direto ao portal HubSpot principal. No fallback,
  o título é composto com módulo e funcionalidade do ticket espelhado porque
  o campo subject não existe na tabela tickets.
- A atualização do status depende do recebimento dos eventos
  hs_pipeline_stage no ledger de webhooks.
- O agrupamento usa `SALOMAO_MESSAGE_QUIET_SECONDS=4` e
  `SALOMAO_MESSAGE_MAX_WAIT_SECONDS=12` por padrão. Em indisponibilidade do
  Redis, degrada para tarefas atrasadas protegidas pelas travas já existentes.
- Não houve deploy nem envio de mensagem real; o smoke test visual deve ser
  feito depois que o usuário autorizar PR/deploy em staging.
