"""Exercise the real Judah -> Salomao v1 image flow without replying to HubSpot."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import uuid
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup(set_prefix=False)

from apps.ai_agents.agents.supervisor import SalomaoSupervisorAgent  # noqa: E402
from apps.ai_agents.services.hubspot import (  # noqa: E402
    DEFAULT_IMAGE_MAX_BYTES,
    _image_mime_type,
    build_conversation_context_from_hubspot_context,
    build_salomao_prompt_from_hubspot_context,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simula uma mensagem HubSpot com imagem sem publicar resposta na conversa.",
    )
    parser.add_argument("--image", type=Path, required=True, help="Caminho local da imagem do cliente.")
    parser.add_argument("--message", required=True, help="Texto enviado junto com a imagem.")
    parser.add_argument("--channel", choices=("chat", "whatsapp"), default="chat")
    parser.add_argument("--session-id", default=f"hubspot-image-test-{uuid.uuid4()}")
    return parser.parse_args()


def _read_image(path: Path) -> tuple[str, str]:
    content = path.read_bytes()
    max_bytes = int(os.getenv("HUBSPOT_IMAGE_MAX_BYTES", str(DEFAULT_IMAGE_MAX_BYTES)))
    if len(content) > max_bytes:
        raise ValueError(f"A imagem excede o limite configurado de {max_bytes} bytes.")

    mime_type = _image_mime_type(content)
    if mime_type is None:
        raise ValueError("Formato não suportado. Use JPEG, PNG, GIF ou WebP.")
    return base64.b64encode(content).decode("ascii"), mime_type


async def _run(args: argparse.Namespace) -> dict:
    image_base64, image_mime_type = _read_image(args.image)
    context = {
        "ticket_id": "image-flow-test",
        "subject": "Teste de leitura de imagem",
        "originating_channel": args.channel,
        "thread_ids": ["image-flow-test-thread"],
        "contact_ids": ["image-flow-test-contact"],
        "conversation_history": [
            {
                "id": "image-flow-test-message",
                "thread_id": "image-flow-test-thread",
                "direction": "INCOMING",
                "sender": "image-flow-test-contact",
                "text": args.message,
                "attachments": [
                    {
                        "type": "FILE",
                        "fileUsageType": "IMAGE",
                        "name": args.image.name,
                    }
                ],
            }
        ],
    }
    prompt = build_salomao_prompt_from_hubspot_context(context)
    if prompt is None:
        raise RuntimeError("O Judah não reconheceu a mensagem de entrada.")

    conversation_context = build_conversation_context_from_hubspot_context(
        context,
        session_id=args.session_id,
    )
    supervisor = SalomaoSupervisorAgent(
        session_id=args.session_id,
        user_metadata={
            "user_id": 0,
            "hubspot_ticket_id": context["ticket_id"],
            "hubspot_thread_id": context["thread_ids"][0],
            "hubspot_contact_id": context["contact_ids"][0],
            "originating_channel": "hubspot",
            "conversation_context": conversation_context.model_dump(mode="json"),
            "image_base64": image_base64,
            "image_mime_type": image_mime_type,
        },
    )
    result = await supervisor.run_pipeline_async(prompt)
    return {
        "channel": args.channel,
        "image_mime_type": image_mime_type,
        "response": result.message,
        "requires_human_handoff": result.requires_human_handoff,
        "handoff_reason": result.handoff_reason,
        "agent_trace": result.agent_trace,
        "model_name": result.model_name,
        "tokens_used": result.tokens_used,
    }


def main() -> None:
    args = _arguments()
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
