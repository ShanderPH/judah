# Implementação — Gate B

## Autorização

- `require_role` agora nega identidades sem papel e preserva signatures resolvidas para o Django Ninja.
- Tickets, fila/diagnóstico e todo o router administrativo de agentes exigem manager/admin.
- `GET /auth/{user_id}` exige admin.
- Analytics agregados permanecem disponíveis a qualquer JWT; health, webhooks e auth público não foram alterados.

## Sync e agendas

- Removido `auth=None` de sync, business hours e special schedules; writes exigem manager/admin.
- Criado `AdministrativeActionAudit`, separado do ledger de IA, com ator, papel, alvo, motivo, correlation ID, fingerprint, status e resposta sanitizada.
- A reserva do audit ocorre dentro da transação antes do write. Falha de reserva impede a operação.
- `Idempotency-Key`/`X-Idempotency-Key` opcional habilita replay; fingerprint divergente retorna 409.
- O schema de agenda restringe tipo, horas e tamanho do motivo.

## Minimização

Viewer/agent recebem 403 antes da serialização de e-mail, manager email, owner ID, contato ou histórico. Manager/admin preservam o schema administrativo necessário.

`support.0025_administrative_action_audit` cria apenas a nova tabela, índices e constraint de idempotência. Nenhuma migration foi aplicada fora do SQLite privado de testes.
