import os
import subprocess
import sys
import time
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Testa HelpdeskActionAgent com MCP HubSpot"

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("TESTE: HelpdeskActionAgent + MCP HubSpot")
        self.stdout.write("=" * 60)

        # Verifica token
        token = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
        if not token:
            self.stdout.write(self.style.ERROR("HUBSPOT_ACCESS_TOKEN nÃ£o configurado!"))
            return
        self.stdout.write(f"Token: {token[:10]}...")

        # Prepara comando MCP
        project_root = Path(__file__).parent.parent.parent.parent
        server_path = project_root / "apps" / "ai_agents" / "mcp_servers" / "hubspot_server.py"
        command = [sys.executable, str(server_path)]

        # Testa subprocesso
        self.stdout.write("\n[1] Testando servidor MCP...")
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            time.sleep(2)
            if proc.poll() is None:
                self.stdout.write(self.style.SUCCESS("  Servidor MCP iniciado!"))
                proc.terminate()
            else:
                _, stderr = proc.communicate()
                self.stdout.write(self.style.ERROR(f"  Falhou: {stderr[:200]}"))
                return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Erro: {e}"))
            return

        # Testa imports
        self.stdout.write("\n[2] Testando imports...")
        try:
            from agno.tools.mcp import MCPTools

            from apps.ai_agents.agents.action import HelpdeskActionAgent, MCPServerConfig  # noqa: F401

            self.stdout.write(self.style.SUCCESS("  Imports OK"))
        except ImportError as e:
            self.stdout.write(self.style.ERROR(f"  Erro: {e}"))
            return

        # Instancia MCP tools
        self.stdout.write("\n[3] Instanciando MCPTools...")
        try:
            mcp_tool = MCPTools(command=command, transport="stdio", timeout_seconds=30)
            self.stdout.write(self.style.SUCCESS("  MCPTools OK"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Erro: {e}"))
            return

        # Instancia agente
        self.stdout.write("\n[4] Instanciando HelpdeskActionAgent...")
        try:
            agent = HelpdeskActionAgent(
                session_id=f"test-{os.getpid()}",
                user_metadata={"user_id": 999, "email": "test@test.com"},
                mcp_tools=[mcp_tool],
            )
            self.stdout.write(self.style.SUCCESS(f"  Agente: {agent.name}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Erro: {e}"))
            return

        self.stdout.write(self.style.SUCCESS("\nâœ“ Teste concluÃ­do!"))
