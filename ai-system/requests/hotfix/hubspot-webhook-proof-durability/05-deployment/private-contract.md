# Preparação do release com contrato privado — sem aplicação produtiva

A proposta anterior de restaurar manifests no backend público foi substituída. A branch já contém main/4ec547d, que removeu `hubspot-app/`, e #134/952ca9f.

## Fonte desejada

Definir `HUBSPOT_PROVIDER_CONFIG_JSON` como variável sealed no Railway para API, worker e beat, com a mesma revisão. A origem deve ficar versionada em repositório privado sob responsabilidade de Felipe. Não colocar conteúdo real em `.env.example`, fixtures, documentação pública, argumentos de shell ou logs.

O valor é um único objeto JSON com `contract_version` (string não vazia), `app` e `webhooks` (manifests completos com `uid` e `config`). A validação exige autenticação/scopes do app, target HTTPS, concorrência positiva e subscriptions ativas válidas. O exemplo fictício utilizado pelos testes vive em `core/settings/test.py`; não é uma configuração de release.

O fingerprint calcula SHA-256 de `{"contract_version": version, "app": app, "webhooks": webhooks}` com `sort_keys=True`, separadores `(',', ':')` e `ensure_ascii=True`. Qualquer mudança nos manifests completos, inclusive arrays ou revisão, exige readback novo; whitespace e ordem de chaves não mudam a identidade. Proofs do formato anterior de fingerprint não são reutilizáveis.

## Aquisição publicada independente

Antes do release autorizado, obter a identidade do build realmente implantado no HubSpot e baixar seus exports oficiais em armazenamento privado. Confirmar novamente a identidade após o download. Disponibilizar os exports recém-adquiridos no container do pre-deploy:

```bash
python manage.py record_hubspot_webhook_readback --published-webhooks /tmp/published-webhooks.json --published-app /tmp/published-app.json
```

Esse comando lê o contrato privado do ambiente, compara ambos os exports e grava um proof sem TTL após a verificação. Drift grava `ready=false` e retorna erro; configuração ou export inválido desativa evidência anterior. Stdout contém apenas schema, horário, ready e fingerprint. Não copiar desired para published nem reembalar export histórico como leitura nova.

Substituir o writer inline legado do worker por essa etapa, preservando migrations/preflight existentes. O writer antigo depende dos arquivos removidos e grava proof legado com TTL de 24h. A aquisição dos exports ainda precisa ser preparada no ambiente operacional; o comando de gravação não consulta o HubSpot por conta própria.

## Gate de release

Felipe deve autorizar e preparar o contrato privado, a aquisição autoritativa de exports e o release conjunto. Antes de liberar a versão, confirmar por leitura própria `schema_version=1`, `ready=true`, fingerprint correspondente ao contrato privado e Redis `TTL=-1`. API, worker e beat precisam executar o mesmo SHA e revisão do contrato.

Não desligar enforce/capabilities/roster/SAT/capacity/authority. Configuração ausente, proof legado, inválido ou incompatível continuam bloqueando. Redis flush/eviction continua exigindo novo readback.

Nenhuma variável Railway, publicação HubSpot, proof produtivo, merge ou deploy foi alterado nesta continuação.
