"use client";

import {
  Button,
  Input,
  Label,
  ListBox,
  Select,
  Switch,
  TextField,
} from "@heroui/react";
import { useState } from "react";

import type {
  Agent,
  AgentStatus,
  CreateAgentPayload,
  UpdateAgentPayload,
} from "@/src/types/api";

const TIMEZONE_OPTIONS = [
  "America/Sao_Paulo",
  "America/Argentina/Buenos_Aires",
  "America/New_York",
  "Europe/Lisbon",
  "UTC",
];

const STATUS_OPTIONS: AgentStatus[] = ["online", "away", "offline", "busy"];

interface AgentFormProps {
  initial?: Agent | null;
  isPending: boolean;
  onCancel: () => void;
  onSubmit: (
    payload: CreateAgentPayload | UpdateAgentPayload,
    mode: "create" | "update",
  ) => void;
}

export function AgentForm({ initial, isPending, onCancel, onSubmit }: AgentFormProps) {
  const isEdit = Boolean(initial);
  const [name, setName] = useState(initial?.name ?? "");
  const [email, setEmail] = useState(initial?.agent_email ?? "");
  const [hubspotOwnerId, setHubspotOwnerId] = useState(
    initial ? String(initial.hubspot_owner_id) : "",
  );
  const [team, setTeam] = useState(initial?.team ?? "");
  const [managerEmail, setManagerEmail] = useState(initial?.manager_email ?? "");
  const [timezone, setTimezone] = useState(initial?.timezone ?? "America/Sao_Paulo");
  const [maxChats, setMaxChats] = useState<string>(
    String(initial?.max_simultaneous_chats ?? 5),
  );
  const [autoAssign, setAutoAssign] = useState<boolean>(
    initial?.auto_assign_enabled ?? true,
  );
  const [status, setStatus] = useState<AgentStatus>(
    (initial?.status_enum as AgentStatus) ?? "offline",
  );
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = () => {
    const trimmedName = name.trim();
    const trimmedEmail = email.trim();
    if (!trimmedName) {
      setError("Informe um nome valido para o agente.");
      return;
    }
    if (!trimmedEmail) {
      setError("Informe um email valido para o agente.");
      return;
    }
    const maxChatsNumber = Number(maxChats);
    if (!Number.isFinite(maxChatsNumber) || maxChatsNumber < 0) {
      setError("Capacidade simultanea invalida.");
      return;
    }
    setError(null);

    if (isEdit) {
      const payload: UpdateAgentPayload = {
        name: trimmedName,
        team: team.trim() || null,
        manager_email: managerEmail.trim() || null,
        timezone,
        max_simultaneous_chats: Math.round(maxChatsNumber),
        auto_assign_enabled: autoAssign,
        status_enum: status,
      };
      onSubmit(payload, "update");
      return;
    }

    const ownerNumber = Number(hubspotOwnerId);
    if (!Number.isInteger(ownerNumber) || ownerNumber <= 0) {
      setError("HubSpot owner ID precisa ser um numero inteiro positivo.");
      return;
    }

    const payload: CreateAgentPayload = {
      name: trimmedName,
      agent_email: trimmedEmail,
      hubspot_owner_id: ownerNumber,
      team: team.trim() || null,
      manager_email: managerEmail.trim() || null,
      timezone,
      max_simultaneous_chats: Math.round(maxChatsNumber),
      auto_assign_enabled: autoAssign,
    };
    onSubmit(payload, "create");
  };

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        handleSubmit();
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <TextField name="agent-name" value={name} onChange={setName} fullWidth>
          <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
            Nome
          </Label>
          <Input variant="secondary" placeholder="Nome do agente" />
        </TextField>
        <TextField
          name="agent-email"
          value={email}
          onChange={setEmail}
          fullWidth
          isDisabled={isEdit}
        >
          <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
            Email
          </Label>
          <Input variant="secondary" placeholder="agente@inchurch.com" type="email" />
        </TextField>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <TextField
          name="hubspot-owner-id"
          value={hubspotOwnerId}
          onChange={setHubspotOwnerId}
          fullWidth
          isDisabled={isEdit}
        >
          <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
            HubSpot owner ID
          </Label>
          <Input variant="secondary" placeholder="72733895" inputMode="numeric" />
        </TextField>

        <TextField name="agent-team" value={team} onChange={setTeam} fullWidth>
          <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
            Time
          </Label>
          <Input variant="secondary" placeholder="N1 / N2" />
        </TextField>
      </div>

      <TextField
        name="manager-email"
        value={managerEmail}
        onChange={setManagerEmail}
        fullWidth
      >
        <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
          Email do gestor
        </Label>
        <Input variant="secondary" placeholder="gestor@inchurch.com" type="email" />
      </TextField>

      <div className="grid gap-4 md:grid-cols-3">
        <TextField
          name="max-chats"
          value={maxChats}
          onChange={setMaxChats}
          fullWidth
        >
          <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
            Capacidade simultanea
          </Label>
          <Input variant="secondary" inputMode="numeric" />
        </TextField>

        <Select
          selectedKey={timezone}
          onSelectionChange={(key) => setTimezone(String(key))}
          fullWidth
        >
          <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
            Timezone
          </Label>
          <Select.Trigger>
            <Select.Value />
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              {TIMEZONE_OPTIONS.map((tz) => (
                <ListBox.Item key={tz} id={tz} textValue={tz}>
                  {tz}
                </ListBox.Item>
              ))}
            </ListBox>
          </Select.Popover>
        </Select>

        {isEdit ? (
          <Select
            selectedKey={status}
            onSelectionChange={(key) => setStatus(String(key) as AgentStatus)}
            fullWidth
          >
            <Label className="judah-mono text-[10px] uppercase tracking-[0.24em] text-[var(--muted)]">
              Status
            </Label>
            <Select.Trigger>
              <Select.Value />
              <Select.Indicator />
            </Select.Trigger>
            <Select.Popover>
              <ListBox>
                {STATUS_OPTIONS.map((option) => (
                  <ListBox.Item key={option} id={option} textValue={option}>
                    {option}
                  </ListBox.Item>
                ))}
              </ListBox>
            </Select.Popover>
          </Select>
        ) : null}
      </div>

      <div className="flex items-center justify-between rounded-xl border border-[var(--border)]/60 bg-[var(--surface)]/50 px-4 py-3">
        <div>
          <p className="font-medium">Auto-atribuicao</p>
          <p className="text-xs text-[var(--muted)]">
            Define se este agente entra na rotacao automatica do matchmaker.
          </p>
        </div>
        <Switch isSelected={autoAssign} onChange={setAutoAssign} />
      </div>

      {error ? (
        <p className="rounded-xl border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-2 text-sm text-[var(--danger)]">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2 pt-2">
        <Button variant="tertiary" onPress={onCancel} type="button">
          Cancelar
        </Button>
        <Button isPending={isPending} type="submit">
          {isEdit ? "Salvar alteracoes" : "Criar agente"}
        </Button>
      </div>
    </form>
  );
}
