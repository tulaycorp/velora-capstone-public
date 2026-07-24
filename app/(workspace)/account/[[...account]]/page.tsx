import { AccountSettingsPage } from "@/components/workspace/account-settings-page";
import { isClerkFrontendConfigured } from "@/lib/clerk-config";

export default function WorkspaceAccountPage() {
  return <AccountSettingsPage clerkEnabled={isClerkFrontendConfigured()} />;
}
