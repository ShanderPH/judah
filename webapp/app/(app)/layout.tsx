import { AuthBoundary } from "@/src/components/auth/auth-boundary";
import { AppShell } from "@/src/components/layout/app-shell";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { canAccessPath } from "@/src/lib/auth/access-policy";
import { readAuthTokens, resolveSessionFromTokens } from "@/src/lib/auth/server-session";

export default async function DashboardLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const pathname = headerStore.get("x-judah-pathname") ?? "/dashboard";
  const tokens = readAuthTokens(cookieStore);
  const session = await resolveSessionFromTokens({ accessToken: tokens.accessToken, refreshToken: null });

  if (session.status !== "authenticated") {
    if (tokens.refreshToken) {
      redirect(`/auth/refresh?next=${encodeURIComponent(pathname)}`);
    }
    redirect(`/login?next=${encodeURIComponent(pathname)}`);
  }
  if (!canAccessPath(session.user, pathname)) redirect("/forbidden");

  return (
    <AuthBoundary initialUser={session.user}>
      <AppShell>{children}</AppShell>
    </AuthBoundary>
  );
}
