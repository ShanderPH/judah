# Convergência idempotente de fechamentos fora de ordem

Plano fornecido e autorizado pelo usuário em 2026-09-25. Ciclo M, P0.
Baseline: `8b4d99134d3d553efec4cf044a9100f027b3b50d`.

## Escopo e aceite

- BE-01: ocorrência calculada de FECHADO recebe policy idempotente; stale suppression genérica permanece.
- BE-02: resolver ciclo por occurrence time; fechar atomicamente apenas suas projeções; não fechar lifecycle nem liberar capacidade de reabertura posterior.
- BE-03: retries e concorrência convergem por identidade do ciclo.
- BE-04: outcomes explícitos em logs estruturados sem payload ou PII.
- OPS-01: reparador limitado, dry-run por padrão e writer authority para apply, usando o mesmo serviço.
- V-01–V-09: policy, incidente, reabertura, duplicatas, concorrência PostgreSQL local, provider indisponível, timestamp inválido, três capacity modes e suíte completa.
- Sem migrations, flags ou mutações em produção. Deploy e reparo operacional dependem de etapa posterior.

## Limites

Até cinco arquivos de produção com alterações substanciais. Schema, substituição do lifecycle ou expansão arquitetural exigem promoção para Ciclo F.
O volume necessário inclui serviço, adapter e reparador previstos no plano, além de testes e evidências; avaliar o diff por responsabilidade, sem refactors adicionais.

## Integrações descobertas

`owner_reconciliation_service.reconcile_ticket` chama o fechamento sob lock. Esse chamador deve fornecer o snapshot já lido para impedir HTTP sob lock.
O lifecycle também aplica CLOSE antes do handler: ocorrências calculadas precisam adiar essa transição até a resolução do ciclo.

Teste `test_stale_close_dispatch_retries_after_broker_failure` falhou com uma única chamada ao dispatcher em duas tentativas. A condição de stale occurrence precisa aceitar também eventos PENDING/FAILED. Alteração pontual em `apps/webhooks/services.py`, autorizada pela watch list após demonstração; não representa reestruturação substancial de um sexto arquivo.

## Decisão conservadora

A constraint `uniq_active_conv_cycle_ticket` impede A ativo e B ativo simultaneamente. Com B existente, A normalmente está CLOSED/CANCELLED. Mantida a regra literal do Caso A (§5.3): A CLOSED retorna DUPLICATE e preserva `closed_at`, mesmo se a projeção ClosedConversation estiver ausente. Esse resíduo não é automaticamente reparado por este P0 e será sinalizado na verificação. Não alterar schema nem converter CANCELLED por heurística.
