# Plano: reconciliação de fechamentos após início dos ciclos

## Escopo

- Derivar o corte do menor `SupportConversationCycle.created_at` persistido. Sem ciclos, interromper o comando.
- Excluir `ConversationEvent` criado antes do corte antes de aplicar `--offset` e `--limit`, sem apagar eventos.
- Ignorar também ocorrências recebidas depois do corte cujo fechamento efetivo seja anterior a ele.
- Antes da paginação, exigir um ciclo local cuja entrada seja anterior ou igual ao fechamento efetivo e cuja identidade seja resolvível pelas regras do serviço.
- Tratar ausência de ciclo, ciclo futuro e identidade temporal indisponível como fora do universo de repair. `--offset` conta somente candidatos com ciclo resolvido.
- Manter dry-run como padrão e exigir `--apply` explícito para escrita.
- Expor `legacy_skipped`, `no_cycle`, `identity_unavailable`, `conflict` e as classificações existentes separadamente.

## Critérios de aceite

1. Eventos anteriores ao corte não chegam ao serviço de reparo, inclusive com `--apply`.
2. A primeira página contém até 100 candidatos com ciclo local temporalmente resolvido, ignorando `no_cycle` antes de aplicar `--offset` e `--limit`.
3. O JSON informa os eventos legados e sem ciclo sem somá-los a `scanned`. `legacy_skipped` inclui os recebimentos pré-corte totais e as ocorrências pré-corte examinadas; `no_cycle` e `identity_unavailable` contam as exclusões observadas até a página preencher. Esses campos não são somáveis entre offsets.
4. Testes locais, Ruff, mypy e pre-commit passam sem conectar testes a banco remoto.
5. Um único dry-run usa `railway run` com variáveis de `JUDAH/production/judah` e código local da branch; não há deploy nem `--apply`.
