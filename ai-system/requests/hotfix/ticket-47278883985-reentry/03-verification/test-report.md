# Verificação local

Data: 2026-07-29
Branch: `agent/fix-ticket-reentry-offhours`
Base local antes das alterações: `fc29934de1356b61d936dbd8959514da91c53177`

## Resultados

- Testes focados finais de lifecycle/webhook/execução e app único: `104 passed`.
- Suíte completa final: `1013 passed, 11 skipped`.
- Cobertura total: `90.14%` (gate: `90%`).
- Ruff lint: aprovado.
- Ruff format check: aprovado (`355 files already formatted`).
- Mypy: aprovado (`Success: no issues found in 351 source files`).
- Django production deploy check: aprovado com o único warning
  `security.W008`, esperado e documentado porque o Railway encerra TLS e faz
  o redirecionamento HTTPS na borda.
- Drift de migrations: nenhum (`No changes detected`).
- `git diff --check`: aprovado.
- Varredura de padrões de segredo no diff: `0` ocorrências.
- HubSpot project validation: Judah aprovado e pronto para upload.

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
- Mensagem rápida não representada pelo booleano é recuperada uma única vez por
  `message_id`, sem repetir uma resposta já processada.
- O evento primário `conversation.newMessage` é ativo no projeto único
  Judah HubSpot Integration, aprovado na validação oficial do HubSpot CLI.
- Comentário interno e mensagem de boas-vindas não iniciam turno da IA.
- Resposta real que autoriza áudio permanece em `WAITING_FOR_CUSTOMER` e não
  executa fechamento.
- Um retorno oficialmente revalidado à pipeline da IA supera lifecycle humano
  obsoleto; uma mensagem comum durante atendimento humano preserva a autoridade
  do agente até essa revalidação.
- O reconciliador combina prioridade recente e rotação anti-starvation, usa
  lock Redis e degrada para idempotência durável quando Redis não está
  disponível.
- `conversation.newMessage` sem direção não altera o cursor do cliente nem
  reabre/fecha lifecycle; ele apenas agenda a verificação da thread.
- Mensagem `OUTGOING`, comentário interno e welcome message nunca substituem
  o último `message_id` confirmado do cliente.
- Evento HubSpot atrasado permanece no ledger, mas não pode desfazer o estado,
  snapshot ou efeitos de um evento com timestamp mais novo.
- Handoff e fechamento falham antes de qualquer mutação quando não há thread
  e turno `INCOMING` confirmados para revalidação no provedor.
- Todos os webhooks de produção autenticam no endpoint único do Judah; uma
  assinatura inválida não cria registro no banco.

## Gate remoto

Um smoke real deve ser executado somente após merge da PR, deploy do SHA exato
e upload autorizado do projeto Judah HubSpot Integration. Esse gate não foi
executado porque deploy e upload não fazem parte desta etapa.

## GitHub

- PR: `#97`, base `main`, branch `agent/fix-ticket-reentry-offhours`.
- Commit de código validado: `2597bf454d4f4e143294f942a91dfc256cab45ed`.
- CI run: `30464399975`.
- `Lint & Type Check`: aprovado.
- `Tests (Python 3.14)`: aprovado.
- `Security Scan`: aprovado.
- `Django System Checks`: aprovado.
- Vercel e preview comments: aprovados.
