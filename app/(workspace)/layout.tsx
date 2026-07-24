import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { AppSessionContextProvider } from "@/components/auth/app-session-context";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { STORE_SELECTION_COOKIE_NAME } from "@/components/workspace/store-context-state";
import { isClerkFrontendConfigured } from "@/lib/clerk-config";
import { fetchServerSessionContext } from "@/lib/server-session-context";

export const dynamic = "force-dynamic";

export default async function WorkspaceLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cookieStore = await cookies();
  const sessionContext = await fetchServerSessionContext();
  const initialSelectedStoreId =
    cookieStore.get(STORE_SELECTION_COOKIE_NAME)?.value ?? null;

  if (sessionContext.onboarding_status !== "approved") {
    redirect("/onboarding");
  }

  return (
    <AppSessionContextProvider initialSessionContext={sessionContext}>
      <WorkspaceShell
        clerkEnabled={isClerkFrontendConfigured()}
        initialSelectedStoreId={initialSelectedStoreId}
      >
        {children}
      </WorkspaceShell>
    </AppSessionContextProvider>
  );
}
