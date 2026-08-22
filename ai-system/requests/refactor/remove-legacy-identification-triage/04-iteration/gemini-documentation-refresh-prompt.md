# Prompt para revisão documental com Gemini

Use o texto abaixo em uma nova sessão do Gemini com acesso ao checkout atualizado
da branch `refactor/remove-legacy-identification-triage`.

```text
Atue como Technical Writer Sênior e Engenheiro Backend especializado em Django,
Django Ninja, Celery, PostgreSQL/Supabase, HubSpot e sistemas orientados a
eventos.

Contexto do repositório:
- Projeto: JUDAH, backend operacional do Help Desk InChurch.
- Branch: refactor/remove-legacy-identification-triage.
- A implementação legada de identificação de clientes e triagem foi removida.
- O n8n será futuramente responsável por coleta de dados, identificação,
  confirmação de identidade e triagem.
- A integração JUDAH-n8n ainda não foi implementada e não deve ser especificada
  de forma inventada.

Objetivo:
Auditar e atualizar toda a documentação versionada para refletir fielmente o
código atual após a remoção. Não altere código de aplicação, migrations,
dependências, manifests HubSpot ou configuração de infraestrutura.

Instruções obrigatórias:
1. Leia integralmente AGENTS.md, README.md, docs/, core/settings/, core/urls.py,
   core/celery.py, apps/ai_agents/, apps/webhooks/, apps/support/ e
   apps/integrations/hubspot/ antes de editar documentação.
2. Verifique `git status --short --branch` e preserve alterações não relacionadas.
3. Trate o código executável como fonte de verdade. Não mantenha descrições de
   endpoints, tasks, estados, flags, agentes ou dependências que não existem.
4. Documente como responsabilidades atuais do JUDAH:
   - ingestão durável e idempotente;
   - lifecycle e auditoria de ciclos;
   - filas e Matchmaker;
   - atribuição automática e atualização de hubspot_owner_id;
   - agentes, status, disponibilidade e capacidade;
   - helpdesk_calendar e horários;
   - métricas operacionais;
   - Celery;
   - HubSpot e PostgreSQL/Supabase compartilhados;
   - RAG, knowledge e Salomão quando independentes da triagem removida.
5. Documente como responsabilidades futuras do n8n:
   - coleta de dados;
   - identificação e confirmação de identidade;
   - triagem;
   - produção da decisão que futuramente será entregue ao JUDAH.
6. Declare explicitamente que o contrato, webhook, outbox, reconciliação e
   endpoints dessa integração futura ainda não existem.
7. Não crie exemplos especulativos de payload, DTO, endpoint, workflow n8n,
   feature flag ou configuração futura.
8. Preserve migrations antigas e ADRs históricos como história intencional.
   Marque decisões antigas de Supervisor, Heimdall, FastMCP e AI_ROUTING_ENABLED
   como superseded quando aparecerem em documentação normativa.
9. Faça uma busca residual por Heimdall, Supervisor, triage, triagem,
   identificação, customer identity, FastMCP, AI_ROUTING_ENABLED,
   HUBSPOT_AI_TRIAGE e `/api/v1/ai/`. Classifique cada ocorrência restante como
   história intencional, teste negativo, migration histórica, falso positivo ou
   resíduo documental.
10. Não edite `docs/ai/n8n-inbound-integration-spec.md` sem confirmar primeiro
    se ele faz parte do escopo e se está versionado; pode ser trabalho local de
    outro colaborador.
11. Mantenha links relativos válidos, linguagem consistente e exemplos que
    correspondam aos routers e comandos reais.
12. Ao final, execute somente verificações documentais e read-only adequadas,
    incluindo busca de links quebrados se o projeto já possuir ferramenta para
    isso. Não invente uma nova stack de qualidade.

Entrega esperada:
- resumo das inconsistências encontradas;
- inventário dos documentos alterados ou removidos;
- justificativa para referências históricas mantidas;
- lista de links ou exemplos corrigidos;
- resultado das verificações;
- riscos e pontos que exigem decisão humana.

Não faça commit, push, PR, deploy ou alteração externa sem autorização explícita.
```
