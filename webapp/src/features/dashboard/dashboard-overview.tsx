"use client";

import { Alert, Card, Label, ProgressBar } from "@heroui/react";
import {
  Activity,
  AlarmClock,
  LifeBuoy,
  ServerCog,
  ShieldCheck,
} from "lucide-react";

import { useApiQuery } from "@/src/hooks/use-api-query";
import { loadDashboardOverview } from "@/src/lib/api/overview";
import {
  formatDateTime,
  formatInteger,
  formatMinutes,
  formatPercentFromRatio,
  formatSeconds,
  safeNumber,
} from "@/src/lib/utils/format";
import { DataState } from "@/src/components/ui/data-state";
import { MetricCard } from "@/src/components/ui/metric-card";
import { PageIntro } from "@/src/components/ui/page-intro";
import { SimpleBarChart } from "@/src/components/ui/simple-chart";

export function DashboardOverview() {
  const overview = useApiQuery(loadDashboardOverview);

  if (overview.isLoading && !overview.data) return <DataState isLoading />;
  if (overview.error && !overview.data)
    return <DataState error={overview.error} onRetry={() => void overview.reload()} />;
  if (!overview.data) return <DataState isEmpty />;

  const { data } = overview;
  const latestMetric = data.latestQueueMetric;
  const latestReport = data.latestReport;
  const queuePressure = Math.min(
    100,
    data.queueStatus.pending_queue_depth * 20 +
      data.queueStatus.eligible_agents * 10,
  );
  const apiHealthy = data.health.status === "healthy";

  return (
    <section className="space-y-4 md:space-y-5">
      <PageIntro
        eyebrow="Main Control Surface"
        title="Estado operacional do Judah em tempo real."
        description="Combina health check, snapshot da fila automatica, saude da distribuicao e relatorios diarios. Onde o backend nao publica granularidade suficiente, a interface deixa explicito."
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:gap-4 xl:grid-cols-4">
        <MetricCard
          icon={ServerCog}
          label="API"
          value={apiHealthy ? "Online" : "Degraded"}
          detail={`${Object.keys(data.health.checks).length} checks ativos`}
          tone={apiHealthy ? "success" : "danger"}
        />
        <MetricCard
          icon={Activity}
          label="Fila pendente"
          value={formatInteger(data.queueStatus.pending_queue_depth)}
          detail={`${formatInteger(data.queueStatus.eligible_agents)} agentes elegiveis`}
          tone="accent"
        />
        <MetricCard
          icon={AlarmClock}
          label="Espera media"
          value={formatSeconds(safeNumber(latestMetric?.avg_queue_wait_seconds))}
          detail="Media diaria do backend."
        />
        <MetricCard
          icon={ShieldCheck}
          label="SLA diario"
          value={
            latestReport
              ? formatPercentFromRatio(latestReport.sla_compliance_rate / 100)
              : "--"
          }
          detail="Disponivel quando ha analytics_daily_reports."
          tone="success"
        />
      </div>

      <div className="grid gap-3 md:gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.6fr)]">
        <Card
          variant="default"
          className="judah-glass space-y-5 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Operational Board
            </p>
            <Card.Title className="text-2xl tracking-tight">
              Pressao da fila + throughput recente
            </Card.Title>
          </Card.Header>

          <ProgressBar
            aria-label="Queue pressure"
            value={queuePressure}
            color={queuePressure > 70 ? "warning" : "accent"}
            size="md"
          >
            <Label className="judah-mono text-[10px] uppercase tracking-[0.22em] text-[var(--muted)]">
              Queue pressure
            </Label>
            <ProgressBar.Output className="judah-mono text-xs text-[var(--foreground)]" />
            <ProgressBar.Track className="rounded-full">
              <ProgressBar.Fill className="rounded-full" />
            </ProgressBar.Track>
          </ProgressBar>

          <div className="grid gap-3 sm:grid-cols-3">
            <Stat
              label="Online"
              value={formatInteger(data.queueHealth.summary.online_agents)}
            />
            <Stat
              label="Atribuidos hoje"
              value={formatInteger(latestMetric?.total_assigned ?? 0)}
            />
            <Stat
              label="Fechados hoje"
              value={formatInteger(latestMetric?.total_closed ?? 0)}
            />
          </div>

          <SimpleBarChart
            data={[...data.queueMetrics].reverse().map((item) => ({
              label: item.metric_date,
              value: item.total_assigned,
            }))}
          />
        </Card>

        <Card
          variant="secondary"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              System Notes
            </p>
            <Card.Title className="text-xl tracking-tight">
              Saude da operacao
            </Card.Title>
          </Card.Header>

          {data.queueHealth.summary.issues.length === 0 &&
          data.queueHealth.summary.warnings.length === 0 ? (
            <Alert status="success" className="rounded-[var(--radius-md)]">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Title>Sem alertas criticos</Alert.Title>
                <Alert.Description>
                  Nenhum bloqueio reportado pelo endpoint de saude.
                </Alert.Description>
              </Alert.Content>
            </Alert>
          ) : null}

          {data.queueHealth.summary.issues.map((issue) => (
            <Alert key={issue} status="danger" className="rounded-[var(--radius-md)]">
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

          <div className="judah-divider" />
          <div className="space-y-2 text-sm leading-relaxed text-[var(--muted)]">
            <p>
              <span className="text-[var(--foreground)]">Business hours:</span>{" "}
              {data.businessHours.is_currently_business_hours
                ? "Ativo"
                : "Fora da janela"}
            </p>
            <p>
              <span className="text-[var(--foreground)]">Ultima amostra:</span>{" "}
              {formatDateTime(data.queueHealth.timestamp)}
            </p>
            <p>
              <span className="text-[var(--foreground)]">Tempo medio:</span>{" "}
              {latestReport
                ? formatMinutes(latestReport.avg_resolution_hours * 60)
                : "--"}
            </p>
          </div>
        </Card>
      </div>

      <div className="grid gap-3 md:gap-4 xl:grid-cols-2">
        <Card
          variant="secondary"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Backend Checks
            </p>
            <Card.Title className="text-xl tracking-tight">
              Servicos monitorados
            </Card.Title>
          </Card.Header>
          <div className="space-y-2 text-sm">
            {Object.entries(data.health.checks).map(([name, status]) => (
              <div
                key={name}
                className="flex items-center justify-between rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 px-4 py-3"
              >
                <span className="capitalize">{name}</span>
                <span
                  className={`judah-mono text-[10px] uppercase tracking-[0.22em] ${
                    status === "ok"
                      ? "text-[var(--success)]"
                      : "text-[var(--danger)]"
                  }`}
                >
                  {status}
                </span>
              </div>
            ))}
          </div>
        </Card>

        <Card
          variant="secondary"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Recent Signals
            </p>
            <Card.Title className="text-xl tracking-tight">
              Ultimas atribuicoes
            </Card.Title>
          </Card.Header>
          <div className="space-y-2.5">
            {data.queueHealth.last_assignments.slice(0, 5).map((assignment) => (
              <div
                key={assignment.ticket_id}
                className="rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 p-4 transition-transform duration-300 hover:-translate-y-0.5"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {assignment.agent_name}
                    </p>
                    <p className="judah-mono mt-1 truncate text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                      {assignment.ticket_id}
                    </p>
                  </div>
                  <p className="judah-mono text-xs text-[var(--accent)]">
                    {formatSeconds(assignment.queue_wait_seconds)}
                  </p>
                </div>
              </div>
            ))}
            {data.queueHealth.last_assignments.length === 0 ? (
              <p className="rounded-xl border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
                Nenhuma atribuicao recente retornada pelo backend.
              </p>
            ) : null}
          </div>
        </Card>
      </div>

      <Card
        variant="transparent"
        className="judah-glass rounded-[var(--radius-md)] p-5"
      >
        <div className="flex items-start gap-3">
          <span className="grid size-9 place-items-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--accent)]">
            <LifeBuoy className="size-4" />
          </span>
          <div className="text-sm leading-relaxed text-[var(--muted)]">
            <p>
              <span className="text-[var(--foreground)]">
                {formatInteger(data.agents.length)}
              </span>{" "}
              agentes cadastrados ·{" "}
              <span className="text-[var(--foreground)]">
                {formatInteger(data.agentMetricsSummary.total_chats)}
              </span>{" "}
              chats nos ultimos {data.agentMetricsSummary.period_days} dias ·
              CSAT medio{" "}
              <span className="text-[var(--foreground)]">
                {data.agentMetricsSummary.avg_csat.toFixed(1)}
              </span>
              .
            </p>
            <p className="mt-1">
              Gestao completa de agentes, capacidade e atribuicoes manuais
              disponivel nas paginas de Agentes e Fila.
            </p>
          </div>
        </div>
      </Card>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1.5 rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 p-4">
      <p className="judah-mono text-[10px] uppercase tracking-[0.22em] text-[var(--muted)]">
        {label}
      </p>
      <p className="text-2xl font-semibold tracking-tight md:text-3xl">{value}</p>
    </div>
  );
}
