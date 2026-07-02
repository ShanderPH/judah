> Início / [Visão geral](../README.md) / [Índice completo](../INDEX.md)

# Contribuindo com o JUDAH

## Resumo

Guia para desenvolvedores que queiram contribuir com o projeto JUDAH. Aqui você encontra links para os padrões de código, convenções de commits, checklist de PR e guia de testes.

## Contexto

O projeto segue o ciclo de desenvolvimento descrito no [AGENTS.md](../../AGENTS.md). Contribuições devem ser feitas via branches nomeadas como `<type>/<kebab-summary>` e pull requests.

## Conteúdo desta seção

| Documento | Descrição |
|-----------|-----------|
| [code-style.md](./code-style.md) | Padrões de código Python e TypeScript |
| [commit-conventions.md](./commit-conventions.md) | Conventional Commits |
| [PR-checklist.md](./PR-checklist.md) | Checklist para abrir pull requests |
| [testing-guide.md](./testing-guide.md) | Como escrever e rodar testes |

## Fluxo de contribuição

1. Crie uma branch a partir de `main`.
2. Implemente a mudança seguindo os padrões de código.
3. Escreva/atualize testes.
4. Rode lint, type check e testes localmente.
5. Abra PR para `main`.
6. Aguarde revisão e CI verde.

## Regras gerais

- Nunca commite direto em `main` ou `production`.
- Não deixe `TODO`, `FIXME` ou prints no código final.
- Atualize a documentação se mudar arquitetura, setup ou comportamento.
- Siga o [Definition of Done](../AGENTS.md#6-padrões-de-qualidade-definition-of-done-universal).
