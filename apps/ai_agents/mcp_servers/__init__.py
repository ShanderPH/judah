"""MCP Servers module for ai_agents app.

Servidores MCP (Model Context Protocol) que expõem ferramentas externas
para uso pelos agentes Agno do sistema Salomão.
"""

from apps.ai_agents.mcp_servers.hubspot_server import mcp as hubspot_mcp

__all__ = ["hubspot_mcp"]
