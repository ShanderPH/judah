"use client";

import {
  Alert,
  Button,
  Card,
  Modal,
  ProgressBar,
  Tabs,
  useOverlayState,
} from "@heroui/react";
import { Pencil, Plus, Power, RefreshCw, UserPlus } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { AgentForm } from "@/src/features/agents/agent-form";
import { useApiQuery } from "@/src/hooks/use-api-query";
import { ApiClientError, judahApi } from "@/src/lib/api/client";
import { loadAgentsAdminOverview } from "@/src/lib/api/overview";
import {
  formatDateTime,
  formatInteger,
  formatMinutes,
  formatPercentFromRatio,
  formatSeconds,
} from "@/src/lib/utils/format";
import { cn } from "@/src/lib/utils/misc";
import { DataState } from "@/src/components/ui/data-state";
import { MetricCard } from "@/src/components/ui/metric-card";
import { PageIntro } from "@/src/components/ui/page-intro";
import type {
  Agent,
  AgentStatus,
  CreateAgentPayload,
  UpdateAgentPayload,
} from "@/src/types/api";

const STATUS_TONE: Record<AgentStatus, string> = {
  online: "border-[var(--success)]/40 text-[var(--success)] bg-[var(--success)]/10",
  away: "border-[var(--warning)]/40 text-[var(--warning)] bg-[var(--warning)]/10",
  busy: "border-[var(--accent)]/40 text-[var(--accent)] bg-[var(--accent)]/10",
  offline: "border-[var(--muted)]/40 text-[var(--muted)] bg-[var(--surface)]/50",
};

function statusBadge(status: string) {
  const tone = STATUS_TONE[status as AgentStatus] ?? STATUS_TONE.offline;
  return (
    <span
      className={cn(
        "judah-mono inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em]",
        tone,
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          status === "online"
            ? "bg-[var(--success)]"
            : status === "away"
            ? "bg-[var(--warning)]"
            : status === "busy"
            ? "bg-[var(--accent)]"
            : "bg-[var(--muted)]",
        )}
      />
      {status}
    </span>
  );
}

