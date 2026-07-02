# JUDAH — Documentação do Backend Unificado InChurch

## Resumo

Esta pasta (`/docs`) contém a documentação técnica completa do **JUDAH**, o backend unificado da InChurch. O objetivo é permitir que desenvolvedores, agentes de IA e ferramentas automatizadas entendam a arquitetura, regras de negócio, APIs, banco de dados, segurança, deploy e operação do sistema sem precisar adivinhar o código.

## Como navegar

- **Quero entender o sistema de cima**: comece por [`INDEX.md`](./INDEX.md) e [`architecture/overview.md`](./architecture/overview.md).
- **Quero configurar o ambiente local**: vá para [`setup/local-development.md`](./setup/local-development.md) e [`setup/environment-variables.md`](./setup/environment-variables.md).
- **Quero integrar ou consumir APIs**: consulte [`api/README.md`](./api/README.md) e [`api/endpoints.md`](./api/endpoints.md).
- **Quero entender regras de negócio**: leia [`business/business-rules.md`](./business/business-rules.md) e [`business/workflows.md`](./business/workflows.md).
- **Quero contribuir com código**: siga [`contributing/README.md`](./contributing/README.md).
- **Quero operar/deployar**: veja [`operations/deployment.md`](./operations/deployment.md).
- **Quero usar como contexto para IA**: use [`ai/ai-context.md`](./ai/ai-context.md).
- **Quero ver o relatório de entrega**: leia [`REPORT.md`](./REPORT.md).

## Convenções usadas

| Marcador | Significado |
|----------|-------------|
| `TODO: confirmar` | Ponto que precisa de confirmação humana. |
| `Inferência baseada no código` | Regra deduzida a partir do código, não documentada explicitamente. |
| `Pontos de atenção` | Riscos, dúvidas ou inconsistências encontradas. |
| `Recomendações` | Sugestões práticas de melhoria. |

## Status

- **Versão documentada:** `1.0.0` (conforme `pyproject.toml`).
- **Status do sistema:** Pré-produção (conforme `README.md` do repositório).
- **Última atualização:** 2026-07-02.

## Documentação legada preservada

O arquivo [`technical-documentation.md`](./technical-documentation.md) (criado anteriormente) foi preservado e ainda pode ser consultado. Esta nova estrutura expande e organiza o mesmo conteúdo em arquivos menores e interligados.
