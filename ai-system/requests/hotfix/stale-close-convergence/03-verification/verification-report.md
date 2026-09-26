# Verificação local do hotfix

Branch `hotfix/stale-close-convergence`, baseline `8b4d99134d3d553efec4cf044a9100f027b3b50d`.

## Portões executados

- Ruff format/check: limpos no repositório inteiro.
- mypy: `Success: no issues found in 360 source files`.
- `run_tests_local.py`: 897 aprovados, 46 ignorados; cobertura 91,13%.
- Concorrência real PostgreSQL 16 local: 3 testes aprovados (`off`, `shadow`, `enforce`), conexões independentes.
- Dry-run do reparador: teste captura SQL e confirma ausência de INSERT/UPDATE/DELETE; apply exige writer authority.
- `manage.py makemigrations --check --dry-run`: `No changes detected`.
- `git diff --check`: limpo.

O primeiro CI do PR #126 passou 936 testes e falhou apenas em `test_agentos_registers_only_independent_agents`: a instalação limpa não incluía `greenlet`, exigido pelo SQLAlchemy assíncrono. A declaração em `requirements/base.txt` agora usa `sqlalchemy[asyncio]`; o metadata instalado confirma `greenlet>=1` nesse extra. Depois da correção, a suíte local em Python 3.14.7 passou novamente (897 aprovados, 46 ignorados) e `uv pip check` confirmou compatibilidade das 160 dependências instaladas. A nova execução do CI é o portão final para validar a instalação limpa.

## Cenários cobertos

- Evento FECHADO calculado entregue depois de duas remoções de owner: permanece stale, é despachado e fecha o ciclo em T1.
- `ConversationInstance.closed_at` e o ciclo de serviço recebem T1; observação genérica de estágio fechado não fecha lifecycle quando ciclos são obrigatórios.
- Falha no broker seguida de retry do webhook stale: a segunda tentativa volta a despachar.
- Generic stage observation e owner event mantêm a policy anterior.
- Fechamento repetido cria uma ClosedConversation e não decrementa capacidade de novo nos três modos.
- Reabertura posterior preserva ciclo, AssignedConversation, occupancy, capacidade e lifecycle correntes; inclui corrida em que B aparece durante a leitura do provider.
- Provider indisponível e timestamp ausente/inválido não fecham o ciclo; dry-run não grava.
- Dois workers em PostgreSQL convergem para uma única projeção e um único decremento; conflito de revisão é classificável/retryable.

## Limitação de domínio explícita

Pela regra literal do Caso A do plano, um ciclo já `CLOSED` retorna `DUPLICATE` mesmo quando falta sua `ClosedConversation`. O reparador não cria essa projeção neste hotfix. O baseline encontrou 8 **ocorrências** nessa condição, não necessariamente 8 ciclos distintos. O restante do backlog é classificado pelo ciclo alvo e pelo provider; não será reparado sem dry-run e aprovação operacional.

## Limites de validação

Não houve deploy nem smoke em staging/produção, e `--apply` não foi executado em produção. A taxa de novas divergências precisa ser medida após o deploy do mesmo SHA em API, Worker e Beat.
