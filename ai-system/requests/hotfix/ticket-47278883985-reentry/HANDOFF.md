# HANDOFF — ticket 47278883985

## Resultado

O hotfix está implementado e validado localmente. A reentrada deixa de depender
de uma associação ausente, participação humana histórica não bloqueia um turno
posterior do visitante, fechamento exige resposta realmente conclusiva e o
handoff fora do expediente usa sua rota própria.

## Arquivos principais

- `apps/ai_agents/services/hubspot.py`
- `apps/ai_agents/services/decision_policy.py`
- `apps/ai_agents/agents/supervisor.py`
- `apps/ai_agents/services/execution.py`
- `common/logging.py`
- `core/settings/base.py`
- `apps/support/management/commands/provision_support_agent.py`
- `.env.example`
- `docs/setup/environment-variables.md`
- `docs/services/ai_agents.md`

## Segurança operacional

- Não houve PR, push, deploy, replay ou mutação de dados remotos.
- Antes de produção, rotacionar qualquer credencial Redis já exposta.
- Confirmar que o workflow HubSpot associado ao estágio fora do expediente
  encaminha a conversa para o N1 no próximo período de atendimento.
- O owner `81908844` foi confirmado para `suporte_inchurch`, mas o comando
  ainda não foi executado em produção.

## Provisionamento autorizado após deploy

Primeiro valide sem escrita:

```powershell
python manage.py provision_support_agent `
  --username suporte_inchurch `
  --hubspot-owner-id 81908844 `
  --agent-email suporte@inchurch.com.br
```

Depois de revisar o plano impresso, aplique explicitamente:

```powershell
python manage.py provision_support_agent `
  --username suporte_inchurch `
  --hubspot-owner-id 81908844 `
  --agent-email suporte@inchurch.com.br `
  --execute
```

O comando preserva o papel atual do usuário, vincula seu
`hubspot_owner_id`, cria o `Agent` ausente em estado `offline` e não sobrescreve
owner/e-mail conflitante.

## Smoke recomendado após deploy em staging

1. Criar uma conversa nova e obter uma resposta da IA.
2. Fazer uma pergunta que exija esclarecimento e confirmar que o ticket não
   fecha.
3. Inserir/remover participação humana e enviar um turno posterior do visitante;
   confirmar que o turno novo é processado somente se owner estiver vazio.
4. Fora do expediente, pedir um humano e confirmar mensagem, pipeline, estágio,
   nota interna e ausência de resposta tardia da IA.
5. Verificar logs sem credenciais ou traceback remoto serializado.
