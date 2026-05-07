"use client";

import { Alert, Button, Card, Spinner } from "@heroui/react";

interface DataStateProps {
  emptyMessage?: string;
  error?: Error | null;
  isEmpty?: boolean;
  isLoading?: boolean;
  onRetry?: () => void;
}

export function DataState({
  emptyMessage = "Nenhum dado disponivel no momento.",
  error,
  isEmpty = false,
  isLoading = false,
  onRetry,
}: DataStateProps) {
  if (isLoading) {
    return (
      <Card
        variant="secondary"
        className="judah-glass flex min-h-52 items-center justify-center rounded-[var(--radius-lg)] p-8"
      >
        <div className="flex flex-col items-center gap-3 text-center">
          <Spinner color="accent" size="lg" />
          <p className="text-sm text-[var(--muted)]">Carregando dados operacionais...</p>
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Alert status="danger" className="rounded-[var(--radius-md)]">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Title>Falha ao carregar dados</Alert.Title>
          <Alert.Description>{error.message}</Alert.Description>
        </Alert.Content>
        {onRetry ? (
          <Button variant="danger" size="sm" onPress={onRetry}>
            Recarregar
          </Button>
        ) : null}
      </Alert>
    );
  }

  if (isEmpty) {
    return (
      <Card
        variant="secondary"
        className="judah-glass min-h-52 rounded-[var(--radius-lg)] p-8"
      >
        <Card.Header>
          <Card.Title>Sem registros relevantes</Card.Title>
          <Card.Description className="max-w-xl">{emptyMessage}</Card.Description>
        </Card.Header>
      </Card>
    );
  }

  return null;
}
