import { AuthBoundary } from "@/src/components/auth/auth-boundary";
import { AppShell } from "@/src/components/layout/app-shell";

export default function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <AuthBoundary>
      <AppShell>{children}</AppShell>
    </AuthBoundary>
  );
}
