# Plano: reconciliação de fechamentos após início dos ciclos

## Escopo

- Derivar o corte do menor `SupportConversationCycle.created_at` persistido. Sem ciclos, interromper o comando.
- Excluir `ConversationEvent` criado antes do corte antes de aplicar `--offset` e `--limit`, sem apagar eventos.
- Ignorar também ocorrências recebidas depois do corte cujo fechamento efetivo seja anterior a ele.
- Manter dry-run como padrão e exigir `--apply` explícito para escrita.
- Expor `legacy_skipped`, `no_cycle`, `identity_unavailable`, `conflict` e as classificações existentes separadamente.

## Critérios de aceite

1. Eventos anteriores ao corte não chegam ao serviço de reparo, inclusive com `--apply`.
2. Eventos pós-corte continuam paginados desde `--offset 0` e classificados pelo serviço existente.
3. O JSON informa os eventos legados sem somá-los a `scanned`; `legacy_skipped` inclui os recebimentos pré-corte totais e as ocorrências pré-corte encontradas na página atual. Por isso, não se soma esse campo entre páginas.
4. Testes locais, Ruff, mypy e pre-commit passam sem conectar testes a banco remoto.
5. Um único dry-run usa `railway run` com variáveis de `JUDAH/production/judah` e código local da branch; não há deploy nem `--apply`.
