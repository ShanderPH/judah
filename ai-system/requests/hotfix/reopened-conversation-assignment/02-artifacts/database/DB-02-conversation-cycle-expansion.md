# DB-02 - expansão de schema de ciclos

Migration `support.0020_conversation_cycles_expand` adiciona a entidade de ciclo,
constraints naturais/ativas, índices, FKs nulas nas seis projeções e o trigger
de isolamento do writer. O reverse remove somente objetos do Gate B e preserva
dados/guards anteriores. Prova PostgreSQL registrada em
`03-verification/01-gate-b.md`.
