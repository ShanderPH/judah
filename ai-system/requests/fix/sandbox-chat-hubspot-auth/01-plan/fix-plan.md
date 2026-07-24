# Fix plan

1. Corrigir endpoint e payload do Visitor Identification API.
2. Manter credencial HubSpot somente na Route Handler server-side.
3. Preservar compatibilidade temporaria com o nome antigo da variavel.
4. Adicionar `conversation.newMessage` ao projeto de webhooks da sandbox.
5. Validar lint/build do webapp e schema/build do projeto HubSpot.
6. Apos aprovacao, isolar a verificacao HMAC do app sandbox sem alterar a
   confiabilidade dos webhooks de producao.
