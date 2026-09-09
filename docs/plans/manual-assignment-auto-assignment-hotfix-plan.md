# Planning — atribuição manual e capacidade

O plano completo e canônico está em [master-plan.md](../../ai-system/requests/hotfix/manual-assignment-capacity/01-plan/master-plan.md).

- Base: [research](../research/manual-assignment-auto-assignment-hotfix.md).
- Progresso: [STATUS.md](../../ai-system/requests/hotfix/manual-assignment-capacity/STATUS.md).
- Proposta: ocupação por ticket, reservas explícitas e reconciliação idempotente, com promoção para Ciclo F sujeita à aprovação.
- Inclui tarefas/dependências, matriz de aceitação, gates PostgreSQL locais, compatibilidade, bootstrap e rollback.
- Planning concluída para revisão. Implementation não iniciada; nenhuma branch ou alteração de código.

Na futura Implementation, a primeira ação será criar a branch `hotfix/manual-assignment-capacity`, antes de alterar código ou testes. Publicação, deploy e ativação permanecem etapas separadas.

Atualizacao: implementacao local concluida e verificada; publicacao autorizada. Consulte STATUS.md e o relatorio de verificacao da request para o estado atual. O texto acima registra a etapa original de Planning.
