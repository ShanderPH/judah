"""Local AgentOS entrypoint for the JUDAH AI agents.

Run with:
    uvicorn apps.ai_agents.agent_os:app --host 0.0.0.0 --port 7777 --reload
"""

from __future__ import annotations

import os
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup(set_prefix=False)

from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.team.factory import TeamFactory  # noqa: E402

from apps.ai_agents.agents.heimdall import heimdall_agent  # noqa: E402
from apps.ai_agents.agents.salomao import salomao_agent  # noqa: E402
from apps.ai_agents.agents.supervisor import SalomaoSupervisorAgent  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent.parent
AGENTOS_DIR = BASE_DIR / ".agentos"
AGENTOS_DIR.mkdir(exist_ok=True)

agentos_db = SqliteDb(db_file=os.getenv("AGENTOS_DB_FILE", str(AGENTOS_DIR / "agentos.db")))


def build_agentos_supervisor(_request_context):
    """Build the full Salomao supervisor team lazily for AgentOS runs."""
    supervisor = SalomaoSupervisorAgent(
        session_id=os.getenv("AGENTOS_SESSION_ID", "agentos-local"),
        user_metadata={
            "user_id": "agentos-local",
            "username": "agentos",
            "email": "",
            "first_name": "AgentOS",
            "last_name": "Local",
            "church_id": "",
            "hubspot_contact_id": "",
            "originating_channel": "webchat_central",
        },
    )
    return supervisor.team


agent_os = AgentOS(
    id="judah-agent-os",
    name="JUDAH AgentOS",
    description="Local AgentOS runtime for JUDAH AI support agents.",
    db=agentos_db,
    agents=[
        salomao_agent,
        heimdall_agent,
    ],
    teams=[
        TeamFactory(
            id="salomao-supervisor",
            name="Salomao Supervisor",
            description="Full local Agno chain: Heimdall triage, Knowledge RAG, and HelpdeskAction.",
            db=agentos_db,
            factory=build_agentos_supervisor,
        ),
    ],
    telemetry=False,
)

app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="apps.ai_agents.agent_os:app", host="0.0.0.0", port=7777, reload=True)
