"""Local AgentOS entrypoint for the JUDAH AI agents.

Run with:
    uvicorn apps.ai_agents.agent_os:app --host 127.0.0.1 --port 7777 --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup(set_prefix=False)

from agno.agent import Agent  # noqa: E402
from agno.agent.factory import AgentFactory  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.team.factory import TeamFactory  # noqa: E402
from agno.tools import Function  # noqa: E402

from apps.ai_agents.agents.base import build_primary_model  # noqa: E402
from apps.ai_agents.agents.heimdall import heimdall_agent  # noqa: E402
from apps.ai_agents.agents.salomao import salomao_agent  # noqa: E402
from apps.ai_agents.agents.salomao_chat import SalomaoChatAgent  # noqa: E402
from apps.ai_agents.agents.supervisor import SalomaoSupervisorAgent  # noqa: E402
from apps.ai_agents.agents.triage import HeimdallTriageAgent  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent.parent
AGENTOS_DIR = BASE_DIR / ".agentos"
AGENTOS_DIR.mkdir(exist_ok=True)

agentos_db = SqliteDb(db_file=os.getenv("AGENTOS_DB_FILE", str(AGENTOS_DIR / "agentos.db")))


def _agentos_user_metadata(originating_channel: str = "webchat_central") -> dict[str, str]:
    return {
        "user_id": "agentos-local",
        "username": "agentos",
        "email": "",
        "first_name": "AgentOS",
        "last_name": "Local",
        "church_id": "",
        "hubspot_contact_id": "",
        "originating_channel": originating_channel,
    }


def build_agentos_supervisor(_request_context):
    """Build the full Salomao supervisor team lazily for AgentOS runs."""
    supervisor = SalomaoSupervisorAgent(
        session_id=os.getenv("AGENTOS_SESSION_ID", "agentos-local"),
        user_metadata=_agentos_user_metadata(),
        db=agentos_db,
    )
    return supervisor.team


def build_agentos_heimdall(_request_context):
    """Build the typed Heimdall triage agent for direct AgentOS tests."""
    return HeimdallTriageAgent(
        session_id=os.getenv("AGENTOS_SESSION_ID", "agentos-local"),
        user_metadata=_agentos_user_metadata(),
        db=agentos_db,
    )


def build_agentos_salomao_chat(_request_context):
    """Build the Salomao v1 adapter agent for direct AgentOS tests."""
    return SalomaoChatAgent(
        session_id=os.getenv("AGENTOS_SESSION_ID", "agentos-local"),
        user_metadata=_agentos_user_metadata(),
        db=agentos_db,
    )


def run_salomao_supervisor_pipeline(message: str) -> dict[str, Any]:
    """Run the deterministic JUDAH pipeline used by Django APIs/webhooks."""
    supervisor = SalomaoSupervisorAgent(
        session_id=os.getenv("AGENTOS_SESSION_ID", "agentos-local"),
        user_metadata=_agentos_user_metadata(),
        db=agentos_db,
    )
    response = supervisor.run_pipeline(message)
    return response.model_dump(mode="json")


def build_agentos_supervisor_pipeline(_request_context):
    """Build a test agent that exposes the deterministic pipeline as a tool."""
    pipeline_tool = Function.from_callable(run_salomao_supervisor_pipeline)
    pipeline_tool.show_result = True
    pipeline_tool.stop_after_tool_call = True

    return Agent(
        id="salomao-supervisor-pipeline",
        name="Salomao Supervisor Pipeline",
        model=build_primary_model(),
        db=agentos_db,
        description="AgentOS smoke-test wrapper for the deterministic Heimdall -> SalomaoChat pipeline.",
        instructions=[
            "Always call the `run_salomao_supervisor_pipeline` tool with the user's message.",
            "Return the tool result exactly as structured JSON.",
        ],
        tools=[pipeline_tool],
        tool_choice={"type": "function", "function": {"name": "run_salomao_supervisor_pipeline"}},
        markdown=False,
        debug_mode=False,
        telemetry=False,
    )


agent_os = AgentOS(
    id="judah-agent-os",
    name="JUDAH AgentOS",
    description="Local AgentOS runtime for JUDAH AI support agents.",
    db=agentos_db,
    agents=[
        salomao_agent,
        heimdall_agent,
        AgentFactory(
            id="heimdall-triage",
            name="Heimdall Triage",
            description="Typed Heimdall triage agent used by the Supervisor before every SalomaoChat draft.",
            db=agentos_db,
            factory=build_agentos_heimdall,
        ),
        AgentFactory(
            id="salomao-chat",
            name="Salomao Chat",
            description="Internal adapter agent that calls the external Salomao v1 chat service.",
            db=agentos_db,
            factory=build_agentos_salomao_chat,
        ),
        AgentFactory(
            id="salomao-supervisor-pipeline",
            name="Salomao Supervisor Pipeline",
            description="Smoke-test agent that runs the deterministic Django/API pipeline from AgentOS.",
            db=agentos_db,
            factory=build_agentos_supervisor_pipeline,
        ),
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
    agent_os.serve(
        app="apps.ai_agents.agent_os:app",
        host=os.getenv("AGENTOS_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENTOS_PORT", "7777")),
        reload=True,
    )
