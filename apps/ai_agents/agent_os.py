"""Local AgentOS entrypoint for independent JUDAH AI agents."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup(set_prefix=False)

from agno.agent.factory import AgentFactory  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402

from apps.ai_agents.agents.salomao import salomao_agent  # noqa: E402
from apps.ai_agents.agents.salomao_chat import SalomaoChatAgent  # noqa: E402

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


def build_agentos_salomao_chat(_request_context: Any) -> SalomaoChatAgent:
    """Build the standalone Salomao adapter for direct AgentOS tests."""
    return SalomaoChatAgent(
        session_id=os.getenv("AGENTOS_SESSION_ID", "agentos-local"),
        user_metadata=_agentos_user_metadata(),
        db=agentos_db,
    )


agent_os = AgentOS(
    id="judah-agent-os",
    name="JUDAH AgentOS",
    description="Local runtime for independent JUDAH AI capabilities.",
    db=agentos_db,
    agents=[
        salomao_agent,
        AgentFactory(
            id="salomao-chat",
            name="Salomao Chat",
            description="Adapter agent for the standalone Salomao service.",
            db=agentos_db,
            factory=build_agentos_salomao_chat,
        ),
    ],
    teams=[],
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
