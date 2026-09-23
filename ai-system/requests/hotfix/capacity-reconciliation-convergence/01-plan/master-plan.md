# Plano — convergência do bootstrap de capacidade

## Escopo

- BE-01: terminalizar tentativas já compensadas quando o ciclo não está mais ativo.
- BE-02: remover o desvio que apenas contabiliza ciclos encerrados sem persistir o reparo.
- BE-03: reconciliar o histórico em lotes retomáveis, preservando prioridade para portfólio ativo e reservas.
- V-01: provar a regressão da tentativa inconsistente e a convergência incremental do histórico.
- V-02: executar lint, type check, testes de suporte e suíte completa.

## Critérios de aceitação

1. Uma tentativa `repair_required` com `compensated_at` e ciclo encerrado termina em `compensated` sem nova chamada ao HubSpot nem novo débito de capacidade.
2. Uma segunda execução do reparador não volta a selecionar a tentativa terminal.
3. Um histórico maior que o lote permitido avança entre execuções e finalmente deixa o agente `ready`.
4. Tickets ativos retornados pelo HubSpot e reservas mantidas nunca são omitidos do lote.
5. Evidência local terminal ausente do portfólio ativo não é relida indefinidamente.
6. O modo de capacidade continua em `shadow`; o enforce só ocorre após deploy e gates aprovados.

## Rollback

Reverter o commit do hotfix. Não há migration nem alteração de configuração neste PR.
