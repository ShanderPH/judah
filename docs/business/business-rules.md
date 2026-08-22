# Regras de negócio

- Autoatribuição só ocorre quando habilitada e para a entrada autorizada no
  estágio NOVO do pipeline de suporte.
- Elegibilidade respeita disponibilidade, ausência, calendário, capacidade e
  autoridade do ambiente.
- Claims e eventos são idempotentes; retries não podem duplicar atribuições.
- `hubspot_owner_id`, capacidade ativa e filas devem convergir após atribuição e
  fechamento.
- Cada reabertura válida cria um novo ciclo mensurável sem apagar o histórico.
- Mensagens não produzem decisão de identidade ou triagem dentro do JUDAH.
- Identificação e triagem futuras pertencem ao n8n e dependem de contrato ainda
  não implementado.
