import { redirect } from "next/navigation";
import { OrganizationOnboarding } from "@/components/auth/organization-onboarding";
import { fetchServerSessionContext } from "@/lib/server-session-context";

export const dynamic = "force-dynamic";

export default async function OnboardingPage() {
  const sessionContext = await fetchServerSessionContext();

  if (sessionContext.onboarding_status === "approved") {
    redirect("/dashboard");
  }

  return <OrganizationOnboarding initialSessionContext={sessionContext} />;
}
