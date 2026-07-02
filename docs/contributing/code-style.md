> [Índice completo](../INDEX.md)

# Guia de Estilo de Código

## Python

- **Versão:** Python 3.14 (target do ruff).
- **Formatador/Linter:** ruff.
- **Type checker:** mypy em modo strict.
- **Type hints:** obrigatórias em funções públicas. Evite `Any`; se necessário, justifique em comentário.
- **Docstrings:** Google-style para módulos, classes e funções públicas.
- **Importações:** ordem padrão do ruff (`isort`).
- **Comprimento de linha:** 88 caracteres (padrão Black/ruff).

### Exemplo

```python
def calculate_wait_seconds(
    entered_queue_at: datetime, assigned_at: datetime
) -> int:
    """Calcula o tempo de espera em segundos.

    Args:
        entered_queue_at: momento em que entrou na fila.
        assigned_at: momento da atribuição.

    Returns:
        Tempo de espera em segundos.
    """
    if not entered_queue_at or not assigned_at:
        return 0
    return max(int((assigned_at - entered_queue_at).total_seconds()), 0)
```

## Django / Ninja

- Schemas explícitos por endpoint; evite `dict` solto na response.
- Views devem ser finas; lógica de negócio fica em services/selectors.
- Use `select_related` / `prefetch_related` quando apropriado.

## TypeScript / Next.js / React

- TypeScript strict; sem `any` (use `unknown` + type guards).
- Componentes funcionais com hooks.
- Tailwind para styling. CSS-in-JS apenas se justificado.

## SQL / Migrations

- snake_case.
- Migrations idempotentes; sempre inclua `down`/`reverse_code`.
- Documente índices com comment no SQL.

## Nomeação

- Branches: `<type>/<kebab-summary>`.
- Commits: Conventional Commits.
- Variáveis: snake_case (Python), camelCase (TypeScript).
- Classes: PascalCase.

## Comandos de verificação

```bash
ruff check .
ruff format --check .
mypy .
pytest
```
