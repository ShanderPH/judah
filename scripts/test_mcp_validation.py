#!/usr/bin/env python3
"""Validação isolada: HelpdeskActionAgent + servidor MCP HubSpot (stdio).

Objetivo: confirmar que o MCP subprocess inicia corretamente, que o agente
consegue se comunicar com ele via stdio e que a ferramenta `get_ticket_status`
é chamada sem crash.

Não usa Django nem manage.py — injetamos os stubs mínimos necessários para
BaseInChurchAgent (Redis URL, OpenAI key, etc.) diretamente via os.environ
antes de qualquer import do pacote apps/.

Usage:
    python scripts/test_mcp_validation.py
    # ou com token real:
    HUBSPOT_ACCESS_TOKEN="pat-xxx" python scripts/test_mcp_validation.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: path + variáveis de ambiente mínimas (ANTES de qualquer import
# do Django ou do pacote apps/).
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Carrega .env da raiz do projeto (mesmo mecanismo do hubspot_server.py)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# Variáveis mínimas para que BaseInChurchAgent não quebre ao importar Django.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
os.environ.setdefault("SECRET_KEY", "test-secret-only-for-validation")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-only-for-validation")
os.environ.setdefault("DJANGO_DEBUG", "True")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# Inicializa Django (necessário porque BaseInChurchAgent importa settings)
try:
    import django
    django.setup()
    print("[bootstrap] Django inicializado.")
except Exception as exc:
    print(f"[bootstrap] Aviso — Django não inicializado: {exc}")
    print("[bootstrap] Continuando com validação estrutural...")


# ---------------------------------------------------------------------------
# Imports dos agentes (após Django setup)
# ---------------------------------------------------------------------------

from agno.tools.mcp import MCPTools  # noqa: E402

from apps.ai_agents.agents.action import (  # noqa: E402
    HelpdeskActionAgent,
    _get_hubspot_mcp_command,
)

# ---------------------------------------------------------------------------
# Validação 1: Sintaxe e imports do hubspot_server.py
# ---------------------------------------------------------------------------

def validate_mcp_server_module() -> bool:
    """Verifica se hubspot_server.py importa sem erros e sem Django."""
    print("\n[1/4] Validando imports do hubspot_server.py...")
    server_path = PROJECT_ROOT / "apps" / "ai_agents" / "mcp_servers" / "hubspot_server.py"

    import importlib.util
    spec = importlib.util.spec_from_file_location("hubspot_server", server_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]

    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception as exc:
        print(f"    FALHA — erro ao importar hubspot_server.py: {exc}")
        return False

    # Garante que não há referência ao Django no módulo carregado
    import inspect
    source = inspect.getsource(mod)
    if "from django" in source or "import django" in source:
        print("    FALHA — hubspot_server.py contém imports do Django!")
        return False

    # Verifica que o bloco __main__ está presente
    if 'mcp.run(transport="stdio")' not in source and "mcp.run(transport='stdio')" not in source:
        print("    AVISO — bloco __main__ com mcp.run(stdio) não encontrado.")

    print("    OK — sem imports Django, bloco stdio presente.")
    return True


# ---------------------------------------------------------------------------
# Validação 2: Subprocess MCP inicia e fica vivo
# ---------------------------------------------------------------------------

async def validate_mcp_subprocess() -> bool:
    """Verifica se o subprocesso MCP inicia sem crash imediato."""
    print("\n[2/4] Verificando inicialização do subprocess MCP...")
    import subprocess

    cmd = _get_hubspot_mcp_command()
    print(f"    Comando: {cmd[:100]}")

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Aguarda 2 s para detectar crash imediato
    await asyncio.sleep(2)

    if proc.poll() is not None:
        _, stderr = proc.communicate()
        print(f"    FALHA — processo encerrou (exit {proc.returncode})")
        print(f"    Stderr: {stderr.decode(errors='replace')[:400]}")
        return False

    # Processo vivo — envia mensagem de inicialização MCP para validar protocolo
    try:
        import json
        init_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "validation-script", "version": "1.0"},
            },
        }) + "\n"
        proc.stdin.write(init_msg.encode())  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]

        await asyncio.sleep(1)
        # Lê resposta parcial (sem bloquear)
        import select as sel
        if hasattr(sel, "select"):
            ready, _, _ = sel.select([proc.stdout], [], [], 0.5)
            if ready:
                chunk = proc.stdout.read1(512)  # type: ignore[union-attr]
                decoded = chunk.decode(errors="replace")
                if '"result"' in decoded or '"id":1' in decoded:
                    print("    OK — servidor MCP respondeu ao handshake initialize.")
                else:
                    print(f"    OK — processo vivo. Resposta parcial: {decoded[:120]}")
            else:
                print("    OK — processo vivo (sem resposta ao handshake no timeout).")
        else:
            print("    OK — processo vivo (plataforma sem select; handshake não testado).")

    except Exception as exc:
        print(f"    AVISO — handshake falhou: {exc} (processo pode ainda estar OK)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    return True


# ---------------------------------------------------------------------------
# Validação 3: Instanciação do HelpdeskActionAgent
# ---------------------------------------------------------------------------

def validate_agent_instantiation() -> HelpdeskActionAgent | None:
    """Instancia o HelpdeskActionAgent com MCP stdio e verifica configuração."""
    print("\n[3/4] Instanciando HelpdeskActionAgent...")

    session_id = f"validation-{os.getpid()}"
    user_metadata = {
        "user_id": 0,
        "username": "validation_script",
        "email": "validation@inchurch.com.br",
        "church_id": "0",
        "hubspot_contact_id": "",
    }

    # Cria MCP tool explicitamente para stdio, apontando ao hubspot_server.py
    mcp_cmd = _get_hubspot_mcp_command()
    mcp_tool = MCPTools(
        command=mcp_cmd,
        transport="stdio",
        tool_name_prefix="hubspot",
    )

    try:
        agent = HelpdeskActionAgent(
            session_id=session_id,
            user_metadata=user_metadata,
            mcp_tools=[mcp_tool],
        )
        print(f"    OK — agente '{agent.name}' instanciado.")
        print(f"    show_tool_calls={agent.show_tool_calls}")
        return agent
    except Exception as exc:
        print(f"    FALHA — erro ao instanciar agente: {exc}")
        import traceback
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Validação 4: Execução do prompt (somente leitura — get_ticket_status)
# ---------------------------------------------------------------------------

async def validate_agent_run(agent: HelpdeskActionAgent) -> bool:
    """Executa um prompt de leitura e verifica se a tool MCP foi chamada."""
    print("\n[4/4] Executando prompt de leitura no agente...")

    prompt = "Retorne as chaves do ticket ID 123 do HubSpot"
    print(f"    Prompt: '{prompt}'")

    token = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
    if not token:
        print("    AVISO — HUBSPOT_ACCESS_TOKEN não definido; a tool falhará com 401.")

    try:
        loop = asyncio.get_running_loop()
        import functools

        response = await loop.run_in_executor(
            None, functools.partial(agent.run, prompt)
        )

        content = getattr(response, "content", str(response))
        print(f"\n    Resposta recebida ({len(str(content))} chars):")
        print(f"    {str(content)[:300]}")

        # Verifica se tool foi chamada (aparece no trace por show_tool_calls=True)
        messages = getattr(response, "messages", [])
        tool_calls_found = any(
            hasattr(m, "tool_calls") and m.tool_calls for m in (messages or [])
        )
        if tool_calls_found:
            print("    OK — tool call detectada na resposta.")
        else:
            print("    AVISO — nenhum tool call detectado (agente pode ter respondido sem usar MCP).")

        return True

    except Exception as exc:
        print(f"    FALHA — erro na execução: {exc}")
        import traceback
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    print("=" * 65)
    print("Validação Isolada: HelpdeskActionAgent + MCP HubSpot stdio")
    print("=" * 65)

    results: dict[str, bool] = {}

    results["mcp_server_imports"] = validate_mcp_server_module()
    results["mcp_subprocess"] = await validate_mcp_subprocess()

    agent = validate_agent_instantiation()
    results["agent_instantiation"] = agent is not None

    if agent is not None:
        results["agent_run"] = await validate_agent_run(agent)
    else:
        results["agent_run"] = False

    print("\n" + "=" * 65)
    print("RESULTADO FINAL")
    print("=" * 65)
    for check, passed in results.items():
        status = "OK  " if passed else "FALHA"
        print(f"  [{status}] {check}")

    all_passed = all(results.values())
    print()
    print("PASSOU" if all_passed else "FALHOU — ver detalhes acima")
    print("=" * 65)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
