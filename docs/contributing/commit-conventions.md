> [Índice completo](../INDEX.md)

# Conventional Commits

## Formato

```
<type>(<scope>): <subject>

<body opcional>
```

- **Mensagem em inglês.**
- **Imperativa** ("Add feature", não "Added feature").
- **Subject ≤ 72 caracteres.**
- Body opcional explicando o "porquê".

## Tipos

| Tipo | Uso |
|------|-----|
| feat | Nova funcionalidade |
| fix | Correção de bug |
| refactor | Mudança de código sem alterar comportamento |
| chore | Tarefas de manutenção |
| docs | Documentação |
| test | Testes |
| perf | Performance |
| hotfix | Correção urgente em produção |
| spike | Pesquisa/prova de conceito |

## Scopes comuns

- `support`, `auth`, `knowledge`, `ai`, `webhooks`, `analytics`, `church`, `integrations`, `api`, `ci`, `docs`

## Exemplos

```
feat(support): add priority-based queue weighting

fix(ai): prevent infinite loop when OpenAI returns empty tool call

refactor(webhooks): extract signature validation to helper

docs(readme): update local development instructions
```