export function AgentsOverview() {
  const overview = useApiQuery(loadAgentsAdminOverview);
  const editorState = useOverlayState();
  const [editing, setEditing] = useState<Agent | null>(null);
  const [tab, setTab] = useState("agents");
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{
    tone: "success" | "danger";
    message: string;
  } | null>(null);

  const openCreate = useCallback(() => {
    setEditing(null);
    setFeedback(null);
    editorState.open();
  }, [editorState]);

  const openEdit = useCallback(
    (agent: Agent) => {
      setEditing(agent);
      setFeedback(null);
      editorState.open();
    },
    [editorState],
  );

  const handleSubmit = useCallback(
    async (
      payload: CreateAgentPayload | UpdateAgentPayload,
      mode: "create" | "update",
    ) => {
      try {
        setActionPending("submit");
        if (mode === "create") {
          await judahApi.createAgent(payload as CreateAgentPayload);
          setFeedback({ tone: "success", message: "Agente criado com sucesso." });
        } else if (editing) {
          await judahApi.updateAgent(editing.id, payload as UpdateAgentPayload);
          setFeedback({ tone: "success", message: "Agente atualizado." });
        }
        await overview.reload();
        editorState.close();
      } catch (error) {
        setFeedback({
          tone: "danger",
          message:
            error instanceof ApiClientError
              ? error.detail
              : error instanceof Error
              ? error.message
              : "Falha ao salvar agente.",
        });
      } finally {
        setActionPending(null);
      }
    },
    [editing, editorState, overview],
  );

  const handleToggle = useCallback(
    async (agent: Agent) => {
      try {
        setActionPending(agent.id);
        if (agent.is_active === false) {
          await judahApi.reactivateAgent(agent.id);
          setFeedback({ tone: "success", message: `${agent.name} reativado.` });
        } else {
          await judahApi.inactivateAgent(agent.id);
          setFeedback({ tone: "success", message: `${agent.name} inativado.` });
        }
        await overview.reload();
      } catch (error) {
        setFeedback({
          tone: "danger",
          message:
            error instanceof ApiClientError
              ? error.detail
              : error instanceof Error
              ? error.message
              : "Falha ao alterar status do agente.",
        });
      } finally {
        setActionPending(null);
      }
    },
    [overview],
  );

  const summary = overview.data?.agentMetricsSummary;
  const totalAgents = overview.data?.agents.length ?? 0;
  const onlineAgents = useMemo(
    () => (overview.data?.agents ?? []).filter((a) => a.status_enum === "online").length,
    [overview.data],
  );
  const eligibleCount = overview.data?.queueHealth.summary.eligible_agents ?? 0;

  if (overview.isLoading && !overview.data) return <DataState isLoading />;
  if (overview.error && !overview.data)
    return <DataState error={overview.error} onRetry={() => void overview.reload()} />;
  if (!overview.data) return <DataState isEmpty />;

  const { agents } = overview.data;

  return (
    <section className="space-y-4 md:space-y-5">
      <PageIntro
        eyebrow="Agents Administration"
        title="Cadastro completo da equipe N1, capacidade e regras."
        description="Cria, edita, reativa ou inativa agentes do helpdesk e ajusta a capacidade simultanea sem precisar tocar no banco. Todas as alteracoes sao auditadas no log de assignments."
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:gap-4 xl:grid-cols-4">
        <MetricCard
          icon={UserPlus}
          label="Total de agentes"
          value={formatInteger(totalAgents)}
          detail={`${formatInteger(onlineAgents)} online agora`}
          tone="accent"
        />
        <MetricCard
          icon={Power}
          label="Elegiveis para fila"
          value={formatInteger(eligibleCount)}
          detail="Online + auto-assign + capacidade livre."
        />
        <MetricCard
          icon={RefreshCw}
          label="Tempo medio de tratamento"
          value={summary ? formatMinutes(summary.avg_handle_time_min) : "--"}
          detail={summary ? `${summary.period_days} dias` : "Aguardando dados."}
        />
        <MetricCard
          icon={Pencil}
          label="Resolucao media"
          value={
            summary ? formatPercentFromRatio(summary.avg_resolution_rate / 100) : "--"
          }
          detail={summary ? `CSAT medio ${summary.avg_csat.toFixed(1)}` : "--"}
          tone="success"
        />
      </div>

      {feedback ? (
        <Alert
          status={feedback.tone === "success" ? "success" : "danger"}
          className="rounded-[var(--radius-md)]"
        >
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>
              {feedback.tone === "success" ? "Pronto" : "Falha"}
            </Alert.Title>
            <Alert.Description>{feedback.message}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}

      <Tabs
        selectedKey={tab}
        onSelectionChange={(key) => setTab(String(key))}
        variant="secondary"
      >
        <Tabs.ListContainer>
          <Tabs.List
            aria-label="Agents views"
            className="judah-glass mask-fade-x flex gap-1 overflow-x-auto rounded-[var(--radius-md)] p-1.5"
          >
            <Tabs.Tab id="agents">
              Equipe
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="capacity">
              Capacidade
              <Tabs.Indicator />
            </Tabs.Tab>
          </Tabs.List>
        </Tabs.ListContainer>

        <Tabs.Panel id="agents" className="pt-4">
          <Card
            variant="default"
            className="judah-glass overflow-hidden rounded-[var(--radius-lg)]"
          >
            <div className="flex flex-col gap-3 border-b border-[var(--border)] bg-[var(--surface-tertiary)]/40 px-5 py-4 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
                  Roster
                </p>
                <h3 className="text-lg font-semibold tracking-tight">Agentes cadastrados</h3>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="tertiary" size="sm" onPress={() => void overview.reload()}>
                  <RefreshCw className="size-4" />
                  Atualizar
                </Button>
                <Button size="sm" onPress={openCreate}>
                  <Plus className="size-4" />
                  Novo agente
                </Button>
              </div>
            </div>
            <div className="hidden gap-4 border-b border-[var(--border)] bg-[var(--surface-tertiary)]/40 px-5 py-3 text-[10px] uppercase tracking-[0.22em] text-[var(--muted)] md:grid md:grid-cols-[1.4fr_0.7fr_0.7fr_0.7fr_0.6fr_0.6fr]">
              <span>Agente</span>
              <span>Status</span>
              <span>Em chats</span>
              <span>Auto-assign</span>
              <span>Ultima atribuicao</span>
              <span className="text-right">Acoes</span>
            </div>
            <div className="divide-y divide-[var(--border)]/60">
              {agents.length === 0 ? (
                <p className="px-5 py-6 text-sm text-[var(--muted)]">
                  Nenhum agente cadastrado ainda. Use o botao &ldquo;Novo agente&rdquo; para registrar o primeiro.
                </p>
              ) : null}
              {agents.map((agent) => {
                const capacityPct = Math.min(
                  100,
                  agent.max_simultaneous_chats > 0
                    ? (agent.current_simultaneous_chats / agent.max_simultaneous_chats) * 100
                    : 0,
                );
                const isActive = agent.is_active !== false;
                return (
                  <div
                    key={agent.id}
                    className="grid grid-cols-1 gap-3 px-5 py-4 text-sm md:grid-cols-[1.4fr_0.7fr_0.7fr_0.7fr_0.6fr_0.6fr]"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium">{agent.name}</p>
                      <p className="truncate text-xs text-[var(--muted)]">
                        {agent.agent_email}
                      </p>
                      <p className="judah-mono mt-1 truncate text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                        owner #{agent.hubspot_owner_id}
                        {agent.team ? ` · ${agent.team}` : ""}
                      </p>
                    </div>
                    <div className="flex items-center">
                      {statusBadge(agent.status_enum)}
                      {!isActive ? (
                        <span className="judah-mono ml-2 rounded-full border border-[var(--danger)]/40 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-[var(--danger)]">
                          inativo
                        </span>
                      ) : null}
                    </div>
                    <div className="space-y-1.5">
                      <p className="judah-mono text-xs">
                        {agent.current_simultaneous_chats}/{agent.max_simultaneous_chats}
                      </p>
                      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--default)]/60">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-[var(--accent)] to-[var(--brand-300)]"
                          style={{ width: `${capacityPct}%` }}
                        />
                      </div>
                    </div>
                    <p>
                      <span
                        className={cn(
                          "judah-mono rounded-full border px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em]",
                          agent.auto_assign_enabled
                            ? "border-[var(--success)]/40 text-[var(--success)]"
                            : "border-[var(--muted)]/40 text-[var(--muted)]",
                        )}
                      >
                        {agent.auto_assign_enabled ? "ativo" : "off"}
                      </span>
                    </p>
                    <p className="text-xs text-[var(--muted)]">
                      {formatDateTime(agent.last_assignment_at)}
                    </p>
                    <div className="flex flex-wrap justify-end gap-2">
                      <Button
                        size="sm"
                        variant="tertiary"
                        onPress={() => openEdit(agent)}
                      >
                        <Pencil className="size-3.5" />
                        Editar
                      </Button>
                      <Button
                        size="sm"
                        variant={isActive ? "secondary" : "primary"}
                        isPending={actionPending === agent.id}
                        onPress={() => void handleToggle(agent)}
                      >
                        <Power className="size-3.5" />
                        {isActive ? "Inativar" : "Reativar"}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel id="capacity" className="pt-4">
          <Card
            variant="default"
            className="judah-glass space-y-5 rounded-[var(--radius-lg)] p-6"
          >
            <Card.Header className="gap-1.5">
              <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
                Capacity Map
              </p>
              <Card.Title className="text-xl tracking-tight">
                Carga atual por agente
              </Card.Title>
              <Card.Description>
                Snapshot do quanto cada agente esta carregado em relacao ao limite simultaneo configurado.
              </Card.Description>
            </Card.Header>
            <div className="space-y-3">
              {agents.map((agent) => {
                const load =
                  agent.max_simultaneous_chats > 0
                    ? (agent.current_simultaneous_chats / agent.max_simultaneous_chats) * 100
                    : 0;
                return (
                  <div
                    key={agent.id}
                    className="rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 p-4"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate font-medium">{agent.name}</p>
                        <p className="judah-mono mt-1 truncate text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                          {agent.team || "sem time"} · {agent.timezone}
                        </p>
                      </div>
                      <span className="judah-mono text-sm text-[var(--accent)]">
                        {agent.current_simultaneous_chats}/{agent.max_simultaneous_chats}
                      </span>
                    </div>
                    <ProgressBar
                      aria-label={`Carga de ${agent.name}`}
                      value={Math.min(100, load)}
                      color={load >= 90 ? "warning" : "accent"}
                      size="sm"
                      className="mt-3"
                    >
                      <ProgressBar.Track className="rounded-full">
                        <ProgressBar.Fill className="rounded-full" />
                      </ProgressBar.Track>
                    </ProgressBar>
                    <p className="judah-mono mt-2 text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                      Online hoje: {formatSeconds(agent.online_time_seconds_today)} ·
                      Away: {formatSeconds(agent.away_time_seconds_today)}
                    </p>
                  </div>
                );
              })}
            </div>
          </Card>
        </Tabs.Panel>
      </Tabs>

      <Modal state={editorState}>
        <Modal.Backdrop>
          <Modal.Container size="lg" placement="center">
            <Modal.Dialog>
              <Modal.Header className="gap-1.5">
                <Modal.Heading className="text-xl">
                  {editing ? `Editar ${editing.name}` : "Novo agente"}
                </Modal.Heading>
                <p className="text-sm text-[var(--muted)]">
                  {editing
                    ? "Ajuste capacidade, status, time ou auto-assign."
                    : "Cadastre um novo agente N1 do suporte. O HubSpot owner ID precisa coincidir com o owner real para que o roteamento funcione."}
                </p>
              </Modal.Header>
              <Modal.Body>
                <AgentForm
                  initial={editing}
                  isPending={actionPending === "submit"}
                  onCancel={() => editorState.close()}
                  onSubmit={handleSubmit}
                />
              </Modal.Body>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </section>
  );
}
