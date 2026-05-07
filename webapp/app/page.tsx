import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AUTH_COOKIE_NAMES } from "@/src/lib/auth/constants";

export default async function Home() {
  const cookieStore = await cookies();
  const hasSession =
    cookieStore.has(AUTH_COOKIE_NAMES.accessToken) ||
    cookieStore.has(AUTH_COOKIE_NAMES.refreshToken);

  redirect(hasSession ? "/dashboard" : "/login");
}
