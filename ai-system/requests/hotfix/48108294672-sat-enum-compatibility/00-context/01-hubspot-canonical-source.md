# SP-06 — fonte HubSpot canônica

Data da leitura: 2026-09-02 (America/Sao_Paulo).

## Escopo e segurança

- Leitura externa autorizada pelo owner.
- Nenhum upload, deploy, activation ou alteração HubSpot foi executado.
- URLs e identificadores de conta foram omitidos; nenhum secret foi lido ou registrado.
- O diretório não rastreado `Judah HubSpot Integration/` não foi alterado nem adicionado ao Git.

## Evidência remota

O readback do HubSpot Developer Project encontrou o projeto remoto `Judah HubSpot Integration` e o build publicado mais recente:

- build: `#20`;
- status: `SUCCESS`;
- platform version: `2025.2`;
- concluído em: `2026-08-25T01:13:50Z`;
- mensagem: `Enable conversation.newMessage webhook delivery to JUDAH`;
- subbuilds: application e webhooks em `SUCCESS`;
- inventário do build: 7 subscriptions legadas, 1 subscription `hubEvent` e 3 subscriptions inativas.

O candidato `inchurch-sandbox/` foi excluído: não existe projeto remoto com esse nome na conta autenticada. Os diretórios `hubspot-app/` e `Judah HubSpot Integration/` resolvem para o mesmo nome de projeto remoto, portanto o nome sozinho não distingue a origem do upload.

## Diff normalizado dos candidatos

| Candidato | Platform | Conversations scopes | `conversation.newMessage` | Legadas / inativas | Resultado |
|---|---:|---|---|---:|---|
| `hubspot-app/` | 2025.2 | ausentes | ausente | 3 / 0 | não corresponde ao build #20 |
| `Judah HubSpot Integration/` | 2025.2 | presentes | ativo | 7 / 3 | corresponde ao build #20 |
| `inchurch-sandbox/` | 2026.03 | ausentes | ausente | 1 / 0 | projeto remoto inexistente nesta conta |

Hashes SHA-256 dos manifests, para rastreabilidade sem publicar conteúdo sensível:

| Candidato | `hsproject.json` | app hsmeta | webhook hsmeta |
|---|---|---|---|
| `hubspot-app/` | `81a53aa90c5dce4de7eb6243e1e9424d60f0c14c86a2dec410d1f6a30e425240` | `3a0cfcbe1b0d21bf6b2cafbbdc484674c4880db1273c5e266b80f62a120e3f4f` | `5789f46bc4f026d616d508b3a07e616463afc873f45020e0cccaf7696287c446` |
| `Judah HubSpot Integration/` | `2062dee4e9aa07f976f23e99294d2556d2e8f576f0bdd2e10175d0564ec8652d` | `b8e959cec961fde4388e1bbec8e9d2c6057075181139ffd3f8cb01b91de3b208` | `c9015d122e3ce2ea314ec7457ea1dee75ce3925a388e60a490ce9ff2dbdd736c` |
| `inchurch-sandbox/` | `4b725bf059ec0aaad97a488d20aee6ee8ac65fee2fd5604319990f5d600f155b` | `3c8e4e6488bdca9836d1e27522e60c21cad348c5b8a45a544abbcb3fff9304b7` | `101f305cb267e7277f1a68975b8a690aa2839be2152f5a985e4cfdfefa63e0aa` |

## Decisão e blocker

SP-06 comprova que a fonte operacional do build #20 é semanticamente o conteúdo de `Judah HubSpot Integration/`. Contudo, esse diretório já era drift não rastreado pertencente ao usuário, e o plano proíbe adicioná-lo ou commitá-lo por conveniência.

Assim, INT-01 não pode cumprir sua exigência de alterar um manifesto canônico **versionado** sem uma decisão explícita de governança de fonte. O menor ajuste proposto é promover/sincronizar apenas os manifests necessários para um path rastreado aprovado, preservando o diretório não rastreado intacto. Até essa decisão, nenhuma configuração HubSpot deve ser alterada.

## Limitação da ferramenta

A validação local via HubSpotDev retornou `spawn npx ENOENT` antes de analisar os manifests. O readback remoto de builds e logs funcionou normalmente. Essa limitação não invalida a identificação do build, mas continua bloqueando o gate de validação local do manifesto até o ambiente `npx` do conector ser corrigido ou a CLI local equivalente ser usada.
