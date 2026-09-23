# Diagnóstico de produção

Após o bootstrap de capacidade em `shadow`, seis agentes permaneceram degradados mesmo com o
portfólio ativo vazio no HubSpot. A reconciliação reconstruía a lista a partir de todo o histórico
de `AssignedConversation`; ao atingir o limite de leitura ou de tempo, a próxima execução começava
novamente pelos mesmos tickets.

Também havia uma tentativa em `repair_required` ligada a ciclo encerrado. O reparador a contabilizava
como `skipped_stale_cycle`, mas não persistia a transição terminal. Quando `compensated_at` já estava
preenchido, a compensação retornava antes de corrigir o estado inconsistente.

O hotfix deve tornar ambos os fluxos convergentes e idempotentes. A ativação de
`SUPPORT_CAPACITY_MODE=enforce` permanece fora deste hotfix e depende dos gates pós-deploy.
