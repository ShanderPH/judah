# Proposta concreta de preparação do release — sem aplicação

## Estado relido em 2026-10-02

- main remoto avançou de 0ca25b8 para 4ec547df0f3e21d9da727bec8a58b36cfdf0492c: `Delete hubspot-app directory`.
- #134 continua OPEN no HEAD 952ca9f.
- #135 foi aberto como draft no HEAD adfbe41, com o trabalho validado antes dessa exclusão. Não está liberado para merge.
- Railway produção: API e beat com deployment SUCCESS no SHA 4ec547d. Worker tem tentativa FAILED nesse SHA.
- Log do pre-deploy do worker em 2026-10-02T14:05:54Z confirma: `FileNotFoundError: /app/hubspot-app/src/app/webhooks/judah-webhooks-hsmeta.json`.
- A atualização/deploy de 4ec547d foi externa a esta execução. Nenhuma ação produtiva foi tomada por este agente.

## Configuração atual observada

- API (`judah`): `python manage.py railway_predeploy`.
- Worker (`judah-worker`): python -c que lê dois manifests de hubspot-app, compara com documentos base64 embutidos, faz assert ready e escreve checked_at/ready com timeout=86400.
- Beat: sem pre-deploy.

O comando atual do worker **não consulta HubSpot durante o pre-deploy**: os exports estão embutidos. Esses documentos não podem ser tratados como uma nova leitura autoritativa só porque o comando foi repetido. Não reutilizar o payload para renovar checked_at no release novo.

## Alteração proposta, pendente da decisão sobre a fonte dos manifests

1. Preservar apenas app-hsmeta.json e judah-webhooks-hsmeta.json como contratos internos em apps/integrations/hubspot/manifests/, sem restaurar hsproject.json ou o projeto de publicação removido por Felipe. Dados devem ser os bytes já versionados no baseline; hash permanece idêntico. Essa escolha foi submetida a Felipe e não foi aplicada.
2. Integrar o main atual na branch do hotfix, apontar os leitores/testes para a fonte aprovada, confirmar fingerprint e repetir gates no novo SHA.
3. Antes do release, obter do HubSpot a identidade do build realmente implantado e baixar seus exports oficiais. Confirmar a identidade novamente após o download. Não usar manifest desejado ou arquivo histórico como publicado.
4. O passo autoritativo do pre-deploy/release produz /tmp/published-webhooks.json e /tmp/published-app.json a partir desse download atual. Manter credenciais em secret storage e impedir log de tokens. A forma de disponibilizar esses exports no container é parte da configuração operacional a aprovar; não há credenciais novas no código.
5. Substituir apenas o writer inline do worker por:

```bash
python manage.py record_hubspot_webhook_readback --published-webhooks /tmp/published-webhooks.json --published-app /tmp/published-app.json
```

6. Preservar migrations/preflight existentes; não modificar modos enforce, roster, SAT, authority ou capacity.
7. Promover API/worker/beat para o mesmo SHA somente após aprovação específica. Confirmar schema/fingerprint/ready/TTL pela leitura operacional autorizada durante release.

## Aprovações ainda necessárias

- Felipe: fonte versionada dos contratos após remoção do projeto HubSpot.
- Felipe: configuração de aquisição/disponibilização dos exports publicados e substituição do pre-deploy.
- Felipe: merge/release/deploy em janela controlada. Este documento não autoriza produção.
