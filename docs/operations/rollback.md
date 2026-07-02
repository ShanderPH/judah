> [Índice completo](../INDEX.md)

# Rollback

## Resumo

Procedimentos para reverter deploys problemáticos no Railway.

## Rollback de código

1. No Railway Dashboard, selecione o serviço.
2. Vá em "Deployments".
3. Escolha o deployment anterior estável.
4. Clique em "Redeploy".

## Rollback de banco

> **Atenção:** nunca rode `DROP`/`TRUNCATE` em produção sem aprovação do Felipe.

1. Identifique a migration problemática.
2. Execute o revert no ambiente desejado:
   ```bash
   python manage.py migrate <app> <migration_anterior>
   ```
3. Valide integridade dos dados.

## Rollback de variáveis de ambiente

1. Acesse Railway Dashboard → Variables.
2. Restaure o valor anterior.
3. Redeploy do serviço.

## Comunicação

- Notifique o time no Slack/Jira.
- Atualize o incidente no Sentry.
- Documente lições aprendidas.

## Arquivos relacionados

- [`operations/deployment.md`](./deployment.md)
