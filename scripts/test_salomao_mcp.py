#!/usr/bin/env python3
"""Script de teste isolado para HelpdeskActionAgent + MCP.

Este script testa o agente de ação de forma isolada, sem Django Ninja
ou Supervisor. Útil para debugar problemas com o servidor MCP HubSpot.

Usage:
    export HUBSPOT_ACCESS_TOKEN="seu_token_aqui"
    python scripts/test_salomao_mcp.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Adiciona o projeto ao path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Variáveis de ambiente mínimas
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
if not os.getenv("HUBSPOT_ACCESS_TOKEN"):
    os.environ["HUBSPOT_ACCESS_TOKEN"] = "dummy_token_for_testing"
if not os.getenv("SECRET_KEY"):
    os.environ["SECRET_KEY"] = "test-secret-key"
if not os.getenv("DJANGO_SECRET_KEY"):
    os.environ["DJANGO_SECRET_KEY"] = "test-secret-key"
if not os.getenv("DJANGO_DEBUG"):
    os.environ["DJANGO_DEBUG"] = "True"

# Tenta inicializar Django
try:
    import django
    django.setup()
    DJANGO_OK = True
except Exception as e:
    DJANGO_OK = False
    print(f"⚠ Django não inicializado: {e}")
    print("  Continuando com testes básicos...")


async def test_helpdesk_agent_with_mcp():
    """Testa o HelpdeskActionAgent com ferramentas MCP do HubSpot."""
    print("=" * 60)
    print("TESTE: HelpdeskActionAgent + MCP HubSpot")
    print("=" * 60)

    # Configuração MCP
    mcp_config = MCPServerConfig(
        name="hubspot",
        command=f'{sys.executable} "{project_root}/apps/ai_agents/mcp_servers/hubspot_server.py"',
        transport="stdio",
        enabled=True,
    )

    print("\n[1] Configuração MCP:")
    print(f"    Nome: {mcp_config.name}")
    print(f"    Transport: {mcp_config.transport}")
    print(f"    Comando: {mcp_config.command[:80]}...")

    # Instancia MCP tools
    print("\n[2] Conectando ao servidor MCP...")
    mcp_tools: list[MCPTools] = []
    stderr_logs: list[str] = []

    try:
        # Configura captura de stderr do subprocesso
        import subprocess

        # Testa se o servidor inicia sem erros
        process = subprocess.Popen(
            mcp_config.command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Aguarda brevemente e captura stderr inicial
        await asyncio.sleep(2)

        # Verifica se processo ainda está vivo
        if process.poll() is None:
            print("    ✓ Servidor MCP iniciado (processo ativo)")
            process.terminate()
            try:
                _, stderr = process.communicate(timeout=2)
                if stderr:
                    stderr_logs.append(stderr[:500])
                    print(f"    ! Stderr: {stderr[:200]}...")
            except subprocess.TimeoutExpired:
                process.kill()
                print("    ! Timeout ao ler stderr")
        else:
            returncode = process.returncode
            _, stderr = process.communicate()
            stderr_logs.append(stderr[:500])
            print(f"    ✗ Servidor MCP falhou ao iniciar (exit {returncode})")
            print(f"    ! Stderr: {stderr[:500]}")

        # Cria MCP Tools
        mcp_tool = MCPTools(
            command=mcp_config.command,
            transport="stdio",  # type: ignore[arg-type]
            timeout_seconds=30,
        )
        mcp_tools.append(mcp_tool)
        print("    ✓ MCPTools instanciado")

    except Exception as e:
        print(f"    ✗ Erro ao conectar MCP: {e}")
        import traceback

        traceback.print_exc()
        return False

    # Instancia o agente
    print("\n[3] Instanciando HelpdeskActionAgent...")
    session_id = f"test-{os.getpid()}"
    user_metadata = {
        "user_id": 999,
        "username": "test_user",
        "email": "test@example.com",
        "church_id": "123",
    }

    try:
        agent = HelpdeskActionAgent(
            session_id=session_id,
            user_metadata=user_metadata,
            mcp_tools=mcp_tools,
        )
        print(f"    ✓ Agente instanciado: {agent.name}")
        print(f"    ✓ Session ID: {session_id}")
    except Exception as e:
        print(f"    ✗ Erro ao instanciar agente: {e}")
        import traceback

        traceback.print_exc()
        return False

    # Executa o teste
    print("\n[4] Executando prompt de teste...")
    prompt = "Qual o status do ticket 12345 no HubSpot?"
    print(f"    Prompt: '{prompt}'")

    try:
        # Agno Agent pode ser sync ou async dependendo da configuração
        print("    Enviando para o agente...")

        # Tenta executar de forma assíncrona
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: agent.run(prompt),
        )

        print("\n[5] Resposta recebida:")
        print(f"    {response}")

        if hasattr(response, "content"):
            print(f"\n    Conteúdo: {response.content}")
        if hasattr(response, "tools"):
            print(f"    Ferramentas usadas: {response.tools}")

        return True

    except Exception as e:
        print(f"    ✗ Erro na execução: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # Logs de debug
        if stderr_logs:
            print("\n[DEBUG] Logs do subprocesso MCP:")
            for log in stderr_logs:
                print(f"    {log[:300]}")


async def main():
    """Ponto de entrada principal."""
    print("\n" + "=" * 60)
    print("Iniciando teste isolado do HelpdeskActionAgent + MCP")
    print("=" * 60)

    # Verifica dependências
    print("\n[0] Verificando dependências...")
    try:
        import agno

        print(f"    ✓ agno: {agno.__version__ if hasattr(agno, '__version__') else 'installed'}")
    except ImportError:
        print("    ✗ agno não instalado")
        return 1

    try:
        import mcp

        print("    ✓ mcp: instalado")
    except ImportError:
        print("    ✗ mcp não instalado (pip install mcp)")
        return 1

    try:
        import httpx

        print("    ✓ httpx: instalado")
    except ImportError:
        print("    ✗ httpx não instalado")
        return 1

    # Verifica token
    token = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
    if not token or token == "dummy_token_for_testing":
        print("\n⚠ HUBSPOT_ACCESS_TOKEN não configurado!")
        print("   Defina a variável de ambiente ou o teste usará token dummy.")
        print("   export HUBSPOT_ACCESS_TOKEN='seu_token_aqui'")

    # Executa teste
    success = await test_helpdesk_agent_with_mcp()

    print("\n" + "=" * 60)
    if success:
        print("✓ TESTE CONCLUÍDO COM SUCESSO")
    else:
        print("✗ TESTE FALHOU")
    print("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
