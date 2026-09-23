# Plano — contabilizar transferências manuais sem confiar em `sourceId`

## Escopo

- BE-01: tratar somente `previousValue` como owner anterior declarado pelo webhook.
- BE-02: usar a ocupação reconciliada como owner atual no modo `shadow`.
- BE-03: derivar origem e agente anterior da `AssignedConversation` bloqueada.
- BE-04: serializar eventos concorrentes por ticket, preservando o guard de evento atrasado.
- V-01: reproduzir payload sem `previousValue` e payload com `sourceId` numérico não relacionado.
- V-02: validar regressões de owner, ciclo, capacidade e barreira de abertura.
- OPS-01: preparar o gate de ativação da barreira em `enforce`, sem alterar produção neste PR.

## Critérios de aceitação

1. Transferência manual A→B em `shadow` decrementa A, incrementa B e atualiza a projeção uma vez.
2. `sourceId` não participa da identidade do owner anterior.
3. Evento com `previousValue` incompatível com a projeção atual é ignorado como atrasado.
4. Retry ou entrega duplicada não aplica um segundo delta.
5. Os modos `off`, `shadow` e `enforce` preservam seus contratos existentes.
6. `OPENING_COHORT_BARRIER_MODE` não é alterado antes do deploy e smoke autorizados pelo usuário.

## Rollback

Reverter o commit do hotfix. Para o rollout operacional da barreira, retornar
`OPENING_COHORT_BARRIER_MODE=shadow` em API, worker e Beat e redeployar os serviços, sem alterar
`SUPPORT_CAPACITY_MODE`.
