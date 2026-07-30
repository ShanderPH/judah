# Plano — recuperação de reentrada e handoff fora do expediente

1. Corrigir a hidratação thread → ticket usando o contrato oficial do HubSpot
   e um fallback local canônico, sem adivinhação.
2. Tornar a autoridade humana cronológica e fail-closed quando não houver
   timestamps confiáveis.
3. Aplicar uma política determinística de semântica de resolução no Supervisor,
   na execução e no replay de efeitos pendentes.
4. Consumir a rota configurada para handoff fora do expediente e preservar a
   rota normal do suporte durante o horário de atendimento.
5. Reduzir a persistência e exposição de tracebacks Celery e sanitizar strings
   sensíveis depois da renderização da exceção.
6. Cobrir regressões com testes focados e executar os gates integrais do
   repositório.
7. Disponibilizar provisionamento idempotente e fail-closed do usuário Judah e
   do registro `Agent` após confirmação do HubSpot owner.
8. Substituir o booleano calculado de última mensagem por
   `conversation.newMessage` e adicionar reconciliação idempotente por
   `message_id` como safety net.
9. Exigir evidência positiva antes do fechamento por IA e reconhecer toda
   solicitação futura de mídia, anexo ou dados do cliente.
10. Auditar eventos não conversacionais, fontes duplicadas, concorrência,
    starvation e reentrada entre autoridade humana e IA.
11. Tratar `conversation.newMessage` sem direção como uma notificação neutra e
    confirmar a direção pela thread antes de alterar cursor ou lifecycle.
12. Consolidar todos os webhooks de produção no app Judah HubSpot Integration,
    autenticado por um único segredo HMAC, rejeitando assinaturas inválidas
    antes de qualquer persistência.
13. Preservar eventos HubSpot entregues fora de ordem no ledger sem permitir
    que eles desfaçam estado, cursor ou efeitos de um evento mais novo.
14. Exigir thread e `message_id` de cliente confirmados antes de qualquer
    efeito tardio de fechamento ou handoff no HubSpot.
