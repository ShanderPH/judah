"use client";

import { Alert, Button, Card, Modal, Tabs } from "@heroui/react";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  RefreshCcw,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { DataState } from "@/src/components/ui/data-state";
import { useApiQuery } from "@/src/hooks/use-api-query";
import { judahApi } from "@/src/lib/api/client";
import {
  CAPABILITIES,
  hasCapability,
} from "@/src/lib/auth/access-policy";
import { useSession } from "@/src/lib/auth/session-context";
import { cn } from "@/src/lib/utils/misc";
import type {
  HelpdeskCalendarOccurrence,
  HelpdeskCalendarRule,
} from "@/src/types/api";

import {
  isoDate,
  monthDays,
  occurrenceFor,
  periodLabel,
  shiftPeriod,
  weekDays,
  type CalendarView,
} from "./calendar-utils";
import { RuleWizard } from "./rule-wizard";

const weekdays = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const stateLabel = {
  OPEN: "Aberto",
  CLOSED: "Fechado",
  ABSENCE: "Ausência",
} as const;

export function HelpdeskCalendarView() {
  const { user } = useSession();
  const canManage = hasCapability(user, CAPABILITIES.supportCalendarManage);
  const [view, setView] = useState<CalendarView>("month");
  const [cursor, setCursor] = useState(() => new Date());
  const [selectedDate, setSelectedDate] = useState(() => isoDate(new Date()));
  const [detailOpen, setDetailOpen] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<HelpdeskCalendarRule | null>(null);
  const [wizardDate, setWizardDate] = useState<string | null>(null);
  const query = useMemo(() => {
    const periodDays = view === "month" ? monthDays(cursor) : weekDays(cursor);
    return {
      from: isoDate(periodDays[0]),
      to: isoDate(periodDays[periodDays.length - 1]),
      view,
    };
  }, [cursor, view]);
  const fetchCalendar = useCallback(
    (signal: AbortSignal) => judahApi.getHelpdeskCalendar(query, { signal }),
    [query],
  );
  const calendar = useApiQuery(fetchCalendar);
  const selectedOccurrence =
    calendar.data?.occurrences.find((item) => item.date === selectedDate) ?? null;
  const selectedRule = selectedOccurrence?.source_rule_id
    ? calendar.data?.rules.find((rule) => rule.id === selectedOccurrence.source_rule_id) ?? null
    : null;
  const days = view === "month" ? monthDays(cursor) : weekDays(cursor);

  const reload = async () => {
    await calendar.reload();
  };

  const openNewRule = (date?: string) => {
    setEditingRule(null);
    setWizardDate(date ?? null);
    setDetailOpen(false);
    setWizardOpen(true);
  };

  const openRuleEditor = (rule: HelpdeskCalendarRule) => {
    setEditingRule(rule);
    setWizardDate(null);
    setDetailOpen(false);
    setWizardOpen(true);
  };

  return (
    <section className="space-y-4 md:space-y-5">
      <Card variant="default" className="judah-glass rounded-[var(--radius-lg)]">
        <Card.Header className="flex-col gap-5 p-5 md:p-6">
          <div className="flex w-full flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-3xl">
              <p className="judah-mono text-[10px] uppercase tracking-[0.28em] text-[var(--accent)]">
                Helpdesk Operations
              </p>
              <Card.Title className="mt-2 text-2xl md:text-3xl">
                Calendário Helpdesk
              </Card.Title>
              <Card.Description className="mt-2 max-w-2xl text-sm leading-6">
                Horários de atendimento, pausas e eventualidades em uma única visão operacional.
              </Card.Description>
            </div>
            {canManage ? (
              <Button onPress={() => openNewRule()}>
                <Plus className="size-4" />
                Nova regra
              </Button>
            ) : null}
          </div>

          <div className="judah-divider w-full" />

          <div className="flex w-full flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <p className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
                Período visível
              </p>
              <h2 className="mt-1 text-xl font-semibold capitalize">
                {periodLabel(cursor, view)}
              </h2>
              <p className="mt-1 text-xs text-[var(--muted)]">
                {calendar.data?.timezone ?? "America/Sao_Paulo"} · versão{" "}
                {calendar.data?.version ?? "—"}
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <Tabs
                selectedKey={view}
                onSelectionChange={(key) => setView(String(key) as CalendarView)}
                variant="secondary"
              >
                <Tabs.List aria-label="Visualização do calendário">
                  <Tabs.Tab id="month">
                    Mensal
                    <Tabs.Indicator />
                  </Tabs.Tab>
                  <Tabs.Tab id="week">
                    Semanal
                    <Tabs.Indicator />
                  </Tabs.Tab>
                </Tabs.List>
              </Tabs>
              <div className="flex items-center gap-2">
                <Button variant="tertiary" size="sm" onPress={() => setCursor(new Date())}>
                  Hoje
                </Button>
                <Button
                  isIconOnly
                  variant="tertiary"
                  size="sm"
                  aria-label="Período anterior"
                  onPress={() => setCursor(shiftPeriod(cursor, view, -1))}
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <Button
                  isIconOnly
                  variant="tertiary"
                  size="sm"
                  aria-label="Próximo período"
                  onPress={() => setCursor(shiftPeriod(cursor, view, 1))}
                >
                  <ChevronRight className="size-4" />
                </Button>
                <Button
                  isIconOnly
                  variant="tertiary"
                  size="sm"
                  aria-label="Atualizar calendário"
                  onPress={() => void reload()}
                >
                  <RefreshCcw
                    className={cn("size-4", calendar.isRefreshing && "animate-spin")}
                  />
                </Button>
              </div>
            </div>
          </div>
        </Card.Header>
      </Card>

      {calendar.data?.degraded ? (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Visão degradada</Alert.Title>
            <Alert.Description>
              Algumas regras não puderam ser expandidas. Confirme antes de publicar uma alteração.
            </Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}

      {calendar.error && !calendar.data ? (
        <DataState error={calendar.error} onRetry={() => void reload()} />
      ) : calendar.isLoading ? (
        <DataState isLoading />
      ) : (
        <CalendarGrid
          days={days}
          cursor={cursor}
          view={view}
          occurrences={calendar.data?.occurrences ?? []}
          selectedDate={selectedDate}
          onSelect={(date) => {
            setSelectedDate(date);
            setDetailOpen(true);
          }}
        />
      )}

      <RuleList
        rules={calendar.data?.rules ?? []}
        canManage={canManage}
        onCreate={() => openNewRule()}
        onEdit={openRuleEditor}
        onDeleted={() => void reload()}
      />

      <DayDetailModal
        isOpen={detailOpen}
        date={selectedDate}
        occurrence={selectedOccurrence}
        rule={selectedRule}
        canManage={canManage}
        onOpenChange={setDetailOpen}
        onCreate={() => openNewRule(selectedDate)}
        onEdit={openRuleEditor}
      />

      <RuleWizard
        key={editingRule?.id ?? `${wizardDate ?? "new"}-${wizardOpen ? "open" : "closed"}`}
        isOpen={wizardOpen}
        initialRule={editingRule}
        initialDate={wizardDate}
        onClose={() => {
          setWizardOpen(false);
          setEditingRule(null);
          setWizardDate(null);
        }}
        onSaved={() => void reload()}
      />
    </section>
  );
}

function RuleList({
  rules,
  canManage,
  onCreate,
  onEdit,
  onDeleted,
}: {
  rules: HelpdeskCalendarRule[];
  canManage: boolean;
  onCreate: () => void;
  onEdit: (rule: HelpdeskCalendarRule) => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const deactivate = async (rule: HelpdeskCalendarRule) => {
    if (!window.confirm(`Desativar a regra “${rule.name}”?`)) return;
    setBusy(rule.id);
    try {
      await judahApi.deleteHelpdeskCalendarRule(rule.id, rule.version);
      onDeleted();
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card variant="default" className="judah-glass rounded-[var(--radius-lg)]">
      <Card.Header className="flex-row items-center justify-between gap-4 p-4 md:p-5">
        <div>
          <Card.Title>Regras publicadas</Card.Title>
          <Card.Description className="mt-1">
            Horários recorrentes e eventualidades que alimentam a triagem.
          </Card.Description>
        </div>
        <span className="shrink-0 text-xs text-[var(--muted)]">{rules.length} ativa(s)</span>
      </Card.Header>
      <Card.Content className="px-4 pb-4 md:px-5 md:pb-5">
        {rules.length ? (
          <div className="divide-y divide-[var(--border)]">
            {rules.map((rule) => (
              <div
                key={rule.id}
                className="flex flex-wrap items-center justify-between gap-3 py-3"
              >
                <div>
                  <p className="font-medium">{rule.name}</p>
                  <p className="mt-1 text-xs text-[var(--muted)]">
                    {rule.rule_type === "absence" ? "Ausência" : "Atendimento"} ·{" "}
                    {rule.recurrence} · prioridade {rule.priority}
                  </p>
                </div>
                {canManage ? (
                  <div className="flex gap-2">
                    <Button size="sm" variant="tertiary" onPress={() => onEdit(rule)}>
                      <Pencil className="size-3.5" />
                      Editar
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      onPress={() => void deactivate(rule)}
                      isDisabled={busy === rule.id}
                    >
                      {busy === rule.id ? "Desativando..." : "Desativar"}
                    </Button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-[var(--radius-md)] border border-dashed border-[var(--border)] p-5 text-sm text-[var(--muted)]">
            <p>Nenhuma regra nativa publicada.</p>
            {canManage ? (
              <Button className="mt-4" size="sm" variant="secondary" onPress={onCreate}>
                <Plus className="size-4" />
                Criar primeira regra
              </Button>
            ) : null}
          </div>
        )}
      </Card.Content>
    </Card>
  );
}

function CalendarGrid({
  days,
  cursor,
  view,
  occurrences,
  selectedDate,
  onSelect,
}: {
  days: Date[];
  cursor: Date;
  view: CalendarView;
  occurrences: HelpdeskCalendarOccurrence[];
  selectedDate: string;
  onSelect: (date: string) => void;
}) {
  return (
    <Card variant="default" className="judah-glass overflow-hidden rounded-[var(--radius-lg)]">
      <Card.Content className="judah-scroll overflow-x-auto p-3 md:p-4">
        <div
          className={cn(
            "grid grid-cols-7 gap-2",
            view === "month" ? "min-w-[980px]" : "min-w-[900px]",
          )}
          role="grid"
          aria-label={`Calendário ${view === "month" ? "mensal" : "semanal"}`}
        >
          <div className="col-span-7 grid grid-cols-7 gap-2">
            {weekdays.map((day) => (
              <span
                key={day}
                role="columnheader"
                className="judah-mono px-2 py-2 text-center text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]"
              >
                {day}
              </span>
            ))}
          </div>
          {days.map((day) => {
            const date = isoDate(day);
            const occurrence = occurrenceFor(occurrences, day);
            const outside = view === "month" && day.getMonth() !== cursor.getMonth();
            return (
              <button
                key={date}
                type="button"
                role="gridcell"
                aria-selected={selectedDate === date}
                aria-label={`${day.toLocaleDateString("pt-BR", { dateStyle: "full" })}: ${
                  occurrence ? stateLabel[occurrence.state] : "sem regra"
                }`}
                onClick={() => onSelect(date)}
                className={cn(
                  "min-h-36 rounded-[var(--radius-md)] border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] md:min-h-40",
                  outside
                    ? "border-transparent opacity-45"
                    : "border-[var(--border)] hover:border-[var(--accent)]/60",
                  selectedDate === date &&
                    "border-[var(--accent)] bg-[var(--accent)]/10",
                )}
              >
                <span className="text-sm font-semibold">{day.getDate()}</span>
                {occurrence ? (
                  <div className="mt-3 space-y-2">
                    <span
                      className={cn(
                        "judah-mono inline-flex rounded-full border px-2 py-0.5 text-[9px] uppercase tracking-[0.12em]",
                        occurrence.state === "OPEN" &&
                          "border-[var(--success)]/40 text-[var(--success)]",
                        occurrence.state === "ABSENCE" &&
                          "border-[var(--warning)]/50 text-[var(--warning)]",
                        occurrence.state === "CLOSED" &&
                          "border-[var(--muted)]/40 text-[var(--muted)]",
                      )}
                    >
                      {stateLabel[occurrence.state]}
                    </span>
                    {occurrence.intervals.length ? (
                      <div className="space-y-1">
                        {occurrence.intervals.map((interval) => (
                          <p
                            key={`${interval.start}-${interval.end}`}
                            className="judah-mono text-xs font-medium text-[var(--foreground)]"
                          >
                            {interval.start}–{interval.end}
                          </p>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs leading-5 text-[var(--muted)]">
                        {occurrence.reason || "Sem atendimento"}
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="mt-3 text-xs text-[var(--muted)]">Sem regra</p>
                )}
              </button>
            );
          })}
        </div>
      </Card.Content>
    </Card>
  );
}

function DayDetailModal({
  isOpen,
  date,
  occurrence,
  rule,
  canManage,
  onOpenChange,
  onCreate,
  onEdit,
}: {
  isOpen: boolean;
  date: string;
  occurrence: HelpdeskCalendarOccurrence | null;
  rule: HelpdeskCalendarRule | null;
  canManage: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: () => void;
  onEdit: (rule: HelpdeskCalendarRule) => void;
}) {
  return (
    <Modal.Backdrop isOpen={isOpen} onOpenChange={onOpenChange} variant="blur">
      <Modal.Container size="md" placement="auto">
        <Modal.Dialog>
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Icon className="bg-[var(--accent)]/10 text-[var(--accent)]">
              <CalendarDays className="size-5" />
            </Modal.Icon>
            <div>
              <p className="judah-mono text-[10px] uppercase tracking-[0.2em] text-[var(--muted)]">
                Detalhe do dia
              </p>
              <Modal.Heading className="mt-1 capitalize">
                {new Date(`${date}T12:00:00`).toLocaleDateString("pt-BR", {
                  dateStyle: "long",
                })}
              </Modal.Heading>
            </div>
          </Modal.Header>
          <Modal.Body className="space-y-5">
            {occurrence ? (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <p className="text-xs text-[var(--muted)]">Estado efetivo</p>
                    <p className="mt-1 text-lg font-semibold">
                      {stateLabel[occurrence.state]}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-[var(--muted)]">Intervalos</p>
                    <div className="mt-1 space-y-1 text-sm font-medium">
                      {occurrence.intervals.length
                        ? occurrence.intervals.map((item) => (
                            <p key={`${item.start}-${item.end}`}>
                              {item.start} — {item.end}
                            </p>
                          ))
                        : "Fechado"}
                    </div>
                  </div>
                </div>
                <div>
                  <p className="text-xs text-[var(--muted)]">Fonte / precedência</p>
                  <p className="mt-1 text-sm">
                    {occurrence.source_rule_name ?? "Configuração de compatibilidade"}
                    {occurrence.priority !== null ? ` · prioridade ${occurrence.priority}` : ""}
                  </p>
                </div>
                {occurrence.message ? (
                  <div className="rounded-[var(--radius-md)] border border-[var(--warning)]/30 bg-[var(--warning)]/10 p-4 text-sm">
                    <p className="judah-mono mb-2 text-[10px] uppercase tracking-[0.16em] text-[var(--warning)]">
                      Mensagem de ausência
                    </p>
                    <p className="whitespace-pre-wrap leading-6">
                      {occurrence.message.replaceAll("**", "")}
                    </p>
                  </div>
                ) : null}
              </>
            ) : (
              <div className="rounded-[var(--radius-md)] border border-dashed border-[var(--border)] p-4 text-sm text-[var(--muted)]">
                Nenhuma regra publicada para este dia.
              </div>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button slot="close" variant="tertiary">
              Fechar
            </Button>
            {canManage && rule ? (
              <Button onPress={() => onEdit(rule)}>
                <Pencil className="size-4" />
                Editar intervalos e estado
              </Button>
            ) : canManage ? (
              <Button onPress={onCreate}>
                <Plus className="size-4" />
                Criar regra para o dia
              </Button>
            ) : null}
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
