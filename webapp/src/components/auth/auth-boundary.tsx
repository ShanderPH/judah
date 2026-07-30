"use client";

import { useRouter } from "next/navigation";

import { authClient } from "@/src/lib/api/client";
import { SessionProvider } from "@/src/lib/auth/session-context";
import type { User } from "@/src/types/api";

export function AuthBoundary({
  children,
  initialUser,
}: Readonly<{ children: React.ReactNode; initialUser: User }>) {
  const router = useRouter();

  const signOut = async () => {
    await authClient.logout();
    router.replace("/login");
  };

  return (
    <SessionProvider
      value={{
        user: initialUser,
        refreshSession: async () => {
          router.refresh();
        },
        signOut,
      }}
    >
      {children}
    </SessionProvider>
  );
}
