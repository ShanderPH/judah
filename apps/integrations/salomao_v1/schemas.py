"""Pydantic schemas for the standalone Salomao v1 service."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SalomaoV1TokenUsage(BaseModel):
    """Token usage returned by Salomao v1."""

    prompt: int = 0
    completion: int = 0
    total: int = 0


class SalomaoV1ChatResult(BaseModel):
    """Normalized response from Salomao v1's POST /chat endpoint."""

    success: bool = True
    response: str
    session_id: str
    transfer_requested: bool = False
    audio_transcription: str | None = None
    model_used: str | None = None
    message_count: int | None = None
    tokens: SalomaoV1TokenUsage = Field(default_factory=SalomaoV1TokenUsage)
    message_id: str | None = None
    error: str | None = None


__all__ = ["SalomaoV1ChatResult", "SalomaoV1TokenUsage"]
