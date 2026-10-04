# Hotfix do PR #134 — entrada de lifecycle e CI

## Escopo autorizado

Solicitação do Felipe em 2026-10-02: analisar objetivo, comentários, CI/CD e codebase do PR #134 e implementar ajustes necessários. Esta autorização cobre implementação local e atualização do PR; o rollout e o recovery histórico continuam sujeitos aos gates do master plan.

O PR começou como baseline documental. A revisão identificou uma falha crítica de dependência e duas lacunas no recovery de entrada. O ajuste é manutenção, sem mudança arquitetural: reutiliza os writers, a identidade temporal e o orçamento existentes. A request arquitetural principal continua em VERIFY.

## Tarefas

- **BE-01:** agendar entradas comprovadas ao persistir; encaminhar retries de entrada para `open_from_proven_occurrence`; recuperar entradas pending antigas sem agendamento.
- **OPS-01:** atualizar Next.js e seu preset ESLint para 16.3.8, com lockfile determinístico, preservando o gate de auditoria.
- **V-01:** reproduzir o defeito antes do patch e verificar orçamento, conflito, stale, duplicidade, evidência inválida, isolamento de owner e limite do scanner em SQLite/PostgreSQL local.

## Critérios de aceitação

1. Entrada comprovada fica agendada; duplicata não reinicia horário nem contador de retry.
2. Retry de entrada usa exclusivamente a ocorrência persistida e o writer canônico de abertura; não chama projeção de fechamento ou readback de fechamento.
3. Conflito/stale não fecha nem substitui ciclo existente. Retry e idade permanecem bounded; evidência proven permanece proven quando exige repair.
4. Scanner inclui entradas pending sem agendamento, exclui processed/repair/futuras e preserva o lote de 100. A recuperação de owners sem agendamento não muda.
5. `npm ci`, lint, tipagem, testes, build e auditoria de produção passam. Ruff, mypy, checks Django e verificação de migrations passam; cobertura Python permanece acima do piso de 90%.

## Limites

Os 229 owners e 15 closes já em repair não serão reabertos pelo scanner. Entradas anteriores ao orçamento de idade serão classificadas como repair, sem abrir ciclos históricos. Deploy, replay, PATCH HubSpot, migração remota e alteração de HMAC ficam fora deste hotfix.

## Verificação

Resultados, comandos e limitações: `../03-verification/pr-134-hotfix-review.md`.
