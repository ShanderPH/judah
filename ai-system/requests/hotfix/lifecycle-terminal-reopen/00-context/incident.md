# Incident context

## Sintoma em produção

O ticket HubSpot `47211840016` entrou na rota de IA, mas não recebeu resposta.
A hidratação da conversa foi concluída e encontrou 20 mensagens; portanto, a
falha não ocorreu no webhook, no acesso ao HubSpot nem na geração do Salomão.

## Causa raiz

Duas projeções persistidas estavam incompatíveis com o estado atual do ticket:

- o placeholder do ticket estava em `QUEUE_PENDING`;
- a instância concreta da thread `11024343046` estava em `CLOSED`.

Ao receber a nova entrada válida na rota de IA, o lifecycle tentou iniciar
`CONTEXT_HYDRATING`, mas não aceitava `QUEUE_PENDING -> CONTEXT_HYDRATING` e o
worker também não reconciliava uma thread `CLOSED` depois de confirmar a rota
atual no HubSpot.

O tratamento do erro agravava a observabilidade: ao tentar transformar uma
instância terminal em `FAILED_RETRYABLE`, gerava uma segunda exceção e ocultava
o erro original. Havia ainda uma recuperação de colisão de idempotência que
capturava `IntegrityError` dentro da transação externa sem savepoint, deixando
a transação inutilizável para a leitura de recuperação.

Uma segunda falha foi encontrada na bateria completa de logs, no ticket
`47246627178` e thread `11026088553`: a hidratação inicial conhecia o ticket,
mas a resposta da API de conversations não trouxe
`threadAssociations.associatedTicketId`. A reidratação final descartava o ID já
conhecido, concluía incorretamente que a rota não podia ser validada, suprimia a
resposta e permitia que o retry repetisse o trabalho do modelo.

Os logs do worker também confundiam falhas recuperáveis e decisões esperadas
com erros finais:

- tentativas intermediárias de Celery eram registradas como `error`;
- indisponibilidade fora do expediente aparecia como `warning`;
- linhas INFO do Celery chegavam ao Railway com severidade `error` porque o
  worker substituía os handlers JSON e redirecionava saída para `stderr`;
- decisões de supressão não informavam rota observada, ação tomada ou se
  haveria retry.

## Restrições de segurança

- Reabrir o ledger não autoriza uma resposta por si só.
- O worker continua exigindo pipeline e etapa de IA configuradas, ausência de
  owner humano e ausência de participação humana.
- A mesma elegibilidade e o mesmo turno do cliente são revalidados
  imediatamente antes de publicar qualquer resposta.
- Um turno que já possui auditoria de resposta bem-sucedida não é processado
  novamente, mesmo se a instância estiver fechada.
- O ID de ticket informado pelo chamador é somente fallback; se a associação
  atual da thread existir e divergir, o valor atual do HubSpot prevalece e a
  divergência é registrada.
