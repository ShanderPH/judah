"""Compatibility checks for Heimdall's OpenAI structured-output schema."""

from apps.ai_agents.agents.triage import TriageResult


def test_enum_references_do_not_have_openai_unsupported_siblings() -> None:
    schema = TriageResult.model_json_schema()

    for property_name in ("rota", "prioridade", "sentimento"):
        property_schema = schema["properties"][property_name]
        assert "$ref" in property_schema
        assert set(property_schema) == {"$ref"}
