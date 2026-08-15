# FE-01 — Experiência da página `/calendar`

## Alterações

- O `StatusRail` e a terceira coluna do shell aparecem somente em `/dashboard`; as demais rotas usam toda a largura disponível.
- “Helpdesk Operations” e “Período visível” foram consolidados em um único card de comando, com período, fuso, versão, navegação e ação principal.
- A grade ganhou largura mínima, altura maior por dia, rolagem horizontal responsiva e exibição completa de múltiplos intervalos.
- O detalhe permanente foi substituído por modal HeroUI v3 acionado pelo dia.
- O modal oferece edição rápida por ícone de lápis e criação de exceção para datas sem regra própria.
- A lista de regras publicadas permite editar e desativar horários migrados e regras novas.
- O wizard permite múltiplos intervalos, recorrência, estado de ausência, mensagem formatada e validação de sobreposição.

## Design system

Os componentes usam a API compound atual do HeroUI v3 (`Modal.Backdrop`, `Modal.Container`, `Modal.Dialog`, `Card`, `Button`) e eventos `onPress`, mantendo o design system existente.
