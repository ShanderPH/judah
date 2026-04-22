#!/usr/bin/env python3
"""Teste E2E isolado: KnowledgeRagAgent + Pinecone real.

Valida a integração RAG sem carregar o Django ORM.
Usa python-dotenv para carregar credenciais do .env na raiz do projeto.

Usage:
    python scripts/test_rag_pinecone_real.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — deve vir ANTES de qualquer import do projeto
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ---------------------------------------------------------------------------
# Carrega variáveis de ambiente via dotenv (sem Django)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv(project_root / ".env")
    print("[.env] Variáveis carregadas via python-dotenv")
except ImportError:
    print("[.env] python-dotenv não instalado — usando variáveis do ambiente do SO")

# ---------------------------------------------------------------------------
# Mínimo de vars para que base.py (Django settings) não quebre na importação.
# O KnowledgeRagAgent usa apenas os env vars do Pinecone e OpenAI diretamente.
# ---------------------------------------------------------------------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-rag-test")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-for-rag-test")
os.environ.setdefault("DJANGO_DEBUG", "True")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# Inicializa Django (necessário por causa do BaseInChurchAgent)
try:
    import django
    django.setup()
    print("[Django] Setup concluído\n")
except Exception as exc:
    print(f"[Django] Falha no setup: {exc}")
    print("  O agente pode falhar ao inicializar o RedisDb.\n")

# ---------------------------------------------------------------------------
# Ativa logging do Agno em nível DEBUG para ver as tool calls do Pinecone
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
# Silencia logs barulhentos de bibliotecas externas
for noisy in ("httpx", "httpcore", "openai", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Verificações pré-voo
# ---------------------------------------------------------------------------

def preflight_checks() -> bool:
    """Verifica dependências e credenciais antes de instanciar o agente."""
    print("=" * 64)
    print("PRÉ-VÔO: Verificando dependências e credenciais")
    print("=" * 64)

    ok = True

    # Agno
    try:
        import agno
        version = getattr(agno, "__version__", "?")
        print(f"  [OK] agno {version}")
    except ImportError:
        print("  [FAIL] agno não instalado — pip install agno")
        ok = False

    # Pinecone
    try:
        import pinecone
        version = getattr(pinecone, "__version__", "?")
        print(f"  [OK] pinecone {version}")
        if version and int(version.split(".")[0]) >= 6:
            print(f"  [WARN] Pinecone v{version} pode ser incompatível com Agno 2.5. Use v5.4.2")
    except ImportError:
        print("  [FAIL] pinecone não instalado — pip install pinecone==5.4.2")
        ok = False

    # OpenAI
    try:
        import openai
        print("  [OK] openai instalado")
    except ImportError:
        print("  [FAIL] openai não instalado")
        ok = False

    # Credenciais obrigatórias
    creds = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "PINECONE_API_KEY": os.getenv("PINECONE_API_KEY"),
        "PINECONE_INDEX_NAME": os.getenv("PINECONE_INDEX_NAME"),
    }
    print()
    for key, value in creds.items():
        if value:
            masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
            print(f"  [OK] {key} = {masked}")
        else:
            print(f"  [FAIL] {key} não definido")
            ok = False

    # Credencial opcional
    host = os.getenv("PINECONE_HOST")
    if host:
        print(f"  [OK] PINECONE_HOST = {host[:40]}...")
    else:
        print("  [INFO] PINECONE_HOST não definido (opcional — Pinecone usará DNS padrão)")

    print()
    return ok


# ---------------------------------------------------------------------------
# Teste principal
# ---------------------------------------------------------------------------

async def run_rag_test() -> bool:
    """Instancia o KnowledgeRagAgent e faz uma query real ao Pinecone."""
    from apps.ai_agents.agents.rag import KnowledgeRagAgent

    session_id = f"rag-e2e-test-{os.getpid()}"
    user_metadata = {
        "user_id": 0,
        "username": "test_e2e",
        "email": "test@inchurch.com.br",
        "church_id": "test-church-001",
    }

    # --- Instanciação ---
    print("=" * 64)
    print("FASE 1: Instanciando KnowledgeRagAgent")
    print("=" * 64)

    t0 = time.monotonic()
    try:
        agent = KnowledgeRagAgent(
            session_id=session_id,
            user_metadata=user_metadata,
        )
        elapsed = time.monotonic() - t0
        print(f"  [OK] Agente instanciado em {elapsed:.2f}s")
        print(f"  Nome: {agent.name}")
        print(f"  search_knowledge: {agent.search_knowledge}")
        print(f"  Knowledge disponível: {agent.knowledge is not None}")
        print(f"  Tools: {[t.name for t in (agent.tools or [])]}")
    except Exception as exc:
        print(f"  [FAIL] Erro ao instanciar agente: {exc}")
        import traceback
        traceback.print_exc()
        return False

    # --- Query ao Pinecone ---
    question = "Como faço para alterar minha senha no portal da InChurch?"
    print()
    print("=" * 64)
    print("FASE 2: Query ao Pinecone via RAG")
    print("=" * 64)
    print(f"  Pergunta: '{question}'")
    print()
    print("  [Agno logs abaixo — observe tool calls e chunks recuperados]")
    print("-" * 64)

    t1 = time.monotonic()
    try:
        response = await agent.arun(question)
        search_latency = time.monotonic() - t1
    except Exception as exc:
        search_latency = time.monotonic() - t1
        print(f"\n  [FAIL] Erro na execução ({search_latency:.2f}s): {exc}")
        import traceback
        traceback.print_exc()
        return False

    # --- Resultado ---
    print("-" * 64)
    print()
    print("=" * 64)
    print("FASE 3: Resultado")
    print("=" * 64)

    content = None
    if hasattr(response, "content"):
        content = response.content
    elif isinstance(response, str):
        content = response
    else:
        content = str(response)

    print("\n  RESPOSTA DO AGENTE:\n")
    print(content or "(sem conteúdo)")

    print()
    print("=" * 64)
    print("RELATÓRIO DE PERFORMANCE")
    print("=" * 64)
    print(f"  Latência total (instanciação + LLM + Pinecone): {search_latency:.2f}s")

    latency_ok = search_latency < 30
    print(f"  Latência da busca Pinecone: {'< 30s (OK)' if latency_ok else '> 30s (LENTO)'}")

    if content and ("documentação" in content.lower() or "base" in content.lower() or "inchurch" in content.lower()):
        print("  Conteúdo: Parece ter usado a base de conhecimento")
    else:
        print("  Conteúdo: Resposta genérica (pode indicar índice vazio ou sem match)")

    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print()
    print("=" * 64)
    print("  TESTE E2E — KnowledgeRagAgent + Pinecone Real")
    print("  Projeto: Judah / Sistema Salomão")
    print("=" * 64)
    print()

    if not preflight_checks():
        print("[ABORTADO] Corrija os itens acima antes de continuar.")
        return 1

    success = asyncio.run(run_rag_test())

    print()
    print("=" * 64)
    if success:
        print("  RESULTADO FINAL: SUCESSO")
    else:
        print("  RESULTADO FINAL: FALHA")
    print("=" * 64)
    print()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
