# Rollback de código — não executado

Base anterior confirmada localmente e no remoto em 2026-09-17:
`6f663265369fca7d2efccc780434cc5cdd4f0a61`.

Não há migrations, alteração de dados, secrets, flags ou provedores neste patch.
O SHA efetivamente implantado deverá ser confirmado antes de qualquer rollout;
a base Git acima não é evidência de SHA em produção.

## Procedimento após eventual merge autorizado

1. Registrar o SHA do squash/merge do PR e os SHAs efetivos de API/worker/beat.
2. Em branch de reversão criada a partir de main atualizada, executar
   `git revert <SHA_DO_SQUASH>` e revisar o diff. Se o merge não for squash,
   identificar o commit correto e sua topologia antes de escolher o comando.
3. Abrir PR de reversão para main, executar checks e obter revisão humana.
4. Após autorização operacional e deploy, confirmar os SHAs nos serviços e
   repetir probes e fluxos legítimos de manager/admin/refresh.

Nunca usar reset, force push ou mutation no banco para reverter este hotfix.
Uma reversão integral reabre SEC-01 a SEC-04; preferir correção pontual se viável.

## Gatilhos

Reverter ou corrigir se manager/admin perder acesso legítimo, o monitor não
interpretar o readiness, refresh interno entrar em loop ou sandbox admin quebrar.
403 esperado para viewer/agent/manager sem capability não é regressão.

## Gates ainda necessários

Browser real; revisão humana; PR/checks/branch protection; autorização e smoke
de staging/produção. Não induzir falhas em produção. Chamada HubSpot admin real
exige autorização operacional separada. Observar 401/403/5xx por 15 minutos
após rollout autorizado. Este procedimento não foi executado nem validado em
staging; nenhum deploy ocorreu nesta implementação.
