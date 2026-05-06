"use client";

import { Alert, Card } from "@heroui/react";
import {
  BrainCircuit,
  Clock3,
  GitCompareArrows,
  TrendingUp,
} from "lucide-react";

import { useApiQuery } from "@/src/hooks/use-api-query";
import { loadMetricsOverview } from "@/src/lib/api/overview";
import {
  formatInteger,
  formatMinutes,
  formatPercentFromRatio,
  formatSeconds,
} from "@/src/lib/utils/format";
import { DataState } from "@/src/components/ui/data-state";
import { MetricCard } from "@/src/components/ui/metric-card";
import { PageIntro } from "@/src/components/ui/page-intro";
import { SimpleBarChart, SimpleLineChart } from "@/src/components/ui/simple-chart";

export function MetricsOverview() {
  const overview = useApiQuery(loadMetricsOverview);

  if (overview.isLoading && !overview.data) return <DataState isLoading />;
  if (overview.error && !overview.data)
    return <DataState error={overview.error} onRetry={() => void overview.reload()} />;
  if (!overview.data) return <DataState isEmpty />;

  const { data } = overview;
  const latestReport = data.latestReport;
  const latestMetric = data.latestMetric;

  return (
    <section className="space-y-4 md:space-y-5">
      <PageIntro
        eyebrow="Operational Metrics"
        title="Metricas reais de fila, agentes e analytics."
        description="queue_performance_metrics, agent_metrics, agent_daily_time_logs, conversation_reassignments e analytics_daily_reports — todos expostos pelo backend e cruzados aqui."
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:gap-4 xl:grid-cols-4">
        <MetricCard
          icon={TrendingUp}
          label="Atribuidos"
          value={formatInteger(data.summary.totalAssigned)}
          detail="Total diario mais recente."
          tone="accent"
        />
        <MetricCard
          icon={Clock3}
          label="Espera media"
          value={formatSeconds(data.summary.avgWaitSeconds)}
          detail="Tempo medio diario na fila."
        />
        <MetricCard
          icon={GitCompareArrows}
          label="Tempo de tratamento"
          value={formatMinutes(data.summary.avgHandleMinutes)}
          detail="Calculado em closed_conversations."
        />
        <MetricCard
          icon={BrainCircuit}
          label="Deflexao AI"
          value={
            latestReport
              ? formatPercentFromRatio(latestReport.ai_deflection_rate / 100)
              : "--"
          }
          detail="Disponivel quando ha analytics_daily_reports."
          tone="success"
        />
      </div>

      <div className="grid gap-3 md:gap-4 xl:grid-cols-2">
        <Card
          variant="default"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Volume
            </p>
            <Card.Title className="text-xl tracking-tight">
              Atribuicoes por dia
            </Card.Title>
          </Card.Header>
          <SimpleBarChart
            data={[...data.queueMetrics]
              .reverse()
              .slice(-10)
              .map((item) => ({
                label: item.metric_date,
                value: item.total_assigned,
              }))}
          />
        </Card>

        <Card
          variant="default"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Latency
            </p>
            <Card.Title className="text-xl tracking-tight">
              Espera media na fila
            </Card.Title>
          </Card.Header>
          <SimpleLineChart
            data={[...data.queueMetrics]
              .reverse()
              .slice(-10)
              .map((item) => ({
                label: item.metric_date,
                value: Number(item.avg_queue_wait_seconds ?? 0) / 60,
              }))}
          />
        </Card>
      </div>

      <div className="grid gap-3 md:gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Card
          variant="secondary"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Reports Coverage
            </p>
            <Card.Title className="text-xl tracking-tight">Analytics diarios</Card.Title>
          </Card.Header>
          {data.reports.length === 0 ? (
            <Alert status="warning" className="rounded-[var(--radius-md)]">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Title>Sem analytics_daily_reports publicados</Alert.Title>
                <Alert.Description>
                  Tabela existe mas endpoints publicos nao retornaram registros.
                </Alert.Description>
              </Alert.Content>
            </Alert>
          ) : (
            <div className="space-y-2.5">
              {data.reports.slice(0, 5).map((report) => (
                <div
                  key={report.date}
                  className="rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 p-4 transition-transform duration-300 hover:-translate-y-0.5"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-medium">{report.date}</p>
                    <span className="judah-mono rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-[var(--accent)]">
                      SLA {formatPercentFromRatio(report.sla_compliance_rate / 100)}
                    </span>
                  </div>
                  <div className="judah-mono mt-3 grid grid-cols-2 gap-2 text-[11px] uppercase tracking-[0.16em] text-[var(--muted)]">
                    <p>Abertos: <span className="text-[var(--foreground)]">{formatInteger(report.total_tickets_opened)}</span></p>
                    <p>Resolvidos: <span className="text-[var(--foreground)]">{formatInteger(report.total_tickets_resolved)}</span></p>
                    <p>Escalados: <span className="text-[var(--foreground)]">{formatInteger(report.total_tickets_escalated)}</span></p>
                    <p>AI: <span className="text-[var(--foreground)]">{formatInteger(report.ai_handled_count)}</span></p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card
          variant="secondary"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Bottlenecks
            </p>
            <Card.Title className="text-xl tracking-tight">
              Falhas e gargalos
            </Card.Title>
          </Card.Header>

          {data.queueHealth.summary.issues.length === 0 &&
          data.queueHealth.summary.warnings.length === 0 ? (
            <p className="rounded-xl border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
              Nenhum gargalo emitido pelo endpoint de saude da fila.
            </p>
          ) : null}

          <div className="space-y-2.5">
            {data.queueHealth.summary.issues.map((issue) => (
              <Alert
                key={issue}
                status="danger"
                className="rounded-[var(--radius-md)]"
              >
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Title>Issue</Alert.Title>
                  <Alert.Description>{issue}</Alert.Description>
                </Alert.Content>
              </Alert>
            ))}
            {data.queueHealth.summary.warnings.map((warning) => (
              <Alert
                key={warning}
                status="warning"
                className="rounded-[var(--radius-md)]"
              >
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Title>Warning</Alert.Title>
                  <Alert.Description>{warning}</Alert.Description>
                </Alert.Content>
              </Alert>
            ))}
          </div>

          {latestMetric?.assignments_by_agent ? (
            <>
              <div className="judah-divider" />
              <div className="space-y-2">
                <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
                  Balanceamento mais recente
                </p>
                {Object.entries(latestMetric.assignments_by_agent).map(
                  ([ownerId, count]) => (
                    <div
                      key={ownerId}
                      className="flex items-center justify-between rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 px-4 py-3 text-sm"
                    >
                      <span className="judah-mono text-xs">{ownerId}</span>
                      <span className="judah-mono text-[var(--accent)]">
                        {count}
                      </span>
                    </div>
                  ),
                )}
              </div>
            </>
          ) : null}
        </Card>
      </div>

      <div className="grid gap-3 md:gap-4 xl:grid-cols-2">
        <Card
          variant="default"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Agent Metrics
            </p>
            <Card.Title className="text-xl tracking-tight">
              Performance individual ({data.agentMetricsSummary.period_days}d)
            </Card.Title>
            <Card.Description>
              {formatInteger(data.agentMetricsSummary.total_chats)} chats ·{" "}
              {formatInteger(data.agentMetricsSummary.total_chats_closed)} fechados ·{" "}
              CSAT {data.agentMetricsSummary.avg_csat.toFixed(1)} · TMA{" "}
              {formatMinutes(data.agentMetricsSummary.avg_handle_time_min)}
            </Card.Description>
          </Card.Header>
          <div className="space-y-2">
            {data.agentMetrics.length === 0 ? (
              <p className="rounded-xl border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
                Nenhum snapshot de agent_metrics nas ultimas tres semanas.
              </p>
            ) : null}
            {data.agentMetrics.slice(0, 8).map((row) => (
              <div
                key={row.id}
                className="flex items-center justify-between rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 px-4 py-3 text-sm"
              >
                <div>
                  <p className="judah-mono text-xs text-[var(--muted)]">
                    owner #{row.agent_id}
                  </p>
                  <p className="font-medium">
                    {formatInteger(row.total_chats)} chats ·{" "}
                    {formatInteger(row.chats_closed)} fechados
                  </p>
                </div>
                <div className="text-right">
                  <p className="judah-mono text-xs text-[var(--accent)]">
                    {formatMinutes(row.average_ticket_time_min)}
                  </p>
                  <p className="judah-mono text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                    CSAT {row.customer_satisfaction_avg ?? "--"}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card
          variant="default"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Reassignments
            </p>
            <Card.Title className="text-xl tracking-tight">
              Net transfer por agente (30d)
            </Card.Title>
            <Card.Description>
              Saldo entre tickets transferidos para fora e recebidos por
              transferencia. Uma negativa alta sugere agente saturado.
            </Card.Description>
          </Card.Header>
          <div className="space-y-2">
            {data.reassignmentsSummary.length === 0 ? (
              <p className="rounded-xl border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
                Nenhuma reatribuicao registrada nos ultimos 30 dias.
              </p>
            ) : null}
            {data.reassignmentsSummary.slice(0, 8).map((row) => (
              <div
                key={row.hubspot_owner_id}
                className="flex items-center justify-between rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 px-4 py-3 text-sm"
              >
                <div>
                  <p className="font-medium">
                    {row.agent_name ?? `owner #${row.hubspot_owner_id}`}
                  </p>
                  <p className="judah-mono text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                    in {row.transferred_in} · out {row.transferred_out}
                  </p>
                </div>
                <p
                  className={`judah-mono text-sm ${
                    row.net >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]"
                  }`}
                >
                  {row.net > 0 ? `+${row.net}` : row.net}
                </p>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </section>
  );
}
