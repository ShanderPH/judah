"""Stable, operator-friendly error descriptions for support routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class CatalogedError:
    """Describe one operational failure without exposing provider payloads."""

    catalog_code: str
    message: str
    category: str
    retryable: bool
    action_taken: str
    operator_hint: str


_UNKNOWN_ERROR = CatalogedError(
    catalog_code="SUP-UNKNOWN-001",
    message="O fluxo de atendimento encontrou uma falha ainda não classificada.",
    category="unclassified",
    retryable=False,
    action_taken="A execução foi interrompida com segurança e preservada para diagnóstico.",
    operator_hint="Consulte exception_type, task_id, ticket_id e queue_row_id no mesmo registro.",
)

_ERRORS: Final[dict[str, CatalogedError]] = {
    "legacy_cycle_ambiguous": CatalogedError(
        catalog_code="SUP-QUEUE-001",
        message=(
            "A linha legada da fila já possui uma atribuição concluída, mas não está vinculada a um ciclo confiável."
        ),
        category="queue_integrity",
        retryable=False,
        action_taken="A linha foi colocada em quarentena para impedir atribuição duplicada.",
        operator_hint="Revise o histórico do ticket antes de reativar manualmente essa linha.",
    ),
    "stale_cycle": CatalogedError(
        catalog_code="SUP-QUEUE-002",
        message="A linha da fila pertence a um ciclo que não está mais no estado de espera.",
        category="queue_integrity",
        retryable=False,
        action_taken="O processamento do ciclo antigo foi encerrado e a linha foi isolada.",
        operator_hint="Confirme o ciclo atual do ticket e não reutilize a linha antiga.",
    ),
    "no_eligible_candidate": CatalogedError(
        catalog_code="SUP-AVAIL-001",
        message="Nenhum agente elegível foi confirmado pela fonte autoritativa de disponibilidade.",
        category="agent_availability",
        retryable=True,
        action_taken="O ticket permaneceu na fila com nova tentativa programada.",
        operator_hint="Verifique horário, presença, capacidade e sincronização dos agentes.",
    ),
    "hubspot_ticket_not_found": CatalogedError(
        catalog_code="SUP-HUBSPOT-001",
        message="O ticket deixou de existir ou não está acessível no portal HubSpot configurado.",
        category="provider_not_found",
        retryable=False,
        action_taken="A reserva foi compensada e a linha foi colocada em quarentena.",
        operator_hint="Confirme o portal, o ID do ticket e se o registro foi excluído ou mesclado.",
    ),
    "hubspot_ticket_fetch_failed": CatalogedError(
        catalog_code="SUP-HUBSPOT-002",
        message="Não foi possível carregar os dados do ticket no HubSpot.",
        category="provider_read",
        retryable=True,
        action_taken="O ticket não foi admitido na fila nesta execução.",
        operator_hint="Verifique status HTTP, escopos do aplicativo, token e disponibilidade da API.",
    ),
    "hubspot_assignment_transient": CatalogedError(
        catalog_code="SUP-HUBSPOT-003",
        message="O HubSpot não confirmou a alteração de proprietário e a falha pode ser transitória.",
        category="provider_write",
        retryable=True,
        action_taken="A capacidade reservada foi liberada e uma nova tentativa foi agendada.",
        operator_hint="Consulte provider_error_code, provider_http_status e next_retry_at.",
    ),
    "hubspot_owner_unreadable": CatalogedError(
        catalog_code="SUP-HUBSPOT-004",
        message="Após uma resposta ambígua, não foi possível consultar o proprietário atual do ticket.",
        category="provider_reconciliation",
        retryable=False,
        action_taken="A tentativa foi marcada para reparo manual, sem assumir sucesso ou falha.",
        operator_hint="Consulte o ticket no HubSpot e reconcilie o proprietário antes de liberar a tentativa.",
    ),
    "hubspot_owner_conflict": CatalogedError(
        catalog_code="SUP-HUBSPOT-005",
        message="O proprietário atual do ticket diverge do proprietário esperado pela tentativa.",
        category="provider_reconciliation",
        retryable=False,
        action_taken="A tentativa foi marcada para reparo para evitar sobrescrever uma ação humana.",
        operator_hint="Compare desired_owner_id e current_owner_id antes de qualquer correção.",
    ),
    "queue_drain_no_progress": CatalogedError(
        catalog_code="SUP-QUEUE-003",
        message="O dreno da fila não conseguiu identificar um item processável nem avançar.",
        category="queue_processing",
        retryable=True,
        action_taken="O ciclo atual foi encerrado para evitar um loop sem progresso.",
        operator_hint="Verifique locks, elegibilidade, next_assignment_attempt_at e o item mais antigo.",
    ),
    "queue_drain_unexpected": CatalogedError(
        catalog_code="SUP-QUEUE-004",
        message="O dreno periódico da fila terminou com uma exceção não tratada.",
        category="queue_processing",
        retryable=True,
        action_taken="O Celery registrou a falha; as linhas permaneceram persistidas para nova execução.",
        operator_hint="Use exception_type, task_id e o traceback para identificar a etapa exata.",
    ),
    "assignment_repair_unexpected": CatalogedError(
        catalog_code="SUP-REPAIR-001",
        message="Uma tentativa de atribuição falhou durante a reconciliação automática.",
        category="assignment_repair",
        retryable=False,
        action_taken="A tentativa foi marcada como repair_required para impedir confirmação incorreta.",
        operator_hint="Consulte attempt_id, cycle_id e last_error_code antes de reparar.",
    ),
    "assignment_task_retry": CatalogedError(
        catalog_code="SUP-TASK-001",
        message="A tarefa de atribuição imediata encontrou uma falha inesperada.",
        category="task_execution",
        retryable=True,
        action_taken="O Celery programou uma nova tentativa e preservou o ticket na fila.",
        operator_hint="Consulte exception_type, retry_count, max_retries e ticket_id.",
    ),
    "availability_reconciliation_failed": CatalogedError(
        catalog_code="SUP-AVAIL-002",
        message="A atualização autoritativa de disponibilidade falhou antes da atribuição.",
        category="agent_availability",
        retryable=True,
        action_taken="A atribuição foi bloqueada e o ticket permaneceu na fila.",
        operator_hint="Verifique o retorno da Users API do HubSpot e o heartbeat dos agentes.",
    ),
    "lifecycle_transition_failed": CatalogedError(
        catalog_code="SUP-LIFECYCLE-001",
        message="A atribuição ocorreu, mas o lifecycle local não confirmou a transição esperada.",
        category="lifecycle",
        retryable=False,
        action_taken="A atribuição do HubSpot foi preservada e a divergência foi registrada para reparo.",
        operator_hint="Compare o estado da ConversationInstance com o proprietário atual do ticket.",
    ),
}


def _resolve_error(error_code: str) -> CatalogedError:
    if error_code in _ERRORS:
        return _ERRORS[error_code]
    if error_code.endswith("_owner_unreadable"):
        return _ERRORS["hubspot_owner_unreadable"]
    if error_code.endswith("_owner_conflict"):
        return _ERRORS["hubspot_owner_conflict"]
    if error_code.startswith(("hubspot_http_", "rate_limited", "timeout", "server_error")):
        return _ERRORS["hubspot_assignment_transient"]
    return _UNKNOWN_ERROR


def cataloged_error_context(
    error_code: str,
    *,
    retryable: bool | None = None,
    action_taken: str | None = None,
) -> dict[str, str | bool]:
    """Return consistent structured fields for an operational error log."""
    descriptor = _resolve_error(error_code)
    return {
        "error_catalog_code": descriptor.catalog_code,
        "failure_code": error_code,
        "message_error": f"Erro catalogado [{descriptor.catalog_code}]: {descriptor.message}",
        "error_category": descriptor.category,
        "retryable": descriptor.retryable if retryable is None else retryable,
        "action_taken": action_taken or descriptor.action_taken,
        "operator_hint": descriptor.operator_hint,
    }
