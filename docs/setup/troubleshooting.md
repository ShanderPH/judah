# Troubleshooting

## Django não inicia

Confirme Python 3.14, `DJANGO_SECRET_KEY`, dependências e `manage.py check`.

## Login ou worker fica pendente

Valide PostgreSQL e Redis antes de alterar a aplicação. Em Windows, confirme as
portas 5432 e 6379 e faça um request HTTP ao serviço.

## Autoatribuição não ocorre

Verifique `AUTO_ASSIGNMENT_ENABLED`, autoridade do ambiente, calendário,
ausências, capacidade, freshness do SAT, fila e credenciais HubSpot.

## Worker ou Beat falha

Importe `core.celery`, confira Redis e liste tasks agendadas. O único job do app
`ai_agents` é o watchdog genérico; jobs de identificação ou triagem não devem
existir.
