## Descrição

<!-- Descreva claramente o que foi alterado e por quê. -->

## Tipo de mudança

- [ ] `feat` — Nova funcionalidade
- [ ] `fix` — Correção de bug
- [ ] `refactor` — Refatoração sem mudança de comportamento
- [ ] `docs` — Documentação
- [ ] `test` — Testes
- [ ] `chore` — Configuração, build, dependências
- [ ] `perf` — Melhoria de performance

## Checklist

### Código
- [ ] O código segue os padrões do projeto (Ruff, tipagem)
- [ ] Não há `print()`, `console.log()` ou logs de debug esquecidos
- [ ] Sem credenciais, tokens ou dados sensíveis no código

### Testes
- [ ] Testes unitários adicionados/atualizados
- [ ] Todos os testes passam localmente (`make test`)
- [ ] Cobertura >= 80% nas partes críticas

### Banco de Dados
- [ ] Migrations criadas se houver mudanças de model
- [ ] Migrations testadas localmente (`make migrate`)
- [ ] Sem `--fake` ou migrations destrutivas sem justificativa

### Documentação
- [ ] `docs/features/<feature>/` atualizado se aplicável
- [ ] `docs/decisions_and_changes_log.md` atualizado se houver decisão arquitetural
- [ ] README atualizado se necessário

## Mudanças no banco de dados

<!-- Liste as migrations ou mudanças de schema, ou escreva "N/A" -->

## Como testar

<!-- Passos para validar manualmente esta PR -->
1.
2.
3.

## Issues relacionadas

<!-- Closes #xxx, Fixes #xxx -->
