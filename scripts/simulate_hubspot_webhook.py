"""Simulador local do webhook do HubSpot (sem Ngrok, sem API real).

Uso:
    1. Exporte USE_MOCK_HUBSPOT=True no ambiente do servidor Django.
    2. Rode o servidor Django (ex.: `python manage.py runserver`).
    3. Execute este script: `python scripts/simulate_hubspot_webhook.py`.

O que faz:
    - Monta um payload JSON-array no mesmo formato que o HubSpot envia
      quando a propriedade `triagem_status` de um ticket muda.
    - POSTa no endpoint `/api/v1/ai/webhooks/hubspot/ticket-change`.
    - Como o servidor está com `USE_MOCK_HUBSPOT=True`, a validação HMAC
      é ignorada e `hydrate_ticket_context` devolve um mock fixo — não
      encosta na API do HubSpot.
    - Imprime `status_code` e corpo da resposta. O pipeline Salomão roda
      em `asyncio.create_task` no servidor; observe o console do Django
      para ver o Supervisor instanciando + tomando decisão (BOLETO).

Este arquivo roda standalone (sem Django settings), por `httpx` puro.
"""

from __future__ import annotations

import json
import sys

import httpx

WEBHOOK_URL = "http://localhost:8000/api/v1/ai/webhooks/hubspot/ticket-change"

# Payload no formato exato que o HubSpot envia (lista de eventos).
PAYLOAD: list[dict[str, object]] = [
    {
        "eventId": 12345,
        "subscriptionId": 9876,
        "objectId": 999999,
        "propertyName": "triagem_status",
        "propertyValue": "Novo",
        "subscriptionType": "ticket.propertyChange",
    },
]


def main() -> int:
    """Dispara o POST e imprime o retorno. Retorna 0 se HTTP 202."""
    print(f"[>] POST {WEBHOOK_URL}")
    print(f"    payload: {json.dumps(PAYLOAD)}")
    try:
        response = httpx.post(WEBHOOK_URL, json=PAYLOAD, timeout=10.0)
    except httpx.HTTPError as exc:
        print(f"[x] Falha de rede: {exc.__class__.__name__}: {exc}")
        print("    Verifique se o Django dev server esta rodando em :8000.")
        return 2

    print(f"[<] status_code: {response.status_code}")
    try:
        print(f"  body: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except ValueError:
        print(f"  body (raw): {response.text}")

    if response.status_code == 202:
        print()
        print("[ok] Webhook aceito. Observe o console do Django para ver:")
        print("     - hubspot_context_mocked (mock aplicado)")
        print("     - SalomaoSupervisorAgent sendo instanciado")
        print("     - supervisor_pipeline_completed (decisao da triagem)")
        print()
        print("Obs.: fora do horario comercial (America/Sao_Paulo), o webhook")
        print("      roteia para 'off_hours_pipeline' e o Supervisor NAO roda.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
