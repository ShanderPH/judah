const dateFormatter = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
});

const dateTimeFormatter = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "short",
});

const integerFormatter = new Intl.NumberFormat("pt-BR");

const percentFormatter = new Intl.NumberFormat("pt-BR", {
  style: "percent",
  maximumFractionDigits: 0,
});

export function formatInteger(value: number): string {
  return integerFormatter.format(value);
}

export function formatPercentFromRatio(value: number): string {
  return percentFormatter.format(Number.isFinite(value) ? value : 0);
}

export function formatDateLabel(value: string): string {
  return dateFormatter.format(new Date(value));
}

export function formatDateTime(value: string | null): string {
  if (!value) {
    return "--";
  }

  return dateTimeFormatter.format(new Date(value));
}

export function formatMinutes(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "--";
  }

  return `${value.toFixed(value >= 10 ? 0 : 1)} min`;
}

export function formatSeconds(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "--";
  }

  if (value >= 3600) {
    return `${(value / 3600).toFixed(1)} h`;
  }

  if (value >= 60) {
    return `${(value / 60).toFixed(1)} min`;
  }

  return `${value.toFixed(0)} s`;
}

export function safeNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
