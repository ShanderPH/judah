# 📊 Relatório de Performance - Atribuição Automática

**Data:** 15 de Abril de 2026  
**Horário do Relatório:** 10:30 (UTC-03:00)  
**Período Analisado:** 15/04/2026 (00:00 - 13:34 UTC)  
**Status:** Em andamento - Dados parciais do dia

---

## 📈 Resumo Executivo

| Métrica | Valor |
|---------|-------|
| **Total de Atribuições** | 26 |
| **Total de Tickets Atribuídos** | 23 |
| **Total de Conversas Encerradas** | 15 |
| **Agentes Ativos** | 4 |
| **Taxa Média de Conversão** | 65.17% |
| **Tempo Médio de Atendimento** | 25.74 min |
| **Tempo Médio de Espera na Fila** | 9,421s (~2.6h) |

---

## 👥 Performance por Agente

### Atribuições e Encerramentos

| Agente | ID HubSpot | Atribuições | Encerramentos | Taxa de Conversão | 1ª Atribuição | Última Atribuição |
|--------|-----------|-------------|---------------|-------------------|---------------|-------------------|
| **Fernanda Gomes** | 88093731 | 8 | 3 | 37.50% | 12:01 | 13:14 |
| **Raphael Loera** | 1372450856 | 8 | 6 | **75.00%** | 12:00 | 13:33 |
| **Esther Finotti** | 89931616 | 5 | 2 | 40.00% | 12:01 | 13:11 |
| **Nathan Rodrigues** | 88093732 | 5 | 1 | 20.00% | 12:13 | 13:34 |

---

### ⏱️ Tempo de Atendimento por Agente

| Agente | Média (min) | Mínimo (min) | Máximo (min) | Espera na Fila (seg) |
|--------|-------------|--------------|--------------|---------------------|
| **Fernanda Gomes** | 12.15 | 1.01 | 29.00 | 30.19 |
| **Raphael Loera** | 30.80 | 11.10 | 37.23 | 12,537.63 |
| **Esther Finotti** | 43.45 | 34.33 | 52.57 | 39.89 |
| **Nathan Rodrigues** | 0.75 | 0.75 | 0.75 | 37,657.02 |

> **Insight:** Nathan teve tempo de espera extremamente alto (10.5h), indicando possível ticket acumulado ou problema na atribuição. Raphael concentra o maior volume de espera na fila.

---

## 📊 Análise de Conversas Encerradas

### Visão Geral

| Métrica | Valor |
|---------|-------|
| **Total Encerradas** | 15 |
| **Agentes com Encerramentos** | 4 |
| **Encerrados por Agente** | 0 |
| **Encerrados pelo Sistema** | 15 |
| **Tempo Médio de Atendimento** | 25.74 min |
| **Tempo Mínimo** | 0.75 min |
| **Tempo Máximo** | 52.57 min |
| **Tempo Médio de Espera** | 9,421s (2.6h) |

### Distribuição por Prioridade

| Prioridade | Quantidade | Tempo Médio (min) |
|------------|-----------|-------------------|
| **LOW** | 11 (73%) | 28.01 |
| **N/A** | 3 (20%) | - |
| *(Vazio)* | 1 (7%) | 0.75 |

---

## ⏰ Distribuição Horária

### Atribuições

| Hora | Atribuições | % do Total |
|------|-------------|------------|
| 12:00 - 12:59 | 18 | 69.2% |
| 13:00 - 13:59 | 8 | 30.8% |

### Encerramentos

| Hora | Encerramentos | % do Total |
|------|---------------|------------|
| 12:00 - 12:59 | 3 | 20.0% |
| 15:00 - 15:59 | 9 | 60.0% |
| 16:00 - 16:59 | 3 | 20.0% |

---

## ⏳ Tempo de Espera na Fila (Detalhado)

| Métrica | Valor (segundos) | Valor (minutos) |
|---------|-----------------|-----------------|
| **Média** | 7,053s | 117.55 min |
| **Mínimo** | 8.53s | 0.14 min |
| **Máximo** | 37,657.65s | 627.63 min (10.5h) |
| **Mediana (P50)** | 57.45s | 0.96 min |
| **Percentil 95 (P95)** | 36,993.13s | 616.55 min (10.3h) |

> ⚠️ **Alerta:** A discrepância entre média (117 min) e mediana (0.96 min) indica presença de outliers com espera muito longa. Recomenda-se investigar tickets com espera >10h.

---

## 🔍 Insights e Recomendações

### ✅ Pontos Positivos

1. **Raphael Loera** apresenta a melhor taxa de conversão (75%), encerrando 6 dos 8 tickets atribuídos
2. **Esther Finotti** mantém tempo médio de atendimento mais longo (43.45 min), possível indicador de tickets mais complexos
3. O sistema está processando atribuições consistentemente ao longo do dia

### ⚠️ Pontos de Atenção

1. **Nathan Rodrigues**:
   - Menor taxa de conversão (20%)
   - Ticket encerrado em apenas 0.75 min (possível fechamento sem atendimento)
   - Tempo de espera na fila de 10.5h (outlier crítico)

2. **Tempo de Espera na Fila**:
   - Média de 117 min vs mediana de 0.96 min indica distribuição desbalanceada
   - P95 de 10.3h mostra que alguns tickets aguardam excessivamente

3. **Encerramentos**:
   - 100% dos encerramentos são pelo sistema (`closure_source: agent`)
   - Nenhum encerramento manual registrado por `closed_by_owner_id`

### 💡 Recomendações

1. **Investigar tickets com espera >10h** - Verificar se há falha na notificação ou atribuição
2. **Revisar processo de fechamento** - Diferenciar encerramentos automáticos de manuais
3. **Monitorar performance de Nathan** - Acompanhar se a baixa conversão é pontual ou padrão
4. **Implementar alerta de SLA** - Notificar quando tempo de espera na fila >30 min

---

## 📋 Detalhamento Técnico

### Tipo de Atribuição

| Tipo | Quantidade |
|------|-----------|
| Automática | 0 |
| Manual | 0 |
| *(Não classificado)* | 26 |

> **Nota:** A coluna `assignment_type` não está populada nos registros atuais. Recomenda-se revisar a lógica de inserção para capturar corretamente o tipo de atribuição.

### Pipeline Utilizado

| Pipeline | Tickets |
|----------|---------|
| 636459134 | 15 |

---

## 📁 Informações do Relatório

- **Base de Dados:** HelpdeskDB (Supabase)
- **Tabelas Consultadas:** `assignment_logs`, `closed_conversations`, `agents`
- **Timezone:** America/Sao_Paulo (UTC-03:00)
- **Última Atualização dos Dados:** 15/04/2026 13:34 UTC

---

*Relatório gerado automaticamente via MCP Supabase - Sistema Judah*
