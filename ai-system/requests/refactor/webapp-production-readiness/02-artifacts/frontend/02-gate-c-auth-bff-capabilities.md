# Gate C — auth, BFF e capabilities

## Contratos congelados

- Refresh exclusivamente em JSON body; token anterior é blacklisted após rotação.
- Capabilities derivadas no backend e consumidas por rota, menu, ação e BFF.
- BFF policy `2026-07-29`, default-deny e body máximo de 16 KiB.
- Mutações exigem Origin/Host equivalentes e `Sec-Fetch-Site: same-origin`.
- Somente Content-Type, Idempotency-Key e X-Request-ID são encaminhados.

## Cookies

HttpOnly, SameSite=Lax, Secure em produção, Path=/ e max-age pelo `exp` do JWT. `__Host-` foi avaliado e adiado para não forçar relogin durante este gate; nenhum Domain é configurado.

## Rollback

A allowlist é server-side e default-deny. Em incompatibilidade de sessão, limpar os cookies e exigir novo login. Não reabrir refresh por query sem aprovação e janela explícita.

## Limites

Nenhuma feature flag foi ativada em staging/produção. Upgrade Next/sharp, headers/CSP, logging estruturado e CI pertencem ao Gate D.
