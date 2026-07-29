# Verificação local

Data: 2026-07-29
Branch: `agent/fix-ticket-reentry-offhours`
Base: `5f49d566812331864cdd32dd7a75b26e9ea9b242`

## Resultados

- Testes focados do incidente: `122 passed`.
- Testes do provisionamento: `4 passed`.
- Suíte completa: `980 passed, 11 skipped`.
- Cobertura total: `90.21%` (gate: `90%`).
- Ruff lint: aprovado.
- Ruff format check: aprovado (`354 files already formatted`).
- Mypy: aprovado (`Success: no issues found in 350 source files`).
- Django system check: aprovado (`0 silenced`).
- Drift de migrations: nenhum (`No changes detected`).
- `git diff --check`: aprovado.

Os testes foram executados com SQLite isolado e valores locais placeholder.
Nenhuma credencial ou banco de staging/produção foi carregado.

## Cenários cobertos

- Consulta HubSpot da thread solicita associação de ticket explicitamente.
- Fallback recupera o ticket somente da instância canônica local.
- Mensagem humana anterior ao novo turno do visitante não bloqueia a IA.
- Mensagem humana posterior continua bloqueando a IA.
- Handoff fora do expediente usa exatamente pipeline e estágio configurados.
- Resposta com pergunta/pedido de erro ou imagem permanece aguardando cliente.
- Replay legado de fechamento semanticamente inválido não fecha o ticket.
- URLs, parâmetros e representações de credenciais são sanitizados nos logs.
- Celery não armazena erros ignorados, tracebacks remotos ou resultado estendido.
- Provisionamento é dry-run por padrão, atômico, idempotente e rejeita owner ou
  e-mail conflitante.

## Gate remoto

Um smoke real de reentrada e handoff fora do expediente deve ser executado
apenas após deploy do SHA exato, com observação do ticket no HubSpot. Esse gate
não foi executado porque esta solicitação não autorizou deploy ou mutação
remota.
