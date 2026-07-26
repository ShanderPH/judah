# AGENTS.md — Workspace

> **Arquivo:** `<workspace-root>/AGENTS.md`
> **Escopo:** este repositório.
> **Carregado automaticamente** pelo Antigravity (e por Cursor / Claude Code se você usar via cross-tool).
> **Versionar em git** — este arquivo é parte do contrato do projeto.

---

## 1. STACK DESTE PROJETO

- **Linguagens:** Python 3.14 (versão exata obrigatória)
- **Frameworks:** Django 5.2 LTS + Django Ninja 1.6, Celery 5
- **Banco / Storage:** PostgreSQL 16 (via Supabase), Redis 7
- **AI infra:** Agno 2.5, OpenAI API (GPT-4o/mini), Pinecone serverless, MCP 1.x (FastMCP)
- **Deploy:** Railway (API, Celery Worker, Celery Beat)
- **Tooling obrigatório:** ruff (target py314), mypy, pytest, pytest-django, pre-commit

## 2. ESTRUTURA `ai-system/` ESPERADA

```
ai-system/
  AGENTS.md         # este arquivo
  CONVENTIONS.md    # padrões deste projeto
  ROUTING.md        # ajustes de roteamento (override do global)
  requests/<branch>/
    00-context/, 01-plan/, 02-artifacts/{backend,frontend,database,devops}/,
    03-verification/, 04-iteration/, 05-deployment/
    STATUS.md, HANDOFF.md
  archive/
```

Se a estrutura não existir e a TASK tiver complexidade > trivial: **pergunte se deve inicializar** antes de prosseguir.

## 3. CONVENÇÕES DE NOMENCLATURA

### Branches
`<type>/<kebab-summary>` onde type ∈ {feat, fix, refactor, chore, docs, test, perf, hotfix, spike}.

### Task IDs (dentro de uma request)
`<LAYER>-<NN>` → BE-01, FE-02, DB-01, OPS-01, V-01 (verification).

### Commits
[Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>): <subject>`. Mensagem em **EN**, imperativa, ≤72 chars no subject. Body opcional explicando "porquê".

### Artifacts
- Diffs: `02-artifacts/<layer>/NN-<task-slug>.diff`
- Screenshots/recordings: `02-artifacts/<layer>/NN-<task-slug>-<n>.<ext>`
- Walkthroughs: `02-artifacts/<layer>/NN-<task-slug>.md`
- Iterações: `04-iteration/NN-<task-slug>.v2.diff`, `.v3.diff` (nunca sobrescreva)

## 4. STATUS.md (single source of truth)

Atualize a cada transição de fase. Formato:
```yaml
request: feat/new-card
cycle: F | M
state: <ver lista no AGENTS global>
opened_at: ISO-8601
last_update: ISO-8601
agent_run_id: <Manager View task ID>
current_blockers: []
next_action: "Felipe: aprovar Plan Artifact em 01-plan/master-plan.md"
artifacts_generated:
  - 01-plan/master-plan.md
