"use client";

import {
  Alert,
  Button,
  Input,
  Label,
  ListBox,
  Modal,
  Select,
  TextArea,
  TextField,
} from "@heroui/react";
import { Clock3, Minus, Plus } from "lucide-react";
import { useState } from "react";

import { ApiClientError, judahApi } from "@/src/lib/api/client";
import type {
  CreateHelpdeskCalendarRulePayload,
  HelpdeskCalendarInterval,
  HelpdeskCalendarRule,
  HelpdeskRecurrence,
  HelpdeskRuleType,
} from "@/src/types/api";

import { areCalendarIntervalsValid } from "./calendar-utils";

interface RuleWizardProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
  initialRule?: HelpdeskCalendarRule | null;
  initialDate?: string | null;
}

const weekdayOptions = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

export function RuleWizard({
  isOpen,
  onClose,
  onSaved,
  initialRule = null,
  initialDate = null,
}: RuleWizardProps) {
  const [type, setType] = useState<HelpdeskRuleType>(initialRule?.rule_type ?? "service");
  const [name, setName] = useState(initialRule?.name ?? "");
  const [recurrence, setRecurrence] = useState<HelpdeskRecurrence>(
    initialRule?.recurrence ?? "once",
  );
  const [date, setDate] = useState(
    initialRule?.starts_on ?? initialDate ?? new Date().toISOString().slice(0, 10),
  );
  const [endDate, setEndDate] = useState(initialRule?.ends_on ?? "");
  const [intervals, setIntervals] = useState<HelpdeskCalendarInterval[]>(
    initialRule?.intervals.length
      ? initialRule.intervals.map((interval) => ({ ...interval }))
      : [{ start: "09:00", end: "18:00" }],
  );
  const [message, setMessage] = useState(initialRule?.message ?? "");
  const [weekdays, setWeekdays] = useState<number[]>(initialRule?.weekdays ?? []);
  const [weekOfMonth, setWeekOfMonth] = useState(
    initialRule?.week_of_month ? String(initialRule.week_of_month) : "",
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const updateInterval = (
    index: number,
    field: keyof HelpdeskCalendarInterval,
    value: string,
  ) => {
    setIntervals((current) =>
      current.map((interval, position) =>
        position === index ? { ...interval, [field]: value } : interval,
      ),
    );
  };

  const validate = (): string | null => {
    if (!name.trim()) return "Informe um nome para a regra.";
    if (endDate && endDate < date) return "A data final não pode preceder a data inicial.";
    if (recurrence === "weekly" && weekdays.length === 0) {
      return "Selecione ao menos um dia da semana.";
    }
    if (type === "absence" && message.includes("<")) {
      return "Use Markdown limitado; HTML não é aceito na mensagem.";
    }
    if (type === "service") {
      if (!areCalendarIntervalsValid(intervals)) {
        return "Os intervalos devem ser crescentes e não podem se sobrepor.";
      }
    }
    return null;
  };

  const submit = async () => {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError(null);
    const payload: CreateHelpdeskCalendarRulePayload = {
      name: name.trim(),
      rule_type: type,
      recurrence,
      starts_on: date,
      ends_on: endDate || null,
      weekdays,
      week_of_month: weekOfMonth ? Number(weekOfMonth) : null,
      dates: recurrence === "once" || recurrence === "yearly" ? [date] : [],
      intervals: type === "service" ? intervals : [],
      message: type === "absence" ? message.trim() || null : null,
      priority: initialRule?.priority ?? (type === "absence" ? 300 : 50),
      ...(initialRule ? { expected_version: initialRule.version } : {}),
    };

    try {
      if (initialRule) {
        await judahApi.updateHelpdeskCalendarRule(initialRule.id, {
          ...payload,
          expected_version: initialRule.version,
        });
      } else {
        await judahApi.createHelpdeskCalendarRule(payload);
      }
      onSaved();
      onClose();
    } catch (caught) {
      setError(
        caught instanceof ApiClientError
          ? caught.detail
          : "Não foi possível salvar a regra.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal.Backdrop isOpen={isOpen} onOpenChange={(open) => !open && onClose()} variant="blur">
      <Modal.Container size="lg" scroll="inside" placement="auto">
        <Modal.Dialog>
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Icon className="bg-[var(--accent)]/10 text-[var(--accent)]">
              <Clock3 className="size-5" />
            </Modal.Icon>
            <div>
              <Modal.Heading>
                {initialRule ? "Editar regra operacional" : "Nova regra operacional"}
              </Modal.Heading>
              <p className="mt-1 text-sm text-[var(--muted)]">
                Configure atendimento ou ausência com vigência e intervalos precisos.
              </p>
            </div>
          </Modal.Header>
          <Modal.Body className="space-y-5">
            {error ? (
              <Alert status="danger">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Description>{error}</Alert.Description>
                </Alert.Content>
              </Alert>
            ) : null}

            <TextField value={name} onChange={setName} fullWidth isRequired>
              <Label>Nome da regra</Label>
              <Input placeholder="Ex.: Atendimento de sábado" />
            </TextField>

            <div className="grid gap-4 sm:grid-cols-2">
              <Select
                selectedKey={type}
                onSelectionChange={(key) => setType(String(key) as HelpdeskRuleType)}
              >
                <Label>Estado da regra</Label>
                <Select.Trigger>
                  <Select.Value />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    <ListBox.Item id="service" textValue="Atendimento aberto">
                      Atendimento aberto
                    </ListBox.Item>
                    <ListBox.Item id="absence" textValue="Ausência / fechado">
                      Ausência / fechado
                    </ListBox.Item>
                  </ListBox>
                </Select.Popover>
              </Select>

              <Select
                selectedKey={recurrence}
                onSelectionChange={(key) =>
                  setRecurrence(String(key) as HelpdeskRecurrence)
                }
              >
                <Label>Recorrência</Label>
                <Select.Trigger>
                  <Select.Value />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    <ListBox.Item id="once" textValue="Uma vez">
                      Uma vez
                    </ListBox.Item>
                    <ListBox.Item id="weekly" textValue="Semanal">
                      Semanal
                    </ListBox.Item>
                    <ListBox.Item id="monthly" textValue="Mensal">
                      Mensal
                    </ListBox.Item>
                    <ListBox.Item id="yearly" textValue="Anual">
                      Anual
                    </ListBox.Item>
                  </ListBox>
                </Select.Popover>
              </Select>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <TextField value={date} onChange={setDate} isRequired>
                <Label>{recurrence === "once" ? "Data" : "Início da vigência"}</Label>
                <Input type="date" />
              </TextField>
              <TextField value={endDate} onChange={setEndDate}>
                <Label>Fim da vigência (opcional)</Label>
                <Input type="date" />
              </TextField>
            </div>

            {recurrence === "weekly" || recurrence === "monthly" ? (
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Dias da semana</legend>
                <div className="flex flex-wrap gap-2">
                  {weekdayOptions.map((label, index) => (
                    <label
                      key={label}
                      className="flex min-h-10 items-center gap-2 rounded-[var(--radius-md)] border border-[var(--border)] px-3 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={weekdays.includes(index)}
                        onChange={(event) =>
                          setWeekdays((current) =>
                            event.target.checked
                              ? [...current, index].sort()
                              : current.filter((day) => day !== index),
                          )
                        }
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </fieldset>
            ) : null}

            {recurrence === "monthly" ? (
              <TextField value={weekOfMonth} onChange={setWeekOfMonth}>
                <Label>Semana do mês (opcional)</Label>
                <Input type="number" min="1" max="5" placeholder="1 a 5" />
              </TextField>
            ) : null}

            {type === "service" ? (
              <fieldset className="space-y-3">
                <legend className="sr-only">Intervalos de atendimento</legend>
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium">Intervalos de atendimento</p>
                  <Button
                    size="sm"
                    variant="secondary"
                    onPress={() =>
                      setIntervals((current) => [
                        ...current,
                        { start: "13:00", end: "18:00" },
                      ])
                    }
                  >
                    <Plus className="size-4" />
                    Adicionar intervalo
                  </Button>
                </div>
                <div className="space-y-3">
                  {intervals.map((interval, index) => (
                    <div
                      key={`interval-${index}`}
                      className="grid gap-3 rounded-[var(--radius-md)] border border-[var(--border)] p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
                    >
                      <TextField
                        value={interval.start}
                        onChange={(value) => updateInterval(index, "start", value)}
                      >
                        <Label>Início</Label>
                        <Input type="time" />
                      </TextField>
                      <TextField
                        value={interval.end}
                        onChange={(value) => updateInterval(index, "end", value)}
                      >
                        <Label>Fim</Label>
                        <Input type="time" />
                      </TextField>
                      <Button
                        isIconOnly
                        variant="tertiary"
                        aria-label={`Remover intervalo ${index + 1}`}
                        isDisabled={intervals.length === 1}
                        onPress={() =>
                          setIntervals((current) =>
                            current.filter((_, position) => position !== index),
                          )
                        }
                      >
                        <Minus className="size-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              </fieldset>
            ) : (
              <TextField value={message} onChange={setMessage} fullWidth>
                <Label>Mensagem de ausência</Label>
                <TextArea placeholder="Ex.: Estamos ausentes hoje. **Voltamos amanhã às 9h.** 😊" />
                <p className="mt-1 text-xs text-[var(--muted)]">
                  Aceita **negrito**, emojis e quebras de linha. O backend gera texto simples e
                  rich text seguro para HubSpot.
                </p>
              </TextField>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button variant="tertiary" onPress={onClose} isDisabled={saving}>
              Cancelar
            </Button>
            <Button onPress={() => void submit()} isPending={saving}>
              {saving ? "Salvando..." : "Salvar regra"}
            </Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
