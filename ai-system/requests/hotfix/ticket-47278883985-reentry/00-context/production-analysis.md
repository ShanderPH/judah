# Contexto — ticket 47278883985

## Incidente

O turno final do visitante existia na thread HubSpot, mas o worker não
conseguia associar a thread ao ticket e encerrava os retries com
`ticket_route_unavailable`. Antes disso, uma resposta que ainda solicitava
informações ao cliente havia sido classificada como `candidate_resolved` e
fechou o ticket indevidamente.

## Causas confirmadas

1. A leitura de uma thread não enviava `association=TICKET`, parâmetro
   necessário para o HubSpot preencher
   `threadAssociations.associatedTicketId`.
2. Uma mensagem humana histórica bloqueava a IA indefinidamente, sem comparar
   sua ordem cronológica com o turno mais recente do visitante.
3. Não havia uma invariável determinística impedindo o fechamento quando a
   resposta continha pergunta aberta ou solicitava dados, erro ou imagem.
4. As variáveis de rota fora do expediente existiam, mas o handoff não as
   consumia.
5. O traceback do Celery podia materializar credenciais de conexão nos campos
   de exceção depois da primeira passagem do sanitizador de logs.

## Limites deliberados

- Nenhuma mutação remota, mensagem, replay, deploy ou alteração no ticket foi
  feita durante esta implementação.
- O usuário administrativo `suporte_inchurch` não foi alterado remotamente. O
  owner `81908844` foi posteriormente validado por consulta somente leitura à
  Owners API do portal `47354717`: `Suporte inChurch`,
  `suporte@inchurch.com.br`, `archived=false`. O vínculo passou a ser aceito
  pelo comando local de provisionamento seguro.
- A credencial Redis eventualmente exposta deve ser rotacionada no provedor;
  sanitização de código não revoga uma credencial já vazada.
