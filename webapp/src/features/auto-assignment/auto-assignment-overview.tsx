"use client";

import { Alert, Button, Card } from "@heroui/react";
import {
  CalendarClock,
  CircleSlash2,
  RefreshCcw,
  Repeat,
  Shuffle,
  Users,
} from "lucide-react";
import { useState } from "react";

import { useApiQuery } from "@/src/hooks/use-api-query";
import { judahApi } from "@/src/lib/api/client";
import { loadAutoAssignmentOverview } from "@/src/lib/api/overview";
import {
  formatDateTime,
  formatInteger,
  formatSeconds,
  safeNumber,
} from "@/src/lib/utils/format";
import { DataState } from "@/src/components/ui/data-state";
import { MetricCard } from "@/src/components/ui/metric-card";
import { PageIntro } from "@/src/components/ui/page-intro";

export function AutoAssignmentOverview() {
  const overview = useApiQuery(loadAutoAssignmentOverview);
  const [syncResult, setSyncResult] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);

  if (overview.isLoading && !overview.data) return <DataState isLoading />;
  if (overview.error && !overview.data)
    return <DataState error={overview.error} onRetry={() => void overview.reload()} />;
  if (!overview.data) return <DataState isEmpty />;

  const { data } = overview;
  const latestMetric = data.latestMetric;

  const syncNovo = async () => {
    setIsSyncing(true);
    setSyncResult(null);
    try {
      const result = await judahApi.syncNovo();
      setSyncResult(
        `Sync executado: ${result.created} criados, ${result.skipped} ignorados, ${result.already_assigned} ja atribuidos.`,
      );
      await overview.reload();
    } catch (error) {
      setSyncResult(
        error instanceof Error ? error.message : "Falha ao sincronizar.",
      );
    } finally {
      setIsSyncing(false);
    }
  };

  const businessActive = data.businessHours.is_currently_business_hours;
  const reassignmentsRecent = data.reassignments.slice(0, 6);

  return (
    <section className="space-y-4 md:space-y-5">
      <PageIntro
        eyebrow="Assignment Intelligence"
        title="Observabilidade da autoatribuicao em produção."
        description="Mostra disponibilidade, capacidade, balanceamento, horarios, calendarios especiais e historico de transferencias com auditoria completa."
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:gap-4 xl:grid-cols-4">
        <MetricCard
          icon={Users}
          label="Agentes elegiveis"
          value={formatInteger(data.queueHealth.summary.eligible_agents)}
          detail={`${formatInteger(data.queueHealth.summary.online_agents)} online`}
          tone="accent"
        />
        <MetricCard
          icon={Shuffle}
          label="Distribuicoes diarias"
          value={formatInteger(latestMetric?.total_assigned ?? 0)}
          detail="queue_performance_metrics."
        />
        <MetricCard
          icon={CalendarClock}
          label="Business hours"
          value={businessActive ? "Ativo" : "Fora"}
          detail={data.businessHours.timezone_name}
          tone={businessActive ? "success" : "warning"}
        />
        <MetricCard
          icon={CircleSlash2}
          label="P95 fila"
          value={formatSeconds(safeNumber(latestMetric?.p95_queue_wait_seconds))}
          detail="Percentil alto da espera diaria."
        />
      </div>

      <div className="grid gap-3 md:gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <Card
          variant="default"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <div className="flex flex-col items-start justify-between gap-4 md:flex-row md:items-center">
            <Card.Header className="gap-1.5 p-0">
              <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
                Administrative Trigger
              </p>
              <Card.Title className="text-xl tracking-tight md:text-2xl">
                Sincronizar tickets em NOVO
              </Card.Title>
            </Card.Header>
            <Button isPending={isSyncing} onPress={() => void syncNovo()}>
              <RefreshCcw className="size-4" />
              Sync NOVO
            </Button>
          </div>
          <Card.Description className="text-sm leading-relaxed">
            Acao administrativa real exposta pela API. Backfill dos tickets em
            NOVO + dispara o fluxo normal de processamento.
          </Card.Description>
          {syncResult ? (
            <Alert status="accent" className="rounded-[var(--radius-md)]">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Title>Resultado da sincronizacao</Alert.Title>
                <Alert.Description>{syncResult}</Alert.Description>
              </Alert.Content>
            </Alert>
          ) : null}
        </Card>

        <Card
          variant="secondary"
          className="judah-glass space-y-3 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Recent Transfers
            </p>
            <Card.Title className="text-xl tracking-tight">
              Reatribuicoes recentes
            </Card.Title>
          </Card.Header>
          {reassignmentsRecent.length === 0 ? (
            <p className="rounded-xl border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
              Nenhuma reatribuicao registrada nas ultimas duas semanas.
            </p>
          ) : (
            <div className="space-y-2.5">
              {reassignmentsRecent.map((reassignment) => (
                <div
                  key={reassignment.id}
                  className="rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="judah-mono text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                      ticket {reassignment.hubspot_ticket_id}
                    </p>
                    <span className="judah-mono rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-[var(--accent)]">
                      {reassignment.reassignment_source}
                    </span>
                  </div>
                  <p className="mt-2 text-sm">
                    <span className="text-[var(--muted)]">
                      {reassignment.from_agent_name ?? "—"}
                    </span>{" "}
                    <Repeat className="inline size-3 text-[var(--accent)]" />{" "}
                    <span className="font-medium">
                      {reassignment.to_agent_name ?? "—"}
                    </span>
                  </p>
                  <p className="judah-mono mt-1 text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                    {formatDateTime(reassignment.reassigned_at)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-3 md:gap-4 xl:grid-cols-2">
        <Card
          variant="secondary"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Eligible Pool
            </p>
            <Card.Title className="text-xl tracking-tight">
              Agentes aptos
            </Card.Title>
          </Card.Header>
          <div className="space-y-2.5">
            {data.queueHealth.eligible_agents.map((agent) => (
              <div
                key={agent.id}
                className="rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 p-4 transition-transform duration-300 hover:-translate-y-0.5"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{agent.name}</p>
                    <p className="truncate text-xs text-[var(--muted)]">
                      {agent.email}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <span className="judah-mono rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-[var(--accent)]">
                      {agent.current_chats}/{agent.max_chats}
                    </span>
                    <span className="judah-mono text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                      {agent.is_last_assigned ? "Ultimo" : "Pool"}
                    </span>
                  </div>
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[var(--default)]/60">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-[var(--accent)] to-[var(--brand-300)]"
                    style={{
                      width: `${Math.min(
                        100,
                        (agent.current_chats /
                          Math.max(agent.max_chats, 1)) *
                          100,
                      )}%`,
                    }}
                  />
                </div>
              </div>
            ))}
            {data.queueHealth.eligible_agents.length === 0 ? (
              <p className="rounded-xl border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
                Nenhum agente elegivel neste snapshot.
              </p>
            ) : null}
          </div>
        </Card>

        <Card
          variant="secondary"
          className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6 md:p-7"
        >
          <Card.Header className="gap-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Operational Rules
            </p>
            <Card.Title className="text-xl tracking-tight">
              Horario e sobreposicoes
            </Card.Title>
          </Card.Header>
          <div className="space-y-1.5 text-sm leading-relaxed text-[var(--muted)]">
            <p>
              <span className="text-[var(--foreground)]">Configuracao ativa:</span>{" "}
              {data.businessHours.name}
            </p>
            <p>
              <span className="text-[var(--foreground)]">Ultima amostra:</span>{" "}
              {formatDateTime(data.queueHealth.timestamp)}
            </p>
          </div>
          <div className="judah-divider" />
          <div className="space-y-2.5">
            {data.specialSchedules.map((schedule) => (
              <div
                key={schedule.id}
                className="rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 p-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium">{schedule.date}</p>
                  <span className="judah-mono rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-[var(--accent)]">
                    {schedule.schedule_type}
                  </span>
                </div>
                <p className="mt-2 text-sm text-[var(--muted)]">
                  {schedule.reason || "Sem justificativa informada."}
                </p>
              </div>
            ))}
            {data.specialSchedules.length === 0 ? (
              <p className="rounded-xl border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
                Nenhuma sobreposicao especial cadastrada.
              </p>
            ) : null}
          </div>
        </Card>
      </div>
    </section>
  );
}
