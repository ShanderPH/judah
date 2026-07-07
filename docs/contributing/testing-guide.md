> [Índice completo](../INDEX.md)

# Guia de Testes

## Resumo

O JUDAH usa `pytest` com `pytest-django`. Testes unitários cobrem lógica de negócio; testes de API validam endpoints.

## Setup

```bash
# Instalar dependências de dev
pip install -r requirements/dev.txt

# Rodar todos os testes
pytest

# Rodar com cobertura
pytest --cov=apps --cov-report=html

# Rodar app específico
pytest apps/support/tests

# Rodar teste específico
pytest apps/support/tests/test_queue_service.py::test_select_next_agent_prefers_online -xvs
```

## Isolamento do banco

O `conftest.py` configura `isolate_db`, que deleta dados das tabelas de suporte antes de cada teste. **Nunca aponte para bancos não-locais.**

```python
# pytest_configure no conftest.py
pytest_plugins = ["pytest_django"]
```

## Escrevendo testes

### Exemplo de teste unitário

```python
def test_assign_agent_ignores_offline():
    agent = AgentFactory(status_enum=AgentStatus.OFFLINE)
    result = assign_agent_to_conversation(ticket_id="123")
    assert result.success is False
    assert result.reason == "NO_ELIGIBLE_AGENT"
```

### Exemplo de teste de API

```python
def test_queue_status_requires_auth(client):
    response = client.get("/api/v1/support/queue/status/")
    assert response.status_code == 401
```

## Mocks

- Use `unittest.mock` ou `pytest-mock` para serviços externos (OpenAI, HubSpot, Pinecone).
- Celery tasks devem ser testadas com `task_always_eager=True` ou mocks.

## CI

A pipeline roda lint e testes em cada PR. Type checking com `mypy` é listado como tooling obrigatório no `AGENTS.md`, mas **não está configurado** no CI, no pre-commit nem nos scripts de execução local atuais.

```bash
ruff check .
ruff format --check .
pytest
# mypy .  # não roda automaticamente hoje
```

## Arquivos relacionados

- [`api/examples.md`](../api/examples.md)
