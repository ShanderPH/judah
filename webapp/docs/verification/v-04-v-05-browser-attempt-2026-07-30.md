# V-04/V-05 browser verification history

> Date: 2026-07-30
> Branch: `refactor/webapp-production-readiness`
> Scope: local-only Playwright MCP verification against disposable SQLite data.

The first in-app Browser attempt returned `No browser is available`. The same-day retry with the Playwright MCP succeeded and supersedes that blocked result.

## Closed coverage

- Authenticated desktop (`1440x1000`) and mobile (`390x844`) flows for dashboard, queue, auto-assignment, agents, metrics and the permitted sandbox route.
- Deterministic local admin, two synthetic agents and 105 synthetic queue rows. The reproducible procedure is in `local-ui-browser-fixture.md`.
- Queue pagination reached `81-105 de 105`; Previous remained enabled and Next disabled.
- The manual-assignment dialog identified `UI-VERIFY-081`, required an agent, kept Confirm disabled and restored focus to the originating Assign button after Escape. No mutation was sent.
- Mobile keyboard order begins at `Abrir menu`; Enter moves focus to `Fechar menu`; Escape closes the drawer and restores focus to `Abrir menu`.
- Reduced motion matched the media query and left zero active animations.
- Axe reported zero serious/critical violations on all critical routes in the final corrected build. A remaining heading-order result is moderate and documented for later semantic cleanup.
- The final clean route trace removed BFF 308 redirects and issued one request per backend resource. The intentionally isolated local failures were queue health 500 (PostgreSQL-only diagnostic using `current_user`) and HubSpot visitor token 503 (placeholder external credential); the rest of each page remained usable.
- Clean dashboard measurement: LCP 512 ms, INP 88 ms, CLS 0.00320, one long task (51 ms), one frame gap over 34 ms and a maximum gap of 62.5 ms. These local numbers are diagnostic, not production RUM.

## Findings corrected during verification

- Empty charts no longer ask GSAP to animate missing targets.
- GSAP uses canonical `rotationX`/`rotationY` properties so context cleanup does not warn.
- Browser BFF URLs no longer incur a trailing-slash 308 before the real response.
- Light-theme semantic colors now satisfy critical contrast checks.
- The two complementary landmarks have unique labels and the service heading no longer starts at level three.
- The closed mobile drawer is hidden from keyboard navigation and manages focus on open/close.

## Evidence

- `docs/verification/artifacts/v04-v05-dashboard-desktop.jpg`
- `docs/verification/artifacts/v04-v05-dashboard-mobile.jpg`
- `docs/verification/artifacts/v04-v05-queue-page3-desktop.jpg`
- `docs/verification/artifacts/v04-v05-queue-mobile.jpg`
- `docs/verification/v-04-v-05-browser-verification-2026-07-30.md` (independent browser review)

V-04 and V-05 are closed for the local release candidate. Vercel Preview and production verification remain distinct release stages.
