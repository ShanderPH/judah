# Diagnóstico de produção

Na janela de 08:06:02–09:06:02 BRT, o runtime `judah_production_runtime` falhou ao persistir
`conversation_instance_attendants`. A consulta de privilégios confirmou `SELECT=false`, `INSERT=false`,
`UPDATE=false` e `DELETE=false` nessa tabela, enquanto a tabela existe, pertence ao papel de migration e
mantém RLS habilitado.

O serviço usa `get_or_create()` e atualiza `last_seen_at`, owner e nome. O contrato mínimo necessário é
`SELECT, INSERT, UPDATE`. Não há consumidor de domínio que exclua esse histórico.

Escopo autorizado: implementação local do ajuste. Fora do escopo: alteração direta no Supabase, deploy,
replay de webhooks e reconciliação de tickets.
