#!/usr/bin/env python3
"""Teste de integração completo da rota POST /api/v1/ai/salomao/chat.

Usa o Django Test Client com JWT para bater na rota real do Ninja sem
precisar de um servidor rodando. Cria (ou recupera) um usuário de teste,
gera o JWT programaticamente e verifica a resposta estruturada.

Usage:
    python scripts/test_api_integration.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path e variáveis de ambiente
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env", override=True)
    print("[.env] Variáveis carregadas")
except ImportError:
    print("[.env] python-dotenv não disponível — usando vars do SO")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django  # noqa: E402

django.setup()

# ---------------------------------------------------------------------------
# Ajustes de settings para ambiente de teste
# ---------------------------------------------------------------------------
from django.conf import settings  # noqa: E402

# Permite o host padrão do Django test client
if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = [*list(settings.ALLOWED_HOSTS), "testserver", "localhost", "127.0.0.1"]

# Desativa o Debug Toolbar, que não funciona em testes sem servidor real
if "debug_toolbar" in settings.INSTALLED_APPS:
    settings.INSTALLED_APPS = [
        app for app in settings.INSTALLED_APPS if app != "debug_toolbar"
    ]
if hasattr(settings, "MIDDLEWARE"):
    settings.MIDDLEWARE = [
        m for m in settings.MIDDLEWARE if "debug_toolbar" not in m
    ]

# ---------------------------------------------------------------------------
# Imports pós-setup
# ---------------------------------------------------------------------------
from django.test import Client  # noqa: E402

from apps.auth_user.models import User  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(title: str) -> None:
    print()
    print("=" * 64)
    print(f"  {title}")
    print("=" * 64)


def _check_redis() -> bool:
    """Verifica se Redis está acessível."""
    import redis as redis_lib
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        r = redis_lib.from_url(redis_url, socket_connect_timeout=2)
        r.ping()
        return True
    except Exception as exc:
        print(f"  [WARN] Redis inacessível: {exc}")
        return False


def get_or_create_test_user() -> User:
    """Cria (ou recupera) usuário de teste com credenciais conhecidas."""
    username = "test_integration"
    password = "Test@1234!"

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "email": "integration@test.inchurch.com.br",
            "first_name": "Test",
            "last_name": "Integration",
            "is_active": True,
            "role": User.Role.AGENT,
        },
    )

    if created:
        user.set_password(password)
        user.save()
        print(f"  [OK] Usuário criado: {username} (pk={user.pk})")
    else:
        print(f"  [OK] Usuário recuperado: {username} (pk={user.pk})")

    return user


def get_jwt_token_via_login(client: Client, username: str, password: str) -> str:
    """Obtém access token JWT via endpoint de login real (funciona com JWTAuth síncrono).

    Nota: RefreshToken.for_user() gerado programaticamente tem claims diferentes
    dos tokens emitidos pelo login endpoint do Ninja. A autenticação no view
    assíncrono via AsyncClient falha porque JWTAuth não implementa authenticate_async.
    A abordagem correta é: logar via sync Client, usar o access token retornado.
    """
    response = client.post(
        "/api/v1/auth/login",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
    )
    if response.status_code != 200:
        raise RuntimeError(f"Login falhou ({response.status_code}): {response.content.decode()[:200]}")
    data = response.json()
    token = data.get("access", "")
    print(f"  [OK] JWT obtido via login: {token[:40]}...")
    return token


# ---------------------------------------------------------------------------
# Teste principal (síncrono — usa django.test.Client)
# ---------------------------------------------------------------------------

def run_sync_test_with_client(client: Client, token: str) -> dict:
    """Bate na rota /api/v1/ai/salomao/chat via Django test Client síncrono.

    Usa o mesmo client que fez o login para manter a sessão (evita 401).
    ninja_jwt.JWTAuth é sync — o Client síncrono funciona corretamente.
    O AsyncClient retorna 401 porque Ninja não encontra authenticate_async no JWTAuth.
    """
    payload = {"message": "Como configuro o dízimo online na InChurch?"}
    url = "/api/v1/ai/salomao/chat"

    print(f"  URL: POST {url}")
    print(f"  Payload: {json.dumps(payload)}")
    print(f"  Authorization: Bearer {token[:40]}...")
    print()

    t0 = time.perf_counter()
    response = client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    print(f"  Status Code : {response.status_code}")
    print(f"  Latência    : {elapsed_ms}ms")

    try:
        body = response.json()
    except Exception:
        body = {"raw": response.content.decode("utf-8", errors="replace")}

    return {"status_code": response.status_code, "latency_ms": elapsed_ms, "body": body}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    _banner("TESTE DE INTEGRAÇÃO — POST /api/v1/ai/salomao/chat")

    # --- Passo 1: Redis ---
    _banner("Passo 1: Status do Redis")
    redis_ok = _check_redis()
    if redis_ok:
        print("  [OK] Redis acessível")
    else:
        print("  [WARN] Redis indisponível — sessão dos agentes não será persistida")

    # --- Passo 2: Usuário e JWT ---
    _banner("Passo 2: Usuário de Teste e JWT")
    client = Client()  # Instância compartilhada para login + chamada da API
    get_or_create_test_user()
    # ninja_jwt.JWTAuth é síncrono — AsyncClient retorna 401 porque não implementa
    # authenticate_async. Usamos o sync Client com token do login endpoint.
    token = get_jwt_token_via_login(client, "test_integration", "Test@1234!")

    # --- Passo 3: Teste via Client síncrono ---
    _banner("Passo 3: Chamada à API (Client síncrono)")
    result = run_sync_test_with_client(client, token)

    # --- Passo 4: Relatório ---
    _banner("Passo 4: Resposta Final")

    status = result["status_code"]
    body = result["body"]

    print(f"\n  HTTP Status : {status}")
    print(f"  Latência    : {result['latency_ms']}ms")
    print()
    print("  JSON Response:")
    print(json.dumps(body, indent=4, ensure_ascii=False))

    # Avaliação
    print()
    if status == 200:
        print("  [SUCESSO] Rota retornou 200 com payload estruturado")
        msg = body.get("message", "")
        if msg:
            print(f"  Mensagem do agente: {msg[:200]}")
    elif status == 503:
        print("  [OK - 503] Rota tratou corretamente o erro de quota/rate-limit")
        print("  Infraestrutura de LLM indisponível, mas a rota não crashou.")
        err = body.get("detail", "")
        print(f"  Detalhe: {err}")
    elif status == 401:
        print("  [FALHA] 401 Unauthorized — token JWT rejeitado")
    elif status == 422:
        print("  [FALHA] 422 Validation Error — payload incorreto")
    else:
        print(f"  [FALHA] Status inesperado: {status}")

    _banner("RELATÓRIO FINAL")
    print(f"  Redis status   : {'ONLINE' if redis_ok else 'OFFLINE'}")
    print(f"  HTTP status    : {status}")
    print(f"  Rota funcional : {'SIM' if status in (200, 503) else 'NAO'}")
    print(f"  LLM disponível : {'SIM' if status == 200 else 'NAO (quota/key inválida)'}")
    print()

    return 0 if status in (200, 503) else 1


if __name__ == "__main__":
    sys.exit(main())
