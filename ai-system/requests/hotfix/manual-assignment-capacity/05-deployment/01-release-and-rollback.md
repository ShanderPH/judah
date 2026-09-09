# Release, ativação e rollback — preparado, não executado

## Limite desta entrega

Implementação e testes locais autorizados. Não houve commit, push, PR, merge, deploy, alteração de flags remotas, bootstrap remoto nem reparação histórica. O modo novo tem default `off`.

## Contrato e pré-requisitos

- Python 3.14; migration Django `support.0031_ticket_capacity`.
- `SUPPORT_CAPACITY_MODE=off|shadow|enforce`; `HUBSPOT_PORTAL_ID` obrigatório ao usar o contrato novo.
- `SUPPORT_CAPACITY_FRESHNESS_SECONDS=60`; `SUPPORT_CAPACITY_MAX_SCAN_TICKETS=200` inicialmente.
- Refresh tem orçamento local de 20s entre leituras; uma chamada em andamento pode terminar após esse limite. Search permite até duas chamadas/s deste consumidor, usando cache compartilhado. O limite do provider é por conta e outros consumidores precisam ser medidos no shadow.
- PostgreSQL e Redis são necessários. A proteção final da contagem usa unicidade, revisão e locks PostgreSQL; o cache reduz trabalho duplicado.
- Conferir RLS e triggers nas duas tabelas novas e no metadado de capacidade de agentes. Não conceder acesso a `PUBLIC`, `anon` ou `authenticated`.

## Release aditivo após autorização própria

1. Publicar a branch/PR revisada e registrar SHA aprovado.
2. Em staging autorizado, aplicar pelo caminho normal Django/Railway: API com predeploy primeiro; validar `showmigrations support`, tabelas, roles e readiness; alinhar worker e Beat ao mesmo SHA.
3. Manter `SUPPORT_CAPACITY_MODE=off` nos três serviços. Smoke de fila, manual, transferência e fechamento; confirmar ingestão, ledger, owner e contador.
4. Não usar o runner de testes contra staging/produção. Todos os testes destrutivos, inclusive reverse migration, são exclusivamente locais.

## Shadow e bootstrap, após autorização própria

1. Configurar `shadow` em todos os consumidores da janela. O contador legado continua ativo; tabelas novas recebem observações e comparação.
2. Executar explicitamente `python manage.py bootstrap_support_capacity` em runtime com autoridade de escrita e configuração da conta correta. O comando recusa outros modos.
3. Guardar relatório por UUID de agente: operações inspecionadas, prontidão, carga identificada e contador legado. Reexecutar é seguro para contagem; retries com liberação comprovada ficam `released`; intenções ambíguas mantêm reserva.
4. Investigar `degraded`, operações legadas sem classificação, timestamps conflitantes e carteiras que excedam orçamento. Não marcar pronto manualmente.
5. Observar tráfego representativo de atribuição manual, transferência, autoatribuição, timeout/reparo e fechamento. Medir chamadas/s por conta, duração de refresh, idade de observação e tempo de espera da fila.
6. O gate operacional só passa se o refresh necessário cabe no orçamento real. Resultado local com provider simulado não libera esse gate.

## Corte para enforcement

1. Suspender novas decisões automáticas e writes administrativos; manter ingestão durável. Confirmar a quiescência de API, worker e Beat e classificar/drenar todas as operações em voo.
2. Reconciliar carteiras e revisar reservas. Exigir prontidão fresca de todos os candidatos; registrar cursor/generation de ingestão e diferenças de projeção.
3. Com writers ainda suspensos, alinhar todos os serviços a `enforce`. Rematerializar os agentes a partir de `capacity_service.materialize()` dentro de uma transação, sob autoridade e com a lista de UUIDs revisada. Essa chamada não faz efeito no HubSpot. Conferir igualdade com `capacity_count()` e ausência de reserva ambígua antes de retomar writes.
4. Retomar consumidores no mesmo contrato e reprocessar pendências idempotentemente. Confirmar que `identified_capacity` no readiness não aponta agentes stale/degradados nem divergência do contador.
5. Verificar, por identidade de ticket, origem/destino, ocupação, reserva, tentativa e histórico. Acompanhar ao menos um refresh e o tráfego representativo; readiness verde isoladamente não prova E2E.

Não fazer um corte gradual com writers legados e novos simultâneos. Se não for possível assegurar a janela, voltar à revisão do rollout.

## Rollback operacional

Gatilhos: contagem duplicada, reserva perdida, decisão acima da capacidade conhecida, deadlock, orçamento excedido ou backlog sem recuperação.

1. Suspender novas reservas e writes administrativos mantendo ingestão.
2. Preservar ocupações, reservas e tentativas para auditoria. Confirmar owner de cada operação ambígua; não liberar reserva por idade/lease.
3. Preparar relatório por agente/ticket e reconstrução do contador/projeção compatível com o writer antigo. Requer autorização específica, pois apenas trocar a flag não corrige semântica de dados.
4. Com writers suspensos, aplicar a reconstrução revisada, alinhar todos os serviços ao código/modo anterior e só então retomar ingestão pendente.
5. Conservar a migration aditiva. Não executar reverse migration em produção para rollback de aplicação.

A reversão e reaplicação do schema foram testadas no PostgreSQL local descartável. A reversão operacional com dados reais continua sendo gate de staging autorizado.
