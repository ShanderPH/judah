# Plano — comercial e agrupamento de mensagens

## Objetivo

1. Responder pedidos explícitos de contato comercial com o formulário oficial.
2. Agrupar mensagens consecutivas do cliente em um único turno antes da execução do Salomão.
3. Preservar contexto, ordem, idempotência e rastreabilidade sem armazenar o texto do cliente no Redis.

## Implementação

- Criar uma representação única do turno corrente: todas as mensagens `INCOMING`
  desde a última mensagem `OUTGOING`, em ordem cronológica.
- Adicionar uma política comercial determinística com proteção contra falsos
  positivos e suporte a confirmações contextuais como “sim”.
- Agendar webhooks de mensagem com uma janela curta de silêncio e um limite
  máximo de espera. Cada novo evento substitui o token Redis do agendamento
  anterior; apenas o token mais recente pode executar.
- Manter HubSpot/WebhookEvent como fonte durável do conteúdo. Redis guarda
  somente tokens e horários efêmeros de coordenação.
- Registrar na instância apenas IDs, quantidade e intervalo temporal do lote,
  sem duplicar texto ou PII.

## Critérios de aceitação

- “Quero falar com o Comercial” retorna exatamente o formulário aprovado.
- Mensagens como “Tenho interesse” + “nos planos e valores” geram uma única
  resposta coerente ao conjunto.
- “Plano de contas” e “valor do ingresso” não acionam o formulário comercial.
- Uma sequência rápida gera uma execução; tarefas antigas são descartadas por
  token, sem bloquear a mais recente.
- Uma sequência longa não espera indefinidamente: respeita o limite máximo.
- Falha no Redis degrada para execução atrasada, sem descartar a mensagem.
- Testes, lint e tipagem permanecem aprovados.
