# Judah WebApp — contratos mínimos de componentes

> Escopo: componentes críticos existentes, HeroUI v3 + Tailwind CSS v4.

## Tokens

Os tokens semânticos ficam em `app/globals.css` e usam `oklch`: `background`, `foreground`, `surface`, `muted`, `accent`, `success`, `warning`, `danger`, `info`, `border` e respectivos foregrounds. Componentes devem consumir significado (`var(--danger)`) e não uma cor visual fixa.

## Catálogo

| Padrão | Anatomia | Variantes/estados | Movimento e acessibilidade |
|---|---|---|---|
| Ação primária | `Button` + ícone opcional + rótulo | default, pending, disabled, danger | `onPress`; rótulo textual ou `aria-label`; sem repetição automática de write |
| Confirmação sensível | `Modal.Backdrop/Container/Dialog/Header/Body/Footer` | alvo, efeito, motivo, cancel, pending, success, unknown/error | foco contido pelo React Aria; cancelamento explícito; resultado persistente fora do modal |
| Lista paginada | cabeçalho, rows, status, `nav` | loading, empty, partial, forbidden/error, success | “Mostrando X–Y de Z”; anterior/próxima com disabled real; atualização anunciada |
| Filtro exclusivo | `RadioGroup` + `Radio.Content/Control/Indicator` | selected, focus, disabled | semântica e teclado do React Aria; não implementar grupo com botões soltos |
| Métrica | `MetricCard` | neutral, accent, success, warning, danger | informação não depende só da cor |
| Gráfico simples | SVG/barras visuais + tabela equivalente | empty, data, degraded | SVG decorativo; tabela disponível a tecnologia assistiva; animação desativada em reduced motion |
| Estado de dados | `DataState` / `DegradedNotice` | loading, empty, error, partial | `role=alert/status` quando aplicável; retry somente para leitura segura |

## Regras de conteúdo

- Ações destrutivas ou externas nomeiam alvo e efeito antes da confirmação.
- `force-reassign` exige motivo não vazio.
- 401 redireciona para login; 403, 404, 409, 429 e 5xx preservam a mensagem sanitizada do contrato.
- Uma falha complementar não deve apagar widgets saudáveis.
- “Online” ou “backend live” só pode aparecer com evidência corrente; a versão do shell informa apenas que a sessão é protegida.

## Motion

- Scroll da janela, sidebar, status rail, modal e tabela é nativo.
- `scroll-behavior: smooth` global é proibido.
- `prefers-reduced-motion: reduce` encerra CSS transitions/animations e impede tweens GSAP dos gráficos.
- Grain animado, background fixo e blur de 20px foram removidos/reduzidos para diminuir custo de pintura.
