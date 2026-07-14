"""HelpdeskActionAgent — Executor de ações externas via MCP e APIs diretas.

Decisão arquitetural: este agente recebe ferramentas **dinamicamente** de
servidores FastMCP (HubSpot, Jira, n8n), eliminando o acoplamento estático
entre o código do agente e as APIs externas. Cada servidor MCP expõe suas
ferramentas via o protocolo Model Context Protocol; o Agno as descobre em
runtime e as injecta no contexto do LLM.

Os métodos `connect_*` são assinaturas/placeholders prontos para receber as
URLs/comandos reais dos servidores MCP quando provisionados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from agno.tools.mcp import MCPTools
from django.conf import settings

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
        enabled=True,
    ),
    MCPServerConfig(
        name="jira_mcp",
        # Ex: url="http://localhost:8002/sse"
        url=None,
        transport="sse",
        enabled=False,
    ),
    MCPServerConfig(
        name="n8n_webhook_mcp",
        # Ex: url="https://n8n.inchurch.com.br/mcp/sse"
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


def connect_n8n_mcp(url: str, *, timeout_seconds: int = 45) -> MCPTools:
    """Cria um cliente MCP conectado ao servidor FastMCP do n8n.

    Expõe workflows n8n como ferramentas (ex: `trigger_onboarding_workflow`,
    `send_whatsapp_notification`, `create_support_task`).

    Args:
        url: URL do servidor SSE FastMCP do n8n.
        timeout_seconds: Timeout de conexão (maior porque workflows n8n podem
            demorar para responder).

    Returns:
        MCPTools configurado para o servidor n8n.
    """
    logger.info("mcp_connect_n8n", url=url)
    return MCPTools(
        url=url,
        transport="sse",
        timeout_seconds=timeout_seconds,
        tool_name_prefix="n8n",
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
    "Você é o HelpdeskAction — agente de ações do helpdesk InChurch.",
    "Você é acionado pelo Supervisor Salomão quando a rota do Heimdall "
    "requer uma AÇÃO concreta no HubSpot (tickets/contatos/negócios), "
    "na Central de Ajuda InChurch (tickets internos/artigos), no Jira "
    "(issues) ou em workflows n8n.",
    "Use o contexto estruturado do Heimdall (rota, prioridade, tags, "
    "dados_faltantes) para decidir quais ferramentas MCP acionar.",
    "Se `dados_faltantes` não estiver vazio, peça ao Supervisor para "
    "coletar esses dados antes de executar ações irreversíveis.",
    "Sempre confirme os dados antes de criar ou modificar um recurso externo.",
    "Priorize a idempotência: verifique se o recurso já existe antes de criar um novo.",
    "FECHAMENTO DE LOOP (OBRIGATÓRIO): após classificar a rota e preparar a "
    "resposta, você DEVE utilizar a ferramenta `hubspot_update_ticket` do "
    "HubSpot para atualizar o ticket com sua resposta (`reply_note`) e o novo "
    "status do pipeline (`pipeline_stage`). Não encerre a execução sem "
    "confirmar a atualização na API do CRM — isto é crítico para que o ticket "
    "saia da fila de triagem e o contato receba o retorno.",
    "Padrão de chamada: `hubspot_update_ticket(ticket_id=<id>, "
    "pipeline_stage='<novo_stage>', reply_note='<texto_da_resposta>')`. "
    f"No pipeline de Triagem IA, use pipeline_stage='{settings.HUBSPOT_AI_WAITING_STAGE_ID}' "
    "depois de responder e ficar aguardando o contato. "
    f"Use pipeline_stage='{settings.HUBSPOT_HUMAN_ESCALATION_STAGE_ID}' quando houver transbordo humano. "
    f"Use pipeline_stage='{settings.HUBSPOT_CLOSED_STAGE_ID}' somente quando o atendimento tiver sido "
    "explicitamente encerrado.",
    "ATENÇÃO AOS PIPELINES E ESTÁGIOS:",
    f"- Se a flag `is_off_hours` for True E houver transbordo, OBRIGATORIAMENTE atualize o ticket para "
    f"`pipeline_stage='{settings.HUBSPOT_HUMAN_ESCALATION_STAGE_ID}'` "
    f"(dentro do `pipeline='{settings.HUBSPOT_AI_TRIAGE_PIPELINE_ID}'`).",
    "- Sempre informe ao usuário o seu Protocolo de Atendimento. O Protocolo é o próprio `hubspot_ticket_id` formatado (Ex: 'Seu protocolo é #12345').",
    "- Sempre responda ao usuário (reply_note) antes de finalizar, alertando que o retorno será no próximo dia útil se for off-hours.",
    "Se a ferramenta `hubspot_update_ticket` retornar `errors` não-vazio, "
    "reporte isso explicitamente ao Supervisor na resposta final.",
    "Registre o resultado de cada ação na resposta final para auditoria.",
    "Se uma ferramenta MCP não estiver disponível, informe o Supervisor imediatamente.",
    "Nunca exponha tokens, chaves de API ou dados sensíveis na resposta.",
    "Sempre que o utilizador relatar problemas de visibilidade num evento, peça o ID e utilize a ferramenta diagnose_event_visibility.",
]


class HelpdeskActionAgent(BaseInChurchAgent):
    """Executor de ações externas via servidores FastMCP.

    Aceita ferramentas MCP dinamicamente em runtime. As ferramentas são
    descobertas via protocol handshake com os servidores MCP registrados,
    sem necessidade de alterar o código do agente quando novos servidores
    são adicionados.

    Uso típico:
        # Com servidores MCP reais:
        hubspot_tool = connect_hubspot_mcp(url=settings.HUBSPOT_MCP_URL)
        agent = HelpdeskActionAgent(
            session_id="...",
            user_metadata={...},
            mcp_tools=[hubspot_tool],
        )

        # Com configuração automática via DEFAULT_MCP_SERVERS:
        agent = HelpdeskActionAgent(session_id="...", user_metadata={...})

    Args:
        session_id: Identificador da sessão.
        user_metadata: Dados do usuário sem ORM.
        mcp_tools: Lista de MCPTools pré-configurados. Se None, usa
            `build_mcp_tools_from_config(DEFAULT_MCP_SERVERS)`.
        extra_mcp_configs: Configurações adicionais de servidores MCP para
            complementar DEFAULT_MCP_SERVERS.
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

        # Fallback estático usando Toolkits diretos enquanto MCP não está disponível.
        # Quando os servidores MCP estiverem ativos, esta lista pode ser esvaziada.
        static_tools = _build_static_fallback_tools()

        all_tools = [*mcp_tools, *static_tools]
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
    """Retorna ferramentas estáticas como fallback enquanto MCP não está ativo.

    Reutiliza os Toolkits já existentes no projeto para manter compatibilidade
    com o código legado e garantir funcionamento em ambiente de desenvolvimento.
    """
    from apps.ai_agents.agents.tools.hubspot_tools import GetTicketInfo
    from apps.ai_agents.agents.tools.jira_tools import SearchJiraIssues
    from apps.ai_agents.tools.inchurch_tools import InChurchDiagnosticsTool

    return [GetTicketInfo(), SearchJiraIssues(), InChurchDiagnosticsTool()]
