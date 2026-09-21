# Diagnóstico de produção

Cinco de sete coortes observadas em `shadow` permaneceram `active` depois do deadline, todas sem backlog
deferido. Em 21/09, o callback executou após a fila ser consumida e retornou `drained` com
`total_pending=0`, mas não alterou o estado da coorte.

## Causa raiz

O callback delega a finalização ao drain. O drain retorna imediatamente quando não encontra linha
`pending/queued`, antes de avaliar coortes expiradas. Em `shadow`, as conversas seguem para atribuição e
esvaziam a fila antes do callback; sem uma linha para atravessar a barreira novamente, a transição para
`released` nunca ocorre.

O readiness agrava o risco de rollout ao selecionar a coorte ativa mais antiga, permitindo que resíduos
históricos escondam a coorte da janela atual.
