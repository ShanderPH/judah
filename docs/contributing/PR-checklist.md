> [Índice completo](../INDEX.md)

# Checklist de Pull Request

## Antes de abrir

- [ ] Branch nomeada como `<type>/<kebab-summary>`.
- [ ] Código atende ao [code-style.md](./code-style.md).
- [ ] Lint passa (`ruff check .`).
- [ ] Formatação passa (`ruff format --check .`).
- [ ] Type check passa (`mypy .`).
- [ ] Testes passam (`pytest`).
- [ ] Testes cobrem lógica nova.
- [ ] Sem `TODO`, `FIXME` ou prints/console.logs.
- [ ] Documentação atualizada quando necessário.
- [ ] Variáveis de ambiente novas documentadas em [setup/environment-variables.md](../setup/environment-variables.md).
- [ ] Migration criada se models foram alterados.

## Na descrição do PR

- [ ] Resumo do que mudou.
- [ ] Motivação / contexto.
- [ ] Como testar.
- [ ] Screenshots/recordings para mudanças de UI.
- [ ] Link para ticket do Jira/HubSpot quando aplicável.

## Após merge

- [ ] Branch deletada.
- [ ] Deploy em staging verificado.
- [ ] Sentry monitorado por 5 minutos.
