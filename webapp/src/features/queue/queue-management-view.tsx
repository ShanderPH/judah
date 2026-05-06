"use client";

import {
  Alert,
  Button,
  Card,
  Input,
  Label,
  ListBox,
  Modal,
  Select,
  Tabs,
  TextField,
  useOverlayState,
} from "@heroui/react";
import { RefreshCcw, Search, Shuffle, UserCheck } from "lucide-react";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";

import { useApiQuery } from "@/src/hooks/use-api-query";
import { ApiClientError, judahApi } from "@/src/lib/api/client";
import {
  formatDateTime,
  formatSeconds,
  safeNumber,
} from "@/src/lib/utils/format";
import { cn } from "@/src/lib/utils/misc";
import { DataState } from "@/src/components/ui/data-state";
import { PageIntro } from "@/src/components/ui/page-intro";
import type { Agent } from "@/src/types/api";

type AssignedFilter = "all" | "open" | "closed";

interface AssignmentDraft {
  mode: "manual" | "force";
  ticketId: string;
  defaultAgentId?: string;
}

const filterOptions: Array<[AssignedFilter, string]> = [
  ["all", "Todos"],
  ["open", "Abertos"],
  ["closed", "Fechados"],
];

export function QueueManagementView() {
  const [tab, setTab] = useState("pending");
  const [search, setSearch] = useState("");
  const [assignedClosed, setAssignedClosed] = useState<AssignedFilter>("all");
  const [now, setNow] = useState(() => Date.now());
  const deferredSearch = useDeferredValue(search);

  useEffect(() => {
    const intervalId = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(intervalId);
  }, []);

  const pendingFetcher = useCallback(
    () => judahApi.listPendingConversations({ limit: 40, offset: 0 }),
    [],
  );
  const assignedFetcher = useCallback(
    () =>
      judahApi.listAssignedConversations({
        closed:
          assignedClosed === "all"
            ? undefined
            : assignedClosed === "closed",
        limit: 40,
        offset: 0,
      }),
    [assignedClosed],
  );
  const healthFetcher = useCallback(() => judahApi.getQueueHealth(), []);
  const agentsFetcher = useCallback(
    () => judahApi.listAgents({ limit: 100, offset: 0 }),
    [],
  );

  const pending = useApiQuery(pendingFetcher);
  const assigned = useApiQuery(assignedFetcher);
  const health = useApiQuery(healthFetcher);
  const agents = useApiQuery(agentsFetcher);

  const assignDialog = useOverlayState();
  const [draft, setDraft] = useState<AssignmentDraft | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [isSubmittingAction, setIsSubmittingAction] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<{
    tone: "success" | "danger";
    message: string;
  } | null>(null);

  const eligibleAgents: Agent[] = useMemo(() => {
    if (!agents.data) return [];
    return agents.data.results.filter((agent) => agent.is_active !== false);
  }, [agents.data]);

  const openAssign = (mode: AssignmentDraft["mode"], ticketId: string, defaultAgentId?: string) => {
    setDraft({ mode, ticketId, defaultAgentId });
    setSelectedAgent(defaultAgentId ?? null);
    setReason("");
    setActionFeedback(null);
    assignDialog.open();
  };

  const submitAssignment = async () => {
    if (!draft || !selectedAgent) {
      setActionFeedback({
        tone: "danger",
        message: "Selecione um agente para concluir a operacao.",
      });
      return;
    }
    setIsSubmittingAction(true);
    setActionFeedback(null);
    try {
      if (draft.mode === "manual") {
        const result = await judahApi.manualAssign({
          hubspot_ticket_id: draft.ticketId,
          agent_id: selectedAgent,
        });
        setActionFeedback({
          tone: "success",
          message: result.detail || "Ticket atribuido manualmente.",
        });
      } else {
        const result = await judahApi.forceReassign({
          hubspot_ticket_id: draft.ticketId,
          target_agent_id: selectedAgent,
          reason: reason.trim() || undefined,
        });
        setActionFeedback({
          tone: "success",
          message: result.detail || "Ticket reatribuido.",
        });
      }
      await Promise.all([pending.reload(), assigned.reload(), health.reload()]);
      assignDialog.close();
    } catch (error) {
      setActionFeedback({
        tone: "danger",
        message:
          error instanceof ApiClientError
            ? error.detail
            : error instanceof Error
            ? error.message
            : "Falha ao executar acao.",
      });
    } finally {
      setIsSubmittingAction(false);
    }
  };

  const pendingRows = useMemo(() => {
    const value = deferredSearch.toLowerCase();
    return (pending.data?.results ?? []).filter((item) =>
      [item.hubspot_ticket_id, item.contact_name, item.subject]
        .filter(Boolean)
        .some((field) => field?.toLowerCase().includes(value)),
    );
  }, [deferredSearch, pending.data]);

  const assignedRows = useMemo(() => {
    const value = deferredSearch.toLowerCase();
    return (assigned.data?.results ?? []).filter((item) =>
      [
        item.hubspot_ticket_id,
        item.agent_name,
        item.contact_name,
        item.subject,
      ]
        .filter(Boolean)
        .some((field) => field?.toLowerCase().includes(value)),
    );
  }, [assigned.data, deferredSearch]);

  return (
    <section className="space-y-4 md:space-y-5">
      <PageIntro
        eyebrow="Queue Operations"
        title="Gerenciamento visual da fila com diagnostico em tempo real."
        description="Combina fila pendente, historico de atribuicoes e snapshot do algoritmo, com atribuicao manual e force-reassign disponiveis para administradores."
      />

      {actionFeedback ? (
        <Alert
          status={actionFeedback.tone === "success" ? "success" : "danger"}
          className="rounded-[var(--radius-md)]"
        >
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>
              {actionFeedback.tone === "success" ? "Acao concluida" : "Falha"}
            </Alert.Title>
            <Alert.Description>{actionFeedback.message}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}

      <Card
        variant="default"
        className="judah-glass flex flex-col gap-4 rounded-[var(--radius-lg)] p-4 md:flex-row md:items-end md:justify-between md:p-5"
      >
        <div className="grid flex-1 gap-4 md:grid-cols-[minmax(0,1fr)_240px]">
          <TextField
            name="queue-search"
            value={search}
            onChange={setSearch}
            fullWidth
          >
            <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Buscar atendimento
            </Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-[var(--muted)]" />
              <Input
                placeholder="Ticket, assunto, contato ou agente"
                variant="secondary"
                className="pl-11"
              />
            </div>
          </TextField>

          <div className="space-y-1.5">
            <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Filtro
            </p>
            <div className="grid grid-cols-3 gap-1.5 rounded-[var(--field-radius)] border border-[var(--border)] bg-[var(--surface)]/50 p-1">
              {filterOptions.map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setAssignedClosed(value)}
                  className={cn(
                    "judah-focus-ring rounded-[calc(var(--field-radius)-0.25rem)] px-3 py-2 text-xs font-medium uppercase tracking-[0.18em] transition-all",
                    assignedClosed === value
                      ? "bg-[var(--accent)] text-[var(--accent-foreground)] shadow-[var(--field-shadow)]"
                      : "text-[var(--muted)] hover:bg-[var(--surface-secondary)] hover:text-[var(--foreground)]",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="tertiary" size="sm" onPress={() => void pending.reload()}>
            Pendentes
          </Button>
          <Button variant="tertiary" size="sm" onPress={() => void assigned.reload()}>
            Atribuidos
          </Button>
          <Button size="sm" onPress={() => void health.reload()}>
            <RefreshCcw className="size-4" />
            Diagnostico
          </Button>
        </div>
      </Card>

      <Tabs
        selectedKey={tab}
        onSelectionChange={(key) => setTab(String(key))}
        variant="secondary"
      >
        <Tabs.ListContainer>
          <Tabs.List
            aria-label="Queue views"
            className="judah-glass mask-fade-x flex gap-1 overflow-x-auto rounded-[var(--radius-md)] p-1.5"
          >
            <Tabs.Tab id="pending">
              Pendentes
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="assigned">
              Atribuidos
              <Tabs.Indicator />
            </Tabs.Tab>
            <Tabs.Tab id="health">
              Saude
              <Tabs.Indicator />
            </Tabs.Tab>
          </Tabs.List>
        </Tabs.ListContainer>

        <Tabs.Panel id="pending" className="pt-4">
          {pending.error && !pending.data ? (
            <DataState error={pending.error} onRetry={() => void pending.reload()} />
          ) : pendingRows.length === 0 && !pending.isLoading ? (
            <DataState
              isEmpty
              emptyMessage="Nao ha conversas pendentes para os filtros atuais."
            />
          ) : (
            <Card
              variant="default"
              className="judah-glass overflow-hidden rounded-[var(--radius-lg)]"
            >
              <div className="hidden gap-4 border-b border-[var(--border)] bg-[var(--surface-tertiary)]/40 px-5 py-3 text-[10px] uppercase tracking-[0.22em] text-[var(--muted)] md:grid md:grid-cols-[1.4fr_0.7fr_0.8fr_0.8fr]">
                <span>Atendimento</span>
                <span>Prioridade</span>
                <span>Entrada</span>
                <span>Espera</span>
              </div>
              <div className="divide-y divide-[var(--border)]/60">
                {pendingRows.map((item) => (
                  <div
                    key={item.id}
                    className="grid grid-cols-1 gap-3 px-5 py-4 text-sm transition-colors hover:bg-[var(--surface-secondary)]/60 md:grid-cols-[1.4fr_0.7fr_0.8fr_0.8fr]"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium">
                        {item.subject || "Ticket sem assunto"}
                      </p>
                      <p className="judah-mono mt-1 truncate text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                        {item.hubspot_ticket_id}
                      </p>
                      <p className="mt-1 truncate text-xs text-[var(--muted)]">
                        {item.contact_name ||
                          item.contact_email ||
                          "Contato nao informado"}
                      </p>
                    </div>
                    <p className="text-[var(--muted)] md:text-[var(--foreground)]">
                      <span className="judah-chip md:hidden">Prioridade:&nbsp;{item.priority || "normal"}</span>
                      <span className="hidden md:inline">{item.priority || "normal"}</span>
                    </p>
                    <p className="text-xs text-[var(--muted)] md:text-sm">
                      {formatDateTime(item.entered_queue_at)}
                    </p>
                    <div className="flex items-center justify-between gap-2 md:flex-col md:items-end">
                      <p className="judah-mono text-xs text-[var(--accent)] md:text-sm">
                        {formatSeconds(
                          (now - new Date(item.entered_queue_at).getTime()) /
                            1000,
                        )}
                      </p>
                      <Button
                        size="sm"
                        variant="tertiary"
                        onPress={() =>
                          openAssign("manual", item.hubspot_ticket_id)
                        }
                      >
                        <UserCheck className="size-3.5" />
                        Atribuir
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </Tabs.Panel>

        <Tabs.Panel id="assigned" className="pt-4">
          {assigned.error && !assigned.data ? (
            <DataState error={assigned.error} onRetry={() => void assigned.reload()} />
          ) : assignedRows.length === 0 && !assigned.isLoading ? (
            <DataState
              isEmpty
              emptyMessage="Nenhuma atribuicao retornou para os filtros atuais."
            />
          ) : (
            <Card
              variant="default"
              className="judah-glass overflow-hidden rounded-[var(--radius-lg)]"
            >
              <div className="hidden gap-4 border-b border-[var(--border)] bg-[var(--surface-tertiary)]/40 px-5 py-3 text-[10px] uppercase tracking-[0.22em] text-[var(--muted)] md:grid md:grid-cols-[1.2fr_0.9fr_0.7fr_0.7fr_0.8fr]">
                <span>Atendimento</span>
                <span>Responsavel</span>
                <span>Espera</span>
                <span>Atribuido</span>
                <span>Status</span>
              </div>
              <div className="divide-y divide-[var(--border)]/60">
                {assignedRows.map((item) => (
                  <div
                    key={item.id}
                    className="grid grid-cols-1 gap-3 px-5 py-4 text-sm transition-colors hover:bg-[var(--surface-secondary)]/60 md:grid-cols-[1.2fr_0.9fr_0.7fr_0.7fr_0.8fr]"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium">
                        {item.subject || "Ticket sem assunto"}
                      </p>
                      <p className="judah-mono mt-1 truncate text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                        {item.hubspot_ticket_id}
                      </p>
                      <p className="mt-1 truncate text-xs text-[var(--muted)]">
                        {item.contact_name || "Contato nao informado"}
                      </p>
                    </div>
                    <div className="min-w-0">
                      <p className="truncate">{item.agent_name}</p>
                      <p className="judah-mono mt-1 truncate text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                        {item.hubspot_owner_id}
                      </p>
                    </div>
                    <p className="judah-mono text-xs text-[var(--accent)]">
                      {formatSeconds(safeNumber(item.queue_wait_seconds))}
                    </p>
                    <p className="text-xs text-[var(--muted)]">
                      {formatDateTime(item.assigned_at)}
                    </p>
                    <div className="flex items-center justify-between gap-2 md:flex-col md:items-end">
                      <span
                        className={cn(
                          "judah-mono inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em]",
                          item.closed_at
                            ? "border-[var(--muted)]/40 text-[var(--muted)]"
                            : "border-[var(--success)]/40 text-[var(--success)]",
                        )}
                      >
                        <span
                          className={`size-1.5 rounded-full ${
                            item.closed_at
                              ? "bg-[var(--muted)]"
                              : "bg-[var(--success)]"
                          }`}
                        />
                        {item.closed_at ? "fechado" : "ativo"}
                      </span>
                      {!item.closed_at ? (
                        <Button
                          size="sm"
                          variant="tertiary"
                          onPress={() =>
                            openAssign("force", item.hubspot_ticket_id)
                          }
                        >
                          <Shuffle className="size-3.5" />
                          Reatribuir
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </Tabs.Panel>

        <Tabs.Panel id="health" className="pt-4">
          {health.error && !health.data ? (
            <DataState error={health.error} onRetry={() => void health.reload()} />
          ) : health.data ? (
            <div className="grid gap-3 md:gap-4 xl:grid-cols-2">
              <Card
                variant="secondary"
                className="judah-glass space-y-4 rounded-[var(--radius-lg)] p-6"
              >
                <Card.Header className="gap-1.5">
                  <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
                    Resumo
                  </p>
                  <Card.Title className="text-xl tracking-tight">
                    Diagnostico da fila
                  </Card.Title>
                </Card.Header>
                <div className="grid gap-2 text-sm">
                  <DiagRow
                    label="Total de agentes"
                    value={String(health.data.summary.total_agents)}
                  />
                  <DiagRow
                    label="Agentes elegiveis"
                    value={String(health.data.summary.eligible_agents)}
                  />
                  <DiagRow
                    label="Fila pendente"
                    value={String(health.data.summary.pending_queue_depth)}
                    accent
                  />
                </div>
              </Card>

              <Card
                variant="secondary"
                className="judah-glass space-y-3 rounded-[var(--radius-lg)] p-6"
              >
                <Card.Header className="gap-1.5">
                  <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
                    Acoes administrativas
                  </p>
                  <Card.Title className="text-xl tracking-tight">
                    Atribuicao manual e force-reassign
                  </Card.Title>
                </Card.Header>
                <Card.Description className="text-sm leading-relaxed">
                  Use a aba &ldquo;Pendentes&rdquo; para atribuir manualmente um ticket
                  parado na fila ao agente desejado, ou a aba &ldquo;Atribuidos&rdquo; para
                  forcar uma reatribuicao com auditoria registrada em
                  conversation_reassignments.
                </Card.Description>
                <ul className="space-y-2 text-sm leading-relaxed text-[var(--muted)]">
                  <li>• Manual: bypass do round-robin, registra assignment_logs com type &lsquo;manual&rsquo;.</li>
                  <li>• Force-reassign: decrementa o agente origem, incrementa destino e propaga para HubSpot.</li>
                  <li>• Endpoints novos: support/queue/manual-assign/ e support/queue/force-reassign/.</li>
                </ul>
              </Card>
            </div>
          ) : (
            <DataState isLoading />
          )}
        </Tabs.Panel>
      </Tabs>

      <Modal state={assignDialog}>
        <Modal.Backdrop>
          <Modal.Container size="md" placement="center">
            <Modal.Dialog>
              <Modal.Header className="gap-1.5">
                <Modal.Heading className="text-xl">
                  {draft?.mode === "manual"
                    ? "Atribuir ticket manualmente"
                    : "Forcar reatribuicao"}
                </Modal.Heading>
                <p className="text-sm text-[var(--muted)]">
                  {draft?.mode === "manual"
                    ? "Direciona um ticket pendente ao agente escolhido, ignorando o round-robin atual."
                    : "Move um ticket ja atribuido para outro agente. A acao e auditada em conversation_reassignments."}
                </p>
              </Modal.Header>
              <Modal.Body className="space-y-4">
                <div className="rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 px-4 py-3">
                  <p className="judah-mono text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]">
                    Ticket
                  </p>
                  <p className="font-medium">{draft?.ticketId}</p>
                </div>

                <Select
                  selectedKey={selectedAgent ?? undefined}
                  onSelectionChange={(key) => setSelectedAgent(String(key))}
                  fullWidth
                  isDisabled={agents.isLoading || eligibleAgents.length === 0}
                >
                  <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
                    Agente destino
                  </Label>
                  <Select.Trigger>
                    <Select.Value>
                      {selectedAgent
                        ? eligibleAgents.find((a) => a.id === selectedAgent)?.name ??
                          "Selecionar agente"
                        : "Selecionar agente"}
                    </Select.Value>
                    <Select.Indicator />
                  </Select.Trigger>
                  <Select.Popover>
                    <ListBox>
                      {eligibleAgents.map((agent) => (
                        <ListBox.Item
                          key={agent.id}
                          id={agent.id}
                          textValue={agent.name}
                        >
                          <div>
                            <p className="text-sm font-medium">{agent.name}</p>
                            <p className="text-xs text-[var(--muted)]">
                              {agent.status_enum} · {agent.current_simultaneous_chats}/
                              {agent.max_simultaneous_chats} chats
                            </p>
                          </div>
                        </ListBox.Item>
                      ))}
                    </ListBox>
                  </Select.Popover>
                </Select>

                {draft?.mode === "force" ? (
                  <TextField name="reason" value={reason} onChange={setReason} fullWidth>
                    <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
                      Motivo (opcional)
                    </Label>
                    <Input
                      variant="secondary"
                      placeholder="Ex: agente original ausente"
                    />
                  </TextField>
                ) : null}

                {actionFeedback?.tone === "danger" ? (
                  <Alert status="danger" className="rounded-[var(--radius-md)]">
                    <Alert.Indicator />
                    <Alert.Content>
                      <Alert.Title>Falha</Alert.Title>
                      <Alert.Description>{actionFeedback.message}</Alert.Description>
                    </Alert.Content>
                  </Alert>
                ) : null}
              </Modal.Body>
              <Modal.Footer className="flex justify-end gap-2">
                <Button variant="tertiary" onPress={() => assignDialog.close()}>
                  Cancelar
                </Button>
                <Button
                  isPending={isSubmittingAction}
                  onPress={() => void submitAssignment()}
                >
                  Confirmar
                </Button>
              </Modal.Footer>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </section>
  );
}

function DiagRow({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 px-4 py-3">
      <span className="text-[var(--muted)]">{label}</span>
      <span
        className={cn(
          "judah-mono text-sm",
          accent ? "text-[var(--accent)]" : "text-[var(--foreground)]",
        )}
      >
        {value}
      </span>
    </div>
  );
}
