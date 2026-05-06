"use client";

import { createContext, useContext } from "react";

import type { User } from "@/src/types/api";

interface SessionContextValue {
  user: User;
  refreshSession: () => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  children,
  value,
}: Readonly<{
  children: React.ReactNode;
  value: SessionContextValue;
}>) {
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);

  if (!context) {
    throw new Error("useSession must be used inside SessionProvider.");
  }

  return context;
}
