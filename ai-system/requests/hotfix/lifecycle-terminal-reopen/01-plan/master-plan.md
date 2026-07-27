# Hotfix plan

## Acceptance criteria

1. Uma entrada atual e elegível na rota de IA pode avançar de
   `QUEUE_PENDING` para `CONTEXT_HYDRATING`.
2. Uma thread fechada pode ser reconciliada somente depois de o worker
   confirmar a rota atual de IA no HubSpot.
3. Ticket fora da pipeline/etapa da IA, com owner humano ou participação
   humana continua sem resposta do Salomão.
4. Um turno já respondido não é executado novamente após fechamento ou
   redelivery.
5. Falha em instância terminal preserva o erro original e não tenta uma
   transição inválida para `FAILED_RETRYABLE`.
6. Colisão de idempotência é recuperada sem quebrar a transação externa.
7. A reidratação final preserva o ticket já conhecido quando a API de
   conversations omite a associação da thread.
8. Logs distinguem decisão esperada, retry agendado e falha terminal, incluindo
   ticket/thread, motivo, ação e contexto de rota quando aplicável.
9. O Celery preserva os handlers JSON da aplicação para que INFO não seja
   classificado como erro pelo Railway.
10. Não há migration, variável de ambiente ou alteração de contrato externo.

## Verification

- Testes de regressão do lifecycle e do pipeline HubSpot.
- Suíte completa local em SQLite isolado, Python 3.14.
- Ruff lint e format check.
- Mypy completo.
- Django system check e migration drift check.
- Smoke real após deploy do mesmo SHA em ambiente controlado.