verification_runs: 0
```

## 5. HANDOFF.md (preencha antes de VERIFY)

- **Resumo do implementado/corrigido:** 3-5 bullets.
- **Arquivos modificados:** paths absolutos relativos ao repo.
- **Como testar localmente:** comandos exatos. Para UI, instrução para o browser sub-agent.
- **Riscos conhecidos / áreas frágeis.**
- **Pontos de integração críticos:** o que VERIFY deve atacar primeiro.

## 6. PADRÕES DE QUALIDADE (Definition of Done universal)

Toda request, antes de DONE, passa por:
- [ ] Lint clean (ruff/eslint conforme stack)
- [ ] Type check clean (mypy/tsc)
- [ ] Testes unitários para lógica nova
- [ ] Sem TODOs, FIXMEs, prints/console.logs deixados
- [ ] Critérios de aceitação do `master-plan.md` cobertos
- [ ] Browser sub-agent verificou UI quando aplicável (recording em `03-verification/`)
- [ ] Smoke test pós-deploy em staging quando aplicável
- [ ] `STATUS.md` em estado `DONE`

## 7. PADRÕES DE CÓDIGO POR STACK

### Python (Django / FastAPI / Ninja)
- Python 3.12+; type hints obrigatórios em funções públicas.
- Pydantic v2 para schemas.
- Docstrings Google-style em módulos, classes e funções públicas.
- `ruff` + `mypy` strict; sem `Any` salvo justificativa em comentário.
- Para Django Ninja: schemas explícitos por endpoint, sem `dict` solto na response.

### TypeScript / Next.js / React
- TypeScript strict; sem `any` (use `unknown` + type guards).
- Componentes funcionais com hooks.
- Tailwind para styling. CSS-in-JS apenas se justificado em `decision-log.md`.
- ESLint + Prettier obrigatórios; configs versionadas em git.

### SQL / Migrations (Postgres / Supabase)
- snake_case.
- Migrations idempotentes; sempre `down` migration.
- Índices documentados em comment do SQL com justificativa.
- **Nunca** rode `DROP`/`TRUNCATE` em produção sem aprovação explícita do Felipe.

### N8N workflows
- Nomes descritivos para nodes (não "HTTP Request 3").
- Sticky comments em pontos de decisão.
- Credentials sempre via cofre, nunca hardcoded.
- Versionar export do workflow em git quando relevante.

## 8. ROTEAMENTO DE MODELOS — overrides

Herda do global (`~/.gemini/AGENTS.md` §4). Overrides específicos deste projeto vão em `ai-system/ROUTING.md` se necessário.

> Caso típico de override: projeto multimodal-heavy (ex.: análise de mocks Figma) → forçar Gemini 3 Pro como primário em todas as fases.

## 9. CICLOS — DECISÕES OPERACIONAIS DESTE REPO

### Quando usar Ciclo F (Feature)
- Nova feature com escopo > 2 arquivos.
- Refactor não-trivial.
- Mudança arquitetural.
- Greenfield / spike formal.

### Quando usar Ciclo M (Manutenção)
- Bug em produção (qualquer P0/P1/P2).
- Regressão.
- Hotfix.
- Ajuste comportamental sem nova feature.

### Triggers para promover Ciclo M → Ciclo F
- Root cause revela necessidade de refactor > 5 arquivos → **promova**, gere `master-plan.md`, peça aprovação.
- Fix exigiria mudança arquitetural → **pause**, escale para o Felipe.

## 10. MANAGER VIEW — REGRAS DESTE WORKSPACE

- **Cap de paralelismo:** 3 agentes simultâneos por padrão. Aumente apenas após observar throughput sem conflito.
- **Domínios isolados obrigatórios:** dois agentes nunca tocam os mesmos arquivos. Verifique watch list em cada `STATUS.md` antes de iniciar nova request paralela.
- **Browser sub-agent:** instância única — serialize uso entre agentes paralelos.
- **Branches paralelas:** cada agente em sua branch git.

## 11. SECURITY GUARDRAILS DESTE REPO

- **Pré-aprovação obrigatória:** Qualquer execução de testes que conectem a bases não-locais (devido ao `conftest.py:isolate_db` deletar dados), mudanças em verificação de HMAC de webhooks (HubSpot/Jira), ou modificação direta em DB de produção.
- **Áreas proibidas:** `.env`, `.env.example`, hardcoding de secrets nos agentes (garantir `debug_mode=False` para não vazar prompts/secrets nos logs).
- **Branches protegidas:** main, production. Agentes nunca commitam direto — sempre via PR.
- **Credenciais:** `DJANGO_SECRET_KEY`, `OPENAI_API_KEY`, `PINECONE_API_KEY`, `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_APP_SECRET`. Todas via Antigravity Customizations → Secrets ou variáveis de ambiente. Nunca em arquivos do repo ou logs de structlog.

## 12. WORKFLOWS LOCAIS (slash commands deste workspace)

Adicione em `<workspace>/.agent/workflows/` arquivos `.md` com conteúdo de comando. Exemplos sugeridos:
- `/run-tests` — executa suite de testes do projeto.
- `/lint` — roda ruff + eslint + tsc.
- `/db-snapshot` — captura schema atual do Supabase via MCP para `00-context/db-schema.md`.
- `/jira-sync` — busca tickets em aberto do projeto via Atlassian MCP.

## 13. INTEGRAÇÃO COM TICKETS (HubSpot / Jira - InChurch)

O JUDAH atua como webhook router e consolidador para HubSpot e Jira. Quando uma TASK envolver tickets:
1. **TRIAGE**:
   - Se Jira (ex: INCH-1234), consulte o ticket via Atlassian MCP e salve em `00-context/ticket.md`.
   - Se HubSpot (ex: Helpdesk), avalie interações via ferramentas do FastMCP (`get_ticket_status`, `create_helpdesk_ticket`, etc).
2. **Sincronização de Status (Jira)**: atualize conforme transições do Ciclo M (TRIAGE → "In Progress", VERIFY → "In Review", DEPLOY → "Done").
3. **Resolução**: anexe link da PR no comentário do Jira/HubSpot após o FIX. Lembre-se que webhooks inbound recebem HMAC v1/v3 (HubSpot) ou Jira.

## 14. CHECKLIST PRÉ-DEPLOY DESTE REPO

> Edite conforme infra real do projeto.

- [ ] Migrations aplicadas em staging com sucesso.
- [ ] Smoke tests no browser sub-agent passaram em staging.
- [ ] Sentry sem novos erros após 5min em staging.
- [ ] Feature flags configuradas (se aplicável).
- [ ] Plano de rollback testado e documentado em `05-deployment/`.
- [ ] Janela de deploy comunicada ao time (Slack/Jira).

---

**Em caso de conflito com `~/.gemini/AGENTS.md`:** use cabeçalho `> overrides global: <seção-N>` no início da seção que sobrescreve, e justifique em comentário inline.