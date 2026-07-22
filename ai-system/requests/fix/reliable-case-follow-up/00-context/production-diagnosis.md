# Diagnóstico

- A pergunta da conversa 47074028289 chegou ao HubSpot como a mensagem
  5cc44121a9be4436ae0a43509c446603.
- O Supervisor gerou uma resposta, mas last_message_id estava vazio e a
  chave de idempotência colidiu com a resposta da saudação.
- Staging recebe os turnos por ticket.propertyChange; o último
  conversation.newMessage persistido é de outubro de 2025.
- O fluxo de protocolo era executado apenas quando require_incoming=True,
  portanto o caminho real de staging ignorava a consulta determinística.
- A credencial HubSpot de staging pertence ao portal sandbox 51734496.
  Os tickets N2 informados estão no portal principal 47354717, mas já são
  espelhados nas tabelas tickets e webhook_events do Supabase.

## Decisão

Usar a última mensagem hidratada como identidade canônica do turno e como
sinal de entrada. Consultar o HubSpot quando disponível e complementar a
consulta com o espelho do Supabase, usando o evento mais recente de
hs_pipeline_stage como fonte do status.
