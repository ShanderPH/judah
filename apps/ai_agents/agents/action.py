"""Read-only protocol lookup agent and legacy MCP connection helpers.

MCP connector builders remain available for integrations outside the customer
assistant. The agent itself deliberately receives only ``GetTicketInfo`` so an
LLM cannot discover or invoke mutating external tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from agno.tools.mcp import MCPTools

from apps.ai_agents.agents.base import BaseInChurchAgent

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuração dos Servidores MCP
# ---------------------------------------------------------------------------


@dataclass
class MCPServerConfig:
    """Configuração de um servidor MCP externo.

    Args:
        name: Nome lógico do servidor (para logs e rastreabilidade).
        url: URL do servidor SSE/HTTP FastMCP (transport='sse') ou None se
            o servidor for iniciado via `command`.
        command: Comando para iniciar o servidor MCP em subprocesso (transport='stdio').
        transport: Protocolo de transporte ('sse', 'stdio' ou 'streamable-http').
        enabled: Flag para desativar um servidor sem removê-lo da config.
        env: Variáveis de ambiente para o subprocesso MCP.
    """

    name: str
    url: str | None = None
    command: str | None = None
    transport: Literal["stdio", "sse", "streamable-http"] = "sse"
    enabled: bool = True
    env: dict[str, str] = field(default_factory=dict)


def _get_hubspot_mcp_command() -> str:
    """Retorna o comando para iniciar o servidor MCP HubSpot via stdio.

    Usa `python` como executável (obrigatório pelo Agno 2.5 — apenas executáveis
    da lista permitida são aceitos: python, python3, node, etc.) e o caminho
    absoluto para o arquivo do servidor.

    Returns:
        Comando completo para executar o servidor como subprocesso.
    """
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent.parent
    server_path = project_root / "apps" / "ai_agents" / "mcp_servers" / "hubspot_server.py"

    return f'python "{server_path}"'


# ---------------------------------------------------------------------------
# Configuração padrão dos servidores MCP.
# O servidor HubSpot MCP usa transporte stdio (subprocesso local) por padrão.
# ---------------------------------------------------------------------------
DEFAULT_MCP_SERVERS: list[MCPServerConfig] = [
    MCPServerConfig(
        name="hubspot",
        command=_get_hubspot_mcp_command(),
        transport="stdio",
        enabled=False,
    ),
    MCPServerConfig(
        name="jira_mcp",
        # Ex: url="http://localhost:8002/sse"
        url=None,
        transport="sse",
        enabled=False,
    ),
    # Central de Ajuda InChurch — endpoint próprio para publicação/atualização
    # de artigos e consulta a tickets internos. Placeholder: será ativado
    # quando o servidor MCP da Central estiver provisionado.
    MCPServerConfig(
        name="helpdesk_api",
        # Ex: url="https://helpdesk.inchurch.com.br/mcp/sse"
        url=None,
        transport="sse",
        enabled=False,
    ),
]


def connect_helpdesk_api_mcp(url: str, *, timeout_seconds: int = 30) -> MCPTools:
    """Cria um cliente MCP conectado à Central de Ajuda InChurch.

    Expõe ferramentas como `create_ticket`, `update_ticket`, `get_ticket`,
    `list_articles` do Helpdesk próprio da InChurch. Pareia com o HubSpot
    para sincronizar estados de atendimento.
    """
    logger.info("mcp_connect_helpdesk_api", url=url)
    return MCPTools(
        url=url,
        transport="sse",
        timeout_seconds=timeout_seconds,
        tool_name_prefix="helpdesk",
    )


# ---------------------------------------------------------------------------
# Helpers de conexão MCP
# ---------------------------------------------------------------------------


def connect_hubspot_mcp(url: str, *, timeout_seconds: int = 30) -> MCPTools:
    """Cria um cliente MCP conectado ao servidor FastMCP do HubSpot.

    Expõe ferramentas como `create_ticket`, `update_contact`, `get_deal`, etc.
    O servidor MCP encapsula a autenticação OAuth do HubSpot internamente.

    Args:
        url: URL do servidor SSE FastMCP do HubSpot.
        timeout_seconds: Timeout de conexão em segundos.

    Returns:
        MCPTools configurado para o servidor HubSpot.
    """
    logger.info("mcp_connect_hubspot", url=url)
    return MCPTools(
        url=url,
        transport="sse",
        timeout_seconds=timeout_seconds,
        tool_name_prefix="hubspot",
    )


def connect_jira_mcp(url: str, *, timeout_seconds: int = 30) -> MCPTools:
    """Cria um cliente MCP conectado ao servidor FastMCP do Jira.

    Expõe ferramentas como `create_issue`, `search_issues`, `add_comment`, etc.

    Args:
        url: URL do servidor SSE FastMCP do Jira.
        timeout_seconds: Timeout de conexão em segundos.

    Returns:
        MCPTools configurado para o servidor Jira.
    """
    logger.info("mcp_connect_jira", url=url)
    return MCPTools(
        url=url,
        transport="sse",
        timeout_seconds=timeout_seconds,
        tool_name_prefix="jira",
    )


def build_mcp_tools_from_config(
    configs: list[MCPServerConfig] | None = None,
) -> list[MCPTools]:
    """Constrói a lista de MCPTools a partir da configuração de servidores.

    Ignora servidores desabilitados ou sem URL/command configurados.

    Args:
        configs: Lista de MCPServerConfig; usa DEFAULT_MCP_SERVERS se None.

    Returns:
        Lista de MCPTools prontos para serem passados ao Agent.
    """
    configs = configs or DEFAULT_MCP_SERVERS
    tools: list[MCPTools] = []

    for cfg in configs:
        if not cfg.enabled:
            logger.debug("mcp_server_disabled", name=cfg.name)
            continue
        if not cfg.url and not cfg.command:
            logger.warning("mcp_server_no_endpoint", name=cfg.name)
            continue

        tool = MCPTools(
            url=cfg.url,
            command=cfg.command,
            transport=cfg.transport,
            tool_name_prefix=cfg.name,
            env=cfg.env if cfg.env else None,
        )
        tools.append(tool)
        logger.info("mcp_server_registered", name=cfg.name, transport=cfg.transport)

    return tools


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------

_ACTION_INSTRUCTIONS = [
    "Você é o HelpdeskAction, restrito à consulta somente leitura do status de protocolos InChurch.",
    "Use apenas a ferramenta de consulta de ticket/protocolo.",
    "Nunca crie, atualize, exclua, atribua ou mova tickets, contatos, negócios, conversas, artigos ou issues.",
    "Nunca execute estorno, cancelamento, emissão ou alteração em nome do cliente.",
    "Se o pedido não for uma consulta de status de protocolo, não use ferramenta e devolva o caso ao Supervisor para orientação pela documentação.",
    "Nunca exponha tokens, chaves de API ou dados sensíveis na resposta.",
]


class HelpdeskActionAgent(BaseInChurchAgent):
    """Expose only read-only ticket/protocol lookup to the model.

    Args:
        session_id: Identificador da sessão.
        user_metadata: Dados do usuário sem ORM.
        mcp_tools: Legacy connector input. Never exposed to this agent.
        extra_mcp_configs: Legacy connector configuration input.
    """

    def __init__(
        self,
        session_id: str,
        user_metadata: dict[str, Any],
        mcp_tools: list[MCPTools] | None = None,
        extra_mcp_configs: list[MCPServerConfig] | None = None,
        db: Any | None = None,
    ) -> None:
        # Constrói lista de ferramentas MCP — fallback para config padrão.
        if mcp_tools is None:
            configs = DEFAULT_MCP_SERVERS + (extra_mcp_configs or [])
            mcp_tools = build_mcp_tools_from_config(configs)

        # The explicit local toolkit is the complete allowed tool surface.
        static_tools = _build_static_fallback_tools()

        # MCPs externos podem expor ferramentas mutáveis. O agente recebe
        # somente o toolkit local de consulta, com superfície conhecida.
        all_tools = static_tools
        kwargs: dict[str, Any] = {}
        if db is not None:
            kwargs["db"] = db

        super().__init__(
            session_id=session_id,
            user_metadata=user_metadata,
            name="HelpdeskAction",
            instructions=_ACTION_INSTRUCTIONS,
            tools=all_tools,
            add_history_to_context=False,
            **kwargs,
        )

        self._agent_logger.info(
            "action_agent_tools_registered",
            mcp_count=len(mcp_tools),
            static_count=len(static_tools),
        )


def _build_static_fallback_tools() -> list[Any]:
    """Return only the read-only ticket/protocol lookup toolkit."""
    from apps.ai_agents.agents.tools.hubspot_tools import GetTicketInfo

    return [GetTicketInfo()]
