request: fix/sandbox-chat-hubspot-auth
cycle: M
state: VERIFY
opened_at: 2026-07-14T12:15:00-03:00
last_update: 2026-07-14T14:20:00-03:00
agent_run_id: codex
current_blockers:
  - "Backend Railway ainda retorna 404 para /api/v1/webhooks/hubspot/sandbox/ porque estas mudancas locais nao foram entregues/deployadas"
  - "Configurar HUBSPOT_SANDBOX_APP_SECRET no backend e HUBSPOT_SANDBOX_ACCESS_TOKEN no webapp"
  - "O chatflow da sandbox precisa estar publicado e incluir judah-admin.staging.febrate.com/sandbox-chat na regra de target"
  - "conversation.newMessage ficou inativo no build remoto #7 ate o backend estar pronto"
next_action: "Deploy do hotfix; Felipe: publicar/segmentar o chatflow da sandbox para staging e configurar os dois secrets; Codex: reativar conversation.newMessage apos smoke test"
artifacts_generated:
  - 00-context/findings.md
  - 00-context/staging-domain-assessment.md
  - 01-plan/fix-plan.md
  - 03-verification/results.md
  - HANDOFF.md
verification_runs: 5
