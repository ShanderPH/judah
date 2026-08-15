# BE-01 — Integração do calendário com a triagem nativa

## Resultado

- O contexto da conversa passou a carregar um snapshot tipado do calendário (`ScheduleResolution`), preservando o contrato de identidade entregue pelo PR #105.
- O webhook resolve o calendário de forma segura em código assíncrono e define `is_off_hours` a partir da mesma autoridade usada pelo handoff.
- O handoff revalida snapshots autoritativos imediatamente antes do roteamento, evitando usar uma regra que mudou durante a triagem.
- Chamadores legados sem snapshot continuam respeitando o valor explícito de `is_off_hours`, sem regressão de pipeline.
- `agent_sync_service` e os helpers legados delegam ao resolvedor publicado, mantendo fallback determinístico durante rollout/migração.

## Mensagens por canal

- A mensagem de ausência aceita Markdown limitado no cadastro.
- O envio ao thread do HubSpot produz `text` sem marcadores e `richText` seguro para os canais que o suportam.
- Emojis, links legíveis e quebras de linha são preservados; HTML arbitrário é rejeitado no schema.
- Para WhatsApp Business nativo, essa formatação não equivale a transporte validado: a documentação oficial não dá suporte ao envio pelo endpoint Conversations usado pelo legado.

## Segurança operacional

- Nenhum segredo foi adicionado ao repositório.
- Nenhuma chamada de escrita foi feita ao HubSpot ou à produção.
- Concorrência otimista protege atualização e desativação de regras por versão.
