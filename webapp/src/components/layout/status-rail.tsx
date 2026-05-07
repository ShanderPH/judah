"use client";

import { Card, Spinner } from "@heroui/react";
import { Activity, ShieldCheck, Timer } from "lucide-react";
import { useCallback } from "react";

import { judahApi } from "@/src/lib/api/client";
import { useApiQuery } from "@/src/hooks/use-api-query";
import { formatInteger } from "@/src/lib/utils/format";

function StatusDot({ isPositive }: { isPositive: boolean }) {
  return (
    <span className="relative inline-flex size-2.5 items-center justify-center">
      <span
        className={`absolute inset-0 rounded-full opacity-50 blur-[3px] ${
          isPositive ? "bg-[var(--success)]" : "bg-[var(--danger)]"
        }`}
      />
      <span
        className={`relative size-2 rounded-full ${
          isPositive ? "bg-[var(--success)]" : "bg-[var(--danger)]"
        }`}
      />
    </span>
  );
}

export function StatusRail() {
  const fetchOverview = useCallback(async () => {
    const [health, queueStatus, businessHours] = await Promise.all([
      judahApi.getHealth(),
      judahApi.getQueueStatus(),
      judahApi.getBusinessHours(),
    ]);
    return { businessHours, health, queueStatus };
  }, []);
  const overview = useApiQuery(fetchOverview);

  return (
    <aside className="hidden flex-col gap-4 xl:sticky xl:top-3 xl:flex xl:max-h-[calc(100svh-1.5rem)] xl:overflow-y-auto judah-scroll">
      <Card variant="default" className="judah-glass rounded-[var(--radius-lg)] p-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="judah-mono text-[10px] uppercase tracking-[0.28em] text-[var(--muted)]">
              Status Rail
            </p>
            <h3 className="mt-1.5 text-xl font-semibold leading-tight">Servicos Judah</h3>
          </div>
          {overview.isLoading || overview.isRefreshing ? <Spinner size="sm" color="accent" /> : null}
        </div>
      </Card>

      {overview.data ? (
        <>
          <Card
            variant="secondary"
            className="judah-glass space-y-3 rounded-[var(--radius-lg)] p-5"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-[var(--accent)]" />
                <span className="text-sm font-medium">API principal</span>
              </div>
              <StatusDot isPositive={overview.data.health.status === "healthy"} />
            </div>
            <div className="judah-divider" />
            <div className="space-y-2 text-sm">
              {Object.entries(overview.data.health.checks ?? {}).map(([service, status]) => (
                <div key={service} className="flex items-center justify-between gap-3">
                  <span className="capitalize text-[var(--muted)]">{service}</span>
                  <span
                    className={`judah-mono text-[10px] uppercase tracking-[0.22em] ${
                      status === "ok" ? "text-[var(--success)]" : "text-[var(--danger)]"
                    }`}
                  >
                    {status === "ok" ? "ONLINE" : "DEGRADED"}
                  </span>
                </div>
              ))}
            </div>
          </Card>

          <Card
            variant="secondary"
            className="judah-glass space-y-3 rounded-[var(--radius-lg)] p-5"
          >
            <div className="flex items-center gap-2">
              <Activity className="size-4 text-[var(--accent)]" />
              <p className="text-sm font-medium">Fila automatica</p>
            </div>
            <div className="grid gap-2 text-sm">
              <Row label="Online" value={formatInteger(overview.data.queueStatus.online_agents)} />
              <Row
                label="Elegiveis"
                value={formatInteger(overview.data.queueStatus.eligible_agents)}
              />
              <Row
                label="Pendentes"
                value={formatInteger(overview.data.queueStatus.pending_queue_depth)}
                accent
              />
            </div>
          </Card>

          <Card
            variant="secondary"
            className="judah-glass space-y-3 rounded-[var(--radius-lg)] p-5"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Timer className="size-4 text-[var(--accent)]" />
                <p className="text-sm font-medium">Regime</p>
              </div>
              <StatusDot
                isPositive={overview.data.businessHours.is_currently_business_hours}
              />
            </div>
            <p className="judah-mono text-[10px] uppercase tracking-[0.22em] text-[var(--muted)]">
              {overview.data.businessHours.timezone_name}
            </p>
            <p className="text-sm leading-relaxed text-[var(--muted)]">
              {overview.data.businessHours.is_currently_business_hours
                ? "Dentro da janela configurada para atendimento."
                : "Fora da janela configurada para atendimento."}
            </p>
          </Card>
        </>
      ) : null}
    </aside>
  );
}

function Row({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/40 px-3 py-2">
      <span className="text-[var(--muted)]">{label}</span>
      <span
        className={`judah-mono text-sm ${accent ? "text-[var(--accent)]" : "text-[var(--foreground)]"}`}
      >
        {value}
      </span>
    </div>
  );
}
