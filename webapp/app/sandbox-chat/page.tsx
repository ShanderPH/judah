import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { SandboxChat } from "@/src/features/sandbox-chat/sandbox-chat";
import { readAuthTokens, resolveSessionFromTokens } from "@/src/lib/auth/server-session";
import { CAPABILITIES, hasCapability } from "@/src/lib/auth/access-policy";

export const dynamic = "force-dynamic";

/** Dedicated, authenticated HubSpot sandbox chat route without the admin shell. */
export default async function SandboxChatPage() {
  const cookieStore = await cookies();
  const tokens = readAuthTokens(cookieStore);
  const session = await resolveSessionFromTokens({ accessToken: tokens.accessToken, refreshToken: null });

  if (session.status !== "authenticated") redirect("/auth/refresh?next=%2Fsandbox-chat");
  if (!hasCapability(session.user, CAPABILITIES.sandboxUse)) redirect("/forbidden");

  return (
    <SandboxChat
      portalId={process.env.NEXT_PUBLIC_HUBSPOT_PORTAL_ID ?? "51734496"}
      user={{
        id: session.user.id,
        email: session.user.email,
        firstName: session.user.first_name,
        lastName: session.user.last_name,
      }}
    />
  );
}
