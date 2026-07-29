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
