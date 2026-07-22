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

## Arquivos modificados

- apps/ai_agents/api/webhooks.py
- apps/ai_agents/services/execution.py
- apps/ai_agents/services/protocol_lookup.py
- apps/ai_agents/tests/test_instance_identity.py
- apps/ai_agents/tests/test_protocol_lookup.py
- apps/ai_agents/tests/test_workflow_execution.py

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
- Não houve deploy nem envio de mensagem real; o smoke test visual deve ser
  feito depois que o usuário autorizar PR/deploy em staging.
