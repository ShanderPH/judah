# Helpdesk Calendar integrado à triagem nativa

## Visão executiva

A implementação transforma o calendário do Helpdesk em uma fonte operacional editável e compartilhada pela interface administrativa, pela disponibilidade de agentes e pelo fluxo de triagem/handoff introduzido no PR #105. O objetivo principal foi eliminar decisões divergentes de horário e tornar regras existentes gerenciáveis sem perder compatibilidade durante a migração.

## Problemas resolvidos

- O calendário antes disputava largura com cards exclusivos da dashboard.
- Os controles de período estavam fragmentados e os dias não exibiam horários completos.
- O detalhe do dia ocupava espaço permanente e não oferecia edição rápida.
- Regras históricas de atendimento não estavam gerenciáveis na nova experiência.
- A triagem nativa podia tomar decisões de handoff sem um snapshot estruturado da agenda.
- Mensagens de ausência precisavam de uma representação segura para canais HubSpot.

## Solução entregue

### Experiência do operador

- Layout integral fora da dashboard.
- Cabeçalho operacional conciso e unificado.
- Grade maior, responsiva e capaz de mostrar vários intervalos.
- Modal de detalhe com edição rápida.
- Gestão de regras publicadas, incluindo as migradas do legado.
- Wizard para serviço/ausência, recorrência, prioridade e múltiplos intervalos.

### Motor de calendário

- Agenda publicada com timezone IANA, versionamento e concorrência otimista.
- Precedência determinística de ausência e prioridade.
- Resolução por dia, intervalo e instante atual.
- Migração idempotente de horários, Quinta Fire, feriados e exceções existentes.
- Fallback legado preservado para rollout seguro.

### Triagem e canais

- Snapshot tipado no contexto de conversa.
- Resolução assíncrona segura no webhook.
- Revalidação antes do handoff quando o snapshot é autoritativo.
- Mensagem customizada de ausência usada na confirmação e no roteamento fora de horário.
- Payload HubSpot com plain text e rich text sanitizados para webchat/custom channels; conteúdo provider-neutral preparado para outros adaptadores.

## Qualidade comprovada

- 1.079 testes backend aprovados; 12 ignorados.
- Cobertura global de 90,07%.
- Ruff, mypy, Django checks e verificação de migrations aprovados.
- 28 testes frontend, ESLint, TypeScript e build Next.js 16.3.0 aprovados.
- Smoke local: API HTTP 200 e proteção de autenticação de `/calendar` confirmada.

## Estado e próximos passos

A branch está pronta para revisão técnica e PR. O deploy não foi executado. Antes de promovê-la para `DONE`, faltam a validação visual com browser conectado, o smoke controlado de webchat/custom channel e uma decisão de transporte para WhatsApp Business nativo, pois o endpoint Conversations legado não tem suporte oficial para esse envio. Depois disso, aplicar o rollout documentado, observar logs e confirmar os serviços Railway no mesmo SHA.
