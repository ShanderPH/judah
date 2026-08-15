# Plano de rollout

## Pré-deploy

1. Conectar o Browser e concluir o roteiro do `HANDOFF.md`.
2. Abrir PR da branch `feat/helpdesk-calendar-triage-integration` para `main`.
3. Reexecutar lint, tipos, testes e build no CI.
4. Criar snapshot das regras legadas e confirmar timezone `America/Sao_Paulo` em staging.
5. Aplicar migration `0028` em staging e revisar as regras materializadas.
6. Executar smoke de uma ausência controlada em webchat, conferindo plain text e rich text no HubSpot.
7. Para WhatsApp Business nativo, definir/confirmar um transporte oficialmente suportado e só então executar o smoke; não promover confiando apenas no endpoint Conversations legado.

## Deploy

1. Implantar API com predeploy/migrations.
2. Implantar worker e beat no mesmo SHA.
3. Implantar WebApp.
4. Confirmar health checks e ausência de erros de resolver/handoff por cinco minutos.

## Rollback

- Reverter aplicação e WebApp para o SHA anterior.
- Não remover as tabelas nativas até exportar qualquer edição criada após o deploy.
- Enquanto as tabelas existirem, o fallback legado permanece disponível para datas sem regra correspondente.

## Autorização

Este documento prepara o deploy, mas não o autoriza. Nenhuma mutação de staging/produção foi executada nesta request.
