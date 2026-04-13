"""Management command: check_assignment_system

Prints a full diagnostic report of the auto-assignment queue system:
  - All agents with status, eligibility, and chat counts
  - Agents that are absent (AWAY / OFFLINE) and therefore excluded from the queue
  - Tickets currently waiting in new_conversations
  - Last 5 assignment log entries

Usage:
    python manage.py check_assignment_system
    python manage.py check_assignment_system --tickets 10
    python manage.py check_assignment_system --format json
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.support.models import Agent, AssignmentLog, NewConversation
from apps.support.queue_service import get_eligible_agents, get_last_assigned_owner_id

_WIDTH = 80


def _divider(char: str = "-") -> str:
    return char * _WIDTH


def _header(title: str) -> str:
    pad = (_WIDTH - len(title) - 2) // 2
    right = _WIDTH - pad - len(title) - 2
    return f"\n{'=' * pad} {title} {'=' * right}"


def _status_badge(status: str) -> str:
    return f"{status.upper():8}"


def _ago(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, UTC)
    delta = timezone.now() - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


class Command(BaseCommand):
    help = "Print a diagnostic report of the auto-assignment queue system."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tickets",
            type=int,
            default=20,
            metavar="N",
            help="Number of recent new_conversations entries to display (default: 20).",
        )
        parser.add_argument(
            "--format",
            choices=["table", "json"],
            default="table",
            help="Output format: table (default) or json.",
        )

    def handle(self, *args, **options):
        if options["format"] == "json":
            self._output_json(options)
        else:
            self._output_table(options)

    # ------------------------------------------------------------------
    # Table output
    # ------------------------------------------------------------------

    def _output_table(self, options: dict) -> None:
        self.stdout.write(f"\n{'JUDAH - AUTO-ASSIGNMENT SYSTEM DIAGNOSTIC':^{_WIDTH}}")
        self.stdout.write(f"{timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z'):^{_WIDTH}}")

        self._section_agents()
        self._section_queue(limit=options["tickets"])
        self._section_last_assignments()
        self._section_system_health()

        self.stdout.write("\n")

    def _section_agents(self) -> None:
        self.stdout.write(_header("AGENTES"))

        all_agents = list(Agent.objects.order_by("status_enum", "name"))
        eligible_ids = {a.pk for a in get_eligible_agents()}
        last_owner = get_last_assigned_owner_id()

        self.stdout.write(
            f"\n{'NOME':<22} {'STATUS':>8}  {'CHATS':>10}  {'ELEGIVEL':>8}  {'ULTIMO ATEND.':>15}  {'OBS.':<20}"
        )
        self.stdout.write(_divider())

        online_count = 0
        away_count = 0
        eligible_count = 0

        for agent in all_agents:
            status = agent.status_enum or "offline"
            at_capacity = agent.current_simultaneous_chats >= (agent.max_simultaneous_chats or 5)
            is_eligible = agent.pk in eligible_ids

            if status == "online":
                online_count += 1
            elif status in ("away", "offline", "busy"):
                away_count += 1

            if is_eligible:
                eligible_count += 1

            obs_parts = []
            if at_capacity:
                obs_parts.append("CAPACIDADE MAX.")
            if agent.hubspot_owner_id == last_owner:
                obs_parts.append("ultimo atribuido")
            if not agent.auto_assign_enabled:
                obs_parts.append("auto-assign OFF")

            chat_display = f"{agent.current_simultaneous_chats}/{agent.max_simultaneous_chats or 5}"
            elegivel = "SIM" if is_eligible else "NAO"

            self.stdout.write(
                f"{agent.name:<22} "
                f"{_status_badge(status)}  "
                f"{chat_display:>10}  "
                f"{elegivel:>8}  "
                f"{_ago(agent.last_assignment_at):>15}  "
                f"{' | '.join(obs_parts) if obs_parts else '-'}"
            )

        self.stdout.write(_divider())
        self.stdout.write(
            f"  Online: {online_count}  |  Ausentes: {away_count}  |  Elegiveis p/ receber: {eligible_count}"
        )

        # Absent agents block
        absent = [a for a in all_agents if a.status_enum in ("away", "offline", "busy")]
        if absent:
            self.stdout.write("\n  Agentes ausentes (fora da fila):")
            for a in absent:
                chats_info = (
                    f", ainda com {a.current_simultaneous_chats} chat(s) aberto(s)"
                    if a.current_simultaneous_chats > 0
                    else ""
                )
                self.stdout.write(
                    f"  > {a.name:<22} [{a.status_enum.upper()}]  hubspot_owner_id={a.hubspot_owner_id}{chats_info}"
                )
        else:
            self.stdout.write("\n  [OK] Todos os agentes disponiveis estao ONLINE.")

    def _section_queue(self, limit: int) -> None:
        self.stdout.write(_header("FILA DE CONVERSAS NOVAS"))

        pending = NewConversation.objects.order_by("entered_queue_at")
        all_new = NewConversation.objects.order_by("-entered_queue_at")[:limit]

        pending_count = pending.count()
        total_count = pending_count

        pending_label = f"AGUARDANDO ATRIBUICAO: {pending_count}"
        self.stdout.write(f"\n  {pending_label}  |  Total registrado: {total_count}")

        if pending_count > 0:
            self.stdout.write("\n  Tickets na fila:")
            self.stdout.write(f"  {'TICKET ID':<18} {'PRIORIDADE':>10}  {'AGUARDANDO HA':>15}  {'CLIENTE':<20}")
            self.stdout.write(_divider("."))
            for conv in pending[:20]:
                self.stdout.write(
                    f"  > {conv.hubspot_ticket_id:<18} "
                    f"{(conv.priority or '-'):>10}  "
                    f"{_ago(conv.entered_queue_at):>15}  "
                    f"{(conv.contact_name or '-'):<20}"
                )
        else:
            self.stdout.write("\n  [OK] Nenhum ticket aguardando atribuicao.")

        if total_count > 0:
            self.stdout.write(f"\n  Ultimos {min(limit, total_count)} registros em new_conversations:")
            self.stdout.write(f"  {'TICKET ID':<18} {'ENTROU NA FILA':>20}  {'HA':>12}")
            self.stdout.write(_divider("."))
            for conv in all_new:
                self.stdout.write(
                    f"  {conv.hubspot_ticket_id:<18} "
                    f"{conv.entered_queue_at.strftime('%Y-%m-%d %H:%M:%S'):>20}  "
                    f"{_ago(conv.entered_queue_at):>12}"
                )
        else:
            self.stdout.write("\n  (Tabela new_conversations vazia - aguardando o primeiro webhook)")

    def _section_last_assignments(self) -> None:
        self.stdout.write(_header("ULTIMAS ATRIBUICOES"))

        logs = AssignmentLog.objects.order_by("-assigned_at")[:5]

        if not logs.exists():
            self.stdout.write("\n  Nenhuma atribuicao registrada ainda.")
            return

        self.stdout.write(f"\n  {'TICKET ID':<18} {'AGENTE':<22} {'TIPO':>10}  {'ESPERA (s)':>12}  {'QUANDO':>12}")
        self.stdout.write(_divider("."))

        for log in logs:
            wait = f"{float(log.queue_wait_seconds):.1f}s" if log.queue_wait_seconds else "-"
            self.stdout.write(
                f"  {log.ticket_id:<18} "
                f"{log.agent_name:<22} "
                f"{log.assignment_type:>10}  "
                f"{wait:>12}  "
                f"{_ago(log.assigned_at):>12}"
            )

    def _section_system_health(self) -> None:
        self.stdout.write(_header("STATUS DO SISTEMA"))

        eligible = get_eligible_agents()
        pending = NewConversation.objects.count()

        issues = []
        warnings = []

        if not eligible:
            issues.append("Nenhum agente elegivel disponivel - atribuicoes bloqueadas")
        elif len(eligible) == 1:
            warnings.append(f"Apenas 1 agente elegivel ({eligible[0].name}) - regra 2 desativada")

        if pending > 0:
            issues.append(f"{pending} ticket(s) aguardando na fila sem agente disponivel")

        away_with_chats = [
            a
            for a in Agent.objects.filter(status_enum__in=["away", "offline", "busy"])
            if a.current_simultaneous_chats > 0
        ]
        if away_with_chats:
            names = ", ".join(a.name for a in away_with_chats)
            warnings.append(f"Agentes ausentes com chats abertos: {names}")

        self.stdout.write("")
        if not issues and not warnings:
            self.stdout.write("  [OK] Sistema operando normalmente.")
        else:
            for issue in issues:
                self.stdout.write(f"  [ERR] {issue}")
            for warn in warnings:
                self.stdout.write(f"  [!]  {warn}")

        self.stdout.write("\n  Dica: use '--format json' para saida em JSON.")

    # ------------------------------------------------------------------
    # JSON output
    # ------------------------------------------------------------------

    def _output_json(self, options: dict) -> None:
        all_agents = list(Agent.objects.order_by("status_enum", "name"))
        eligible_ids = {a.pk for a in get_eligible_agents()}
        last_owner = get_last_assigned_owner_id()

        agents_data = [
            {
                "id": str(a.id),
                "name": a.name,
                "email": a.agent_email,
                "hubspot_owner_id": a.hubspot_owner_id,
                "status": a.status_enum,
                "current_chats": int(a.current_simultaneous_chats),
                "max_chats": a.max_simultaneous_chats or 5,
                "eligible": a.pk in eligible_ids,
                "at_capacity": a.current_simultaneous_chats >= (a.max_simultaneous_chats or 5),
                "auto_assign_enabled": a.auto_assign_enabled,
                "last_assignment_at": a.last_assignment_at.isoformat() if a.last_assignment_at else None,
                "is_last_assigned": a.hubspot_owner_id == last_owner,
            }
            for a in all_agents
        ]

        pending_qs = NewConversation.objects.order_by("entered_queue_at")
        pending_data = [
            {
                "hubspot_ticket_id": c.hubspot_ticket_id,
                "priority": c.priority,
                "contact_name": c.contact_name,
                "entered_queue_at": c.entered_queue_at.isoformat(),
                "wait_seconds": round((timezone.now() - c.entered_queue_at).total_seconds(), 1),
            }
            for c in pending_qs
        ]

        logs_qs = AssignmentLog.objects.order_by("-assigned_at")[:5]
        logs_data = [
            {
                "ticket_id": lg.ticket_id,
                "agent_name": lg.agent_name,
                "hubspot_owner_id": lg.hubspot_owner_id,
                "assignment_type": lg.assignment_type,
                "queue_wait_seconds": float(lg.queue_wait_seconds) if lg.queue_wait_seconds else None,
                "assigned_at": lg.assigned_at.isoformat(),
            }
            for lg in logs_qs
        ]

        eligible_list = get_eligible_agents()
        away = [a for a in all_agents if a.status_enum in ("away", "offline", "busy")]

        output = {
            "timestamp": timezone.now().isoformat(),
            "summary": {
                "total_agents": len(all_agents),
                "online_agents": sum(1 for a in all_agents if a.status_enum == "online"),
                "away_agents": len(away),
                "eligible_agents": len(eligible_list),
                "pending_queue_depth": len(pending_data),
            },
            "absent_agents": [
                {
                    "name": a.name,
                    "hubspot_owner_id": a.hubspot_owner_id,
                    "status": a.status_enum,
                    "open_chats": int(a.current_simultaneous_chats),
                }
                for a in away
            ],
            "agents": agents_data,
            "pending_tickets": pending_data,
            "last_assignments": logs_data,
        }

        self.stdout.write(json.dumps(output, ensure_ascii=False, indent=2))
