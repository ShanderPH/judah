"""Tabela de preços e cálculo de custo por execução do pipeline.

Fonte dos preços: documentação pública OpenAI (abril/2026). Valores em USD
por 1 milhão de tokens. Mantenha este arquivo como a ÚNICA fonte de verdade
para o cálculo — qualquer serviço que precise reportar custo deve chamar
`calculate_cost()` em vez de replicar a tabela.
"""

from __future__ import annotations

from decimal import Decimal

# Preços por 1M de tokens (USD). Atualize quando a OpenAI mexer na tabela.
# Usamos Decimal para evitar ruído de ponto flutuante ao persistir em
# DecimalField (ver models.TokenTrackingLog.total_cost_usd).
_ONE_MILLION = Decimal("1000000")

PRICING_PER_MILLION_TOKENS: dict[str, dict[str, Decimal]] = {
    "gpt-4o-mini": {
        "input": Decimal("0.15"),
        "output": Decimal("0.60"),
    },
    "gpt-4o": {
        "input": Decimal("5.00"),
        "output": Decimal("15.00"),
    },
}


def _normalize_model_name(model_name: str) -> str:
    """Mapeia variantes/aliases para chaves canônicas da tabela.

    Aceita variantes comuns (ex.: `gpt-4o-2024-08-06`) reduzindo para o
    prefixo canônico. Isso evita cadastro explícito de todas as datas de
    release do mesmo modelo.
    """
    lowered = (model_name or "").lower().strip()
    if lowered.startswith("gpt-4o-mini"):
        return "gpt-4o-mini"
    if lowered.startswith("gpt-4o"):
        return "gpt-4o"
    return lowered


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calcula o custo em USD de uma execução com base nos tokens consumidos.

    Args:
        model_name: Nome do modelo (ex.: "gpt-4o", "gpt-4o-mini" ou variantes
            datadas como "gpt-4o-2024-08-06").
        input_tokens: Tokens de entrada (prompt).
        output_tokens: Tokens de saída (completion).

    Returns:
        Custo em USD como float. Retorna 0.0 se o modelo não estiver
        catalogado — logue isso no chamador se precisar alertar FinOps.
    """
    key = _normalize_model_name(model_name)
    prices = PRICING_PER_MILLION_TOKENS.get(key)
    if prices is None:
        return 0.0

    input_cost = (Decimal(input_tokens) * prices["input"]) / _ONE_MILLION
    output_cost = (Decimal(output_tokens) * prices["output"]) / _ONE_MILLION
    return float(input_cost + output_cost)


__all__ = ["PRICING_PER_MILLION_TOKENS", "calculate_cost"]
