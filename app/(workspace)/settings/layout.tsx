import { redirect } from "next/navigation";
import { fetchServerSessionContext } from "@/lib/server-session-context";

export const dynamic = "force-dynamic";

export default async function SettingsLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const sessionContext = await fetchServerSessionContext();

  if (sessionContext.onboarding_status !== "approved" || sessionContext.membership?.role !== "admin") {
    redirect("/dashboard");
  }

  return children;
}
