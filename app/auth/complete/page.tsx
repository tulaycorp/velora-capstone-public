import { redirect } from "next/navigation";
import { resolvePostAuthLandingPath } from "@/lib/auth-entry-state";
import { fetchServerSessionContext } from "@/lib/server-session-context";

export const dynamic = "force-dynamic";

export default async function PostAuthHandoffPage() {
  const sessionContext = await fetchServerSessionContext();
  redirect(resolvePostAuthLandingPath(sessionContext.onboarding_status));
}
