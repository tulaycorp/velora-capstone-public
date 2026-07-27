"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ExternalLink,
  LoaderCircle,
  Link2,
  Plus,
  PlugZap,
  RefreshCw,
  Users,
  Pencil,
  Building
} from "lucide-react";
import { useAppSessionContext } from "@/components/auth/app-session-context";
import { PageHeader } from "@/components/workspace/page-header";
import {
  ResourceError,
  SettingsSkeleton
} from "@/components/workspace/resource-state";
import {
  CredentialCard,
  InlineEmptyState,
  MetadataChip,
  ProviderLogo,
  ProviderSelectorCard,
  ProviderStatusBadge,
  SettingsSection,
  StoreConnectionDialog,
  usePersistentState
} from "@/components/workspace/organization-settings-sections";
import { useStoreContext } from "@/components/workspace/store-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { buildEtsyDiscoverySummaryChips } from "@/components/workspace/etsy-discovery-display";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import {
  approveOrganizationJoinRequest,
  deleteProviderCredentials,
  deleteStoreConnection,
  fetchEtsyConnectionStatus,
  fetchOrganizationJoinRequests,
  fetchOrganizationMembers,
  fetchProviderCredentialStatus,
  fetchProviders,
  formatDateTime,
  providerLabel,
  rejectOrganizationJoinRequest,
  removeOrganizationMember,
  saveProviderCredentials,
  startEtsyOAuth,
  storefrontLabel,
  syncEtsyConnectionShops,
  syncStoreConnections,
  updateStoreConnection,
  updateOrganization,
  type EtsyConnectionStatus,
  type ManualStoreSeed,
  type OrganizationJoinRequestSummary,
  type OrganizationMemberSummary,
  type PodProvider,
  type PodProviderKey,
  type ProviderCredentialStatus,
  type ProviderStoreConnection,
} from "@/lib/backend-api";
import {
  buildEtsyOAuthPopupFeatures,
  isEtsyOAuthMessage
} from "@/lib/etsy-oauth";
import { buildEtsyStoreCapacitySummary } from "@/lib/etsy-store-capacity";
import { resolveEtsyShopMatchedConnections } from "@/lib/etsy-shop-matches";
import { cn } from "@/lib/utils";
import { workspacePageCacheKeys } from "@/lib/workspace-page-cache-keys";
import { loadWorkspacePageResource } from "@/lib/workspace-page-cache";
import {
  buildCredentialActionKey,
  createEmptyEtsyConnectionStatus,
  createGelatoDraft,
  createManualStoreSeed,
  createPrintifyDraft,
  emptyCredentialStatuses,
  formatRequesterPrimaryLine,
  formatRequesterSecondaryLine,
  formatStorefrontCount,
  normalizeManualStoreSeedsForSave,
  providerKeys,
  type CredentialDrafts
} from "@/lib/organization-settings-state";


export function OrganizationSettingsPage() {
  const { sessionContext, refreshSessionContext } = useAppSessionContext();
  const { storeConnections, refresh } = useStoreContext();
  const [providers, setProviders] = useState<PodProvider[]>([]);
  const [etsyConnection, setEtsyConnection] = useState<EtsyConnectionStatus>(
    createEmptyEtsyConnectionStatus()
  );
  const [credentialStatuses, setCredentialStatuses] = useState<
    Record<PodProviderKey, ProviderCredentialStatus>
  >(emptyCredentialStatuses);
  const [drafts, setDrafts] = useState<CredentialDrafts>({
    printify: createPrintifyDraft(),
    gelato: createGelatoDraft()
  });
  const [members, setMembers] = useState<OrganizationMemberSummary[]>([]);
  const [joinRequests, setJoinRequests] = useState<OrganizationJoinRequestSummary[]>([]);
  const [selectedProvider, setSelectedProvider] = usePersistentState<PodProviderKey | null>(
    "velora.settings.selected-provider",
    null
  );
  const [loading, setLoading] = useState(true);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingProvider, setSavingProvider] = useState<PodProviderKey | null>(null);
  const [syncingCredential, setSyncingCredential] = useState<string | null>(null);
  const [deletingCredential, setDeletingCredential] = useState<string | null>(null);
  const [deletingStoreId, setDeletingStoreId] = useState<string | null>(null);
  const [removingMemberId, setRemovingMemberId] = useState<string | null>(null);
  const [reviewingJoinRequestId, setReviewingJoinRequestId] = useState<string | null>(null);
  const [reviewingAction, setReviewingAction] = useState<"approve" | "reject" | null>(null);
  const [editingStoreSeed, setEditingStoreSeed] = useState<{
    credentialKey: string;
    seed: ManualStoreSeed | null;
  } | null>(null);
  const [editingEtsyConnectionId, setEditingEtsyConnectionId] = useState<string | null>(null);
  const [editingEtsyShopIdDraft, setEditingEtsyShopIdDraft] = useState("");
  const [savingEtsyConnectionId, setSavingEtsyConnectionId] = useState<string | null>(null);
  const [connectingEtsy, setConnectingEtsy] = useState(false);
  const [syncingEtsy, setSyncingEtsy] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const etsyOAuthWindowRef = useRef<Window | null>(null);
  const etsyOAuthWindowPollRef = useRef<number | null>(null);
  const activeEtsyOAuthStateRef = useRef<string | null>(null);
  const cacheScope = useMemo(
    () => ({
      organizationId: sessionContext.organization?.id ?? null,
      userId: sessionContext.user.id
    }),
    [sessionContext.organization?.id, sessionContext.user.id]
  );

  useEffect(() => {
    if (!selectedProvider) {
      return;
    }

    if (!providerKeys.includes(selectedProvider)) {
      setSelectedProvider(null);
    }
  }, [selectedProvider, setSelectedProvider]);

  const organization = sessionContext.organization;
  const selectedProviderRecord = useMemo(
    () => providers.find((provider) => provider.id === selectedProvider) ?? null,
    [providers, selectedProvider]
  );
  const gelatoProvider = useMemo(
    () => providers.find((provider) => provider.id === "gelato") ?? null,
    [providers]
  );
  const etsyStoreConnectionCount = useMemo(
    () => storeConnections.filter((connection) => connection.storefront_type === "etsy").length,
    [storeConnections]
  );
  const etsyStoreCapacity = useMemo(
    () =>
      buildEtsyStoreCapacitySummary({
        storeConnections,
        gelatoCredentials: credentialStatuses.gelato.credentials
      }),
    [credentialStatuses.gelato.credentials, storeConnections]
  );
  const providerSetupLocked = !etsyConnection.is_connected;
  const providerStoreCounts = useMemo(() => {
    return storeConnections.reduce(
      (counts, connection) => {
        counts[connection.provider] += 1;
        return counts;
      },
      {
        printify: 0,
        gelato: 0
      } satisfies Record<PodProviderKey, number>
    );
  }, [storeConnections]);
  const selectedProviderStores = useMemo(
    () =>
      selectedProvider
        ? storeConnections.filter((connection) => connection.provider === selectedProvider)
        : [],
    [selectedProvider, storeConnections]
  );
  const selectedCredentialStatus = selectedProvider ? credentialStatuses[selectedProvider] : null;
  const etsyDiscoverySummaryChips = useMemo(
    () =>
      buildEtsyDiscoverySummaryChips({
        etsyStoreConnectionCount,
        lastSyncedAt: etsyConnection.last_synced_at,
        formatDateTime
      }),
    [
      etsyConnection.last_synced_at,
      etsyStoreConnectionCount
    ]
  );
  const selectedCredentialGroups = useMemo(() => {
    if (!selectedCredentialStatus) {
      return [];
    }

    const groupedConnections = new Map<string, ProviderStoreConnection[]>();

    for (const connection of selectedProviderStores) {
      const existing = groupedConnections.get(connection.credential_key);
      if (existing) {
        existing.push(connection);
      } else {
        groupedConnections.set(connection.credential_key, [connection]);
      }
    }

    return selectedCredentialStatus.credentials.map((credential) => ({
      credential,
      connections: groupedConnections.get(credential.credential_key) ?? []
    }));
  }, [selectedCredentialStatus, selectedProviderStores]);
  const gelatoStorefrontOptions = useMemo(() => {
    const next = new Set<ManualStoreSeed["storefront_type"]>(["etsy", "shopify", "unknown"]);

    for (const option of gelatoProvider?.available_storefronts ?? []) {
      next.add(option);
    }

    return Array.from(next);
  }, [gelatoProvider]);

  const loadSettings = useCallback(async (mode: "initial" | "refresh" | "silent" = "initial") => {
    if (mode === "initial") {
      setLoading(true);
    }
    if (mode === "refresh") {
      setRefreshingAll(true);
    }
    setError(null);

    try {
      const [
        nextProviders,
        nextEtsyConnection,
        printifyStatus,
        gelatoStatus,
        nextMembers,
        nextJoinRequests
      ] = await loadWorkspacePageResource(
        workspacePageCacheKeys.organizationSettings(),
        cacheScope,
        () =>
          Promise.all([
            fetchProviders(),
            fetchEtsyConnectionStatus(),
            fetchProviderCredentialStatus("printify"),
            fetchProviderCredentialStatus("gelato"),
            fetchOrganizationMembers(),
            fetchOrganizationJoinRequests()
          ])
      );

      setProviders(nextProviders);
      setEtsyConnection(nextEtsyConnection);
      setCredentialStatuses({
        printify: printifyStatus,
        gelato: gelatoStatus
      });
      setMembers(nextMembers.members);
      setJoinRequests(nextJoinRequests.join_requests);
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "Unable to load settings."
      );
    } finally {
      if (mode === "initial") {
        setLoading(false);
      }
      if (mode === "refresh") {
        setRefreshingAll(false);
      }
    }
  }, [cacheScope]);

  const clearEtsyOAuthWindowMonitor = useCallback(() => {
    if (etsyOAuthWindowPollRef.current !== null) {
      window.clearInterval(etsyOAuthWindowPollRef.current);
      etsyOAuthWindowPollRef.current = null;
    }

    etsyOAuthWindowRef.current = null;
    activeEtsyOAuthStateRef.current = null;
  }, []);

  useEffect(() => {
    void loadSettings("initial");
  }, [loadSettings]);

  useEffect(() => {
    return () => {
      clearEtsyOAuthWindowMonitor();
    };
  }, [clearEtsyOAuthWindowMonitor]);

  useEffect(() => {
    function handleEtsyOAuthMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !isEtsyOAuthMessage(event.data)) {
        return;
      }

      const activeState = activeEtsyOAuthStateRef.current;
      if (
        activeState
        && event.data.state !== activeState
        && event.source !== etsyOAuthWindowRef.current
      ) {
        return;
      }

      clearEtsyOAuthWindowMonitor();
      setConnectingEtsy(false);

      if (event.data.success) {
        setError(null);
        void Promise.all([loadSettings("silent"), refresh()]).catch((refreshError) => {
          setError(
            refreshError instanceof Error
              ? refreshError.message
              : "Unable to refresh Etsy settings."
          );
        });
        return;
      }

      setError(event.data.error);
    }

    window.addEventListener("message", handleEtsyOAuthMessage);
    return () => {
      window.removeEventListener("message", handleEtsyOAuthMessage);
    };
  }, [clearEtsyOAuthWindowMonitor, loadSettings, refresh]);



  async function handleRefreshAll() {
    await Promise.all([loadSettings("refresh"), refresh()]);
  }

  async function handleOpenEtsyOAuth(expectedSellerUserId?: string) {
    setConnectingEtsy(true);
    setError(null);

    try {
      const response = await startEtsyOAuth(expectedSellerUserId);
      clearEtsyOAuthWindowMonitor();
      activeEtsyOAuthStateRef.current = response.state;

      const popup = window.open(
        response.authorization_url,
        "_blank",
        buildEtsyOAuthPopupFeatures({
          screenX: window.screenX,
          screenY: window.screenY,
          outerWidth: window.outerWidth,
          outerHeight: window.outerHeight
        })
      );
      if (!popup) {
        throw new Error("Allow pop-ups so Velora can open the Etsy connection window.");
      }

      popup.focus();
      etsyOAuthWindowRef.current = popup;
      etsyOAuthWindowPollRef.current = window.setInterval(() => {
        if (!popup.closed) {
          return;
        }

        clearEtsyOAuthWindowMonitor();
        setConnectingEtsy(false);
        setError((currentError) => currentError ?? "The Etsy connection window was closed.");
      }, 500);
    } catch (connectError) {
      setError(
        connectError instanceof Error ? connectError.message : "Unable to start Etsy connection."
      );
      clearEtsyOAuthWindowMonitor();
      setConnectingEtsy(false);
    }
  }

  async function handleRefreshEtsyConnection() {
    setSyncingEtsy(true);
    setError(null);

    try {
      await syncEtsyConnectionShops();
      await Promise.all([loadSettings("silent"), refresh()]);
    } catch (syncError) {
      setError(
        syncError instanceof Error ? syncError.message : "Unable to refresh Etsy shops."
      );
    } finally {
      setSyncingEtsy(false);
    }
  }

  async function handleSave(provider: PodProviderKey) {
    if (providerSetupLocked) {
      setError("Connect Etsy first before setting up Printify or Gelato.");
      return;
    }

    const displayName =
      provider === "printify"
        ? drafts.printify.display_name.trim()
        : drafts.gelato.display_name.trim();
    const credentialValue =
      provider === "printify"
        ? drafts.printify.api_token.trim()
        : drafts.gelato.api_key.trim();

    if (!displayName) {
      setError("Give this connection a name.");
      return;
    }

    if (!credentialValue) {
      setError(
        provider === "printify"
          ? "Paste your Printify access key."
          : "Paste your Gelato access key."
      );
      return;
    }

    setSavingProvider(provider);
    setError(null);

    try {
      await saveProviderCredentials(provider, {
        credentials:
          provider === "printify"
            ? { api_token: credentialValue }
            : { api_key: credentialValue },
        credential_display_name: displayName,
        manual_store_seeds: []
      });

      setDrafts((current) => ({
        ...current,
        [provider]: provider === "printify" ? createPrintifyDraft() : createGelatoDraft()
      }));

      await Promise.all([loadSettings("silent"), refresh()]);
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "Unable to save this connection."
      );
    } finally {
      setSavingProvider(null);
    }
  }

  async function handleSync(provider: PodProviderKey, credentialKey: string) {
    if (providerSetupLocked) {
      setError("Connect Etsy first before refreshing these stores.");
      return;
    }

    const credential = credentialStatuses[provider].credentials.find(
      (entry) => entry.credential_key === credentialKey
    );

    if (!credential) {
      setError("That connection could not be found.");
      return;
    }

    if (credential.missing_keys.length > 0) {
      setError(`Finish setting up ${credential.credential_display_name ?? "this connection"} first.`);
      return;
    }

    const actionKey = buildCredentialActionKey(provider, credentialKey);
    setSyncingCredential(actionKey);
    setError(null);

    try {
      await syncStoreConnections(provider, credentialKey);
      await Promise.all([loadSettings("silent"), refresh()]);
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Unable to refresh stores.");
    } finally {
      setSyncingCredential(null);
    }
  }

  async function handleDeleteCredentials(provider: PodProviderKey, credentialKey: string) {
    const actionKey = buildCredentialActionKey(provider, credentialKey);
    setDeletingCredential(actionKey);
    setError(null);

    try {
      await deleteProviderCredentials(provider, credentialKey);
      await Promise.all([loadSettings("silent"), refresh()]);
    } catch (deleteError) {
      setError(
        deleteError instanceof Error ? deleteError.message : "Unable to remove this connection."
      );
    } finally {
      setDeletingCredential(null);
    }
  }

  async function handleSaveStoreSeed(credentialKey: string, seed: ManualStoreSeed) {
    if (providerSetupLocked) {
      setError("Connect Etsy first before editing this store.");
      throw new Error("Connect Etsy first before editing this store.");
    }

    setError(null);
    try {
      const credential = credentialStatuses.gelato.credentials.find(
        (c) => c.credential_key === credentialKey
      );
      if (!credential) {
        throw new Error("This connection is no longer available.");
      }

      const currentSeeds = credential.manual_store_seeds.map(createManualStoreSeed);
      const existingIndex = currentSeeds.findIndex(
        (s) => s.provider_store_id === seed.provider_store_id
      );

      const nextSeeds = [...currentSeeds];
      if (existingIndex >= 0) {
        nextSeeds[existingIndex] = seed;
      } else {
        nextSeeds.push(seed);
      }

      await saveProviderCredentials("gelato", {
        credential_key: credentialKey,
        manual_store_seeds: normalizeManualStoreSeedsForSave(nextSeeds)
      });
      await syncStoreConnections("gelato", credentialKey);
      await Promise.all([loadSettings("silent"), refresh()]);
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "Unable to save this store."
      );
      throw saveError;
    }
  }

  async function handleDeleteStore(connectionId: string) {
    setDeletingStoreId(connectionId);
    setError(null);

    try {
      await deleteStoreConnection(connectionId);
      await Promise.all([loadSettings("silent"), refresh()]);
    } catch (deleteError) {
      setError(
        deleteError instanceof Error ? deleteError.message : "Unable to remove this store."
      );
    } finally {
      setDeletingStoreId(null);
    }
  }

  function handleStartEditEtsyShopId(connection: ProviderStoreConnection) {
    setEditingEtsyConnectionId(connection.id);
    setEditingEtsyShopIdDraft(connection.etsy_shop_id ?? "");
    setError(null);
  }

  function handleCancelEditEtsyShopId() {
    setEditingEtsyConnectionId(null);
    setEditingEtsyShopIdDraft("");
  }

  async function handleSaveEtsyShopId(connection: ProviderStoreConnection) {
    setSavingEtsyConnectionId(connection.id);
    setError(null);

    try {
      await updateStoreConnection(connection.id, {
        etsy_shop_id: editingEtsyShopIdDraft.trim() || null
      });
      handleCancelEditEtsyShopId();
      await Promise.all([loadSettings("silent"), refresh()]);
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "Unable to save the Etsy shop link."
      );
    } finally {
      setSavingEtsyConnectionId(null);
    }
  }

  async function handleReviewJoinRequest(joinRequestId: string, approve: boolean) {
    setReviewingJoinRequestId(joinRequestId);
    setReviewingAction(approve ? "approve" : "reject");
    setError(null);

    try {
      if (approve) {
        await approveOrganizationJoinRequest(joinRequestId);
      } else {
        await rejectOrganizationJoinRequest(joinRequestId);
      }
      await loadSettings("silent");
    } catch (reviewError) {
      setError(
        reviewError instanceof Error
          ? reviewError.message
          : "Unable to review the organization access request."
      );
    } finally {
      setReviewingJoinRequestId(null);
      setReviewingAction(null);
    }
  }

  async function handleRemoveMember(userId: string) {
    setRemovingMemberId(userId);
    setError(null);

    try {
      await removeOrganizationMember(userId);
      await loadSettings("silent");
    } catch (removeError) {
      setError(
        removeError instanceof Error ? removeError.message : "Unable to remove the organization member."
      );
    } finally {
      setRemovingMemberId(null);
    }
  }

  async function handleUpdateName() {
    const nextName = draftName.trim();
    if (!nextName) {
      setError("Organization name cannot be empty.");
      return;
    }

    setSavingName(true);
    setError(null);
    try {
      await updateOrganization({ name: nextName });
      await refreshSessionContext();
      setEditingName(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update organization name.");
    } finally {
      setSavingName(false);
    }
  }

  if (loading) {
    return (
      <>
        <PageHeader
          title="Organization settings"
          description="Manage members and connected services."
          preserveActionSpace
        />
        <SettingsSkeleton />
      </>
    );
  }

  if (error && providers.length === 0) {
    return (
      <>
        <PageHeader
          title="Organization settings"
          description="Manage members and connected services."
          preserveActionSpace
        />
        <ResourceError message={error} onRetry={() => void handleRefreshAll()} />
      </>
    );
  }

  return (
    <>
      <div className="space-y-6">
        {editingStoreSeed ? (
          <StoreConnectionDialog
            open={!!editingStoreSeed}
            onOpenChange={(open) => {
              if (!open) setEditingStoreSeed(null);
            }}
            initialSeed={editingStoreSeed.seed}
            storefrontOptions={gelatoStorefrontOptions}
            etsyStoreProjectedCount={etsyStoreCapacity.projected}
            etsyStoreLimit={etsyStoreCapacity.limit}
            onSave={(seed) => handleSaveStoreSeed(editingStoreSeed.credentialKey, seed)}
          />
        ) : null}
      </div>

      <PageHeader
        title="Organization settings"
        description="Manage members and connected services."
        action={
          <Button variant="outline" onClick={() => void handleRefreshAll()} disabled={refreshingAll}>
            <RefreshCw className={cn(refreshingAll && "animate-spin")} data-icon="inline-start" />
            Refresh
          </Button>
        }
      />

      {error ? (
        <div className="mb-6 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <div className="space-y-6">
        <SettingsSection title="Organization details" icon={<Building className="h-4 w-4 text-primary" />}>
          <div className="px-5 py-5">
            <div className="max-w-md">
              <Label htmlFor="org-name" className="text-muted-foreground">Organization name</Label>
              {editingName ? (
                <div className="mt-2 flex items-center gap-2">
                  <Input
                    id="org-name"
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    disabled={savingName}
                    autoFocus
                  />
                  <Button size="sm" onClick={() => void handleUpdateName()} disabled={savingName}>
                    {savingName ? <LoaderCircle className="animate-spin h-4 w-4 mr-2" /> : null}
                    Save
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditingName(false)} disabled={savingName}>
                    Cancel
                  </Button>
                </div>
              ) : (
                <div className="mt-2 flex items-center justify-between gap-4 rounded-md border border-border bg-background/50 px-3 py-2">
                  <span className="font-medium text-foreground">{organization?.name}</span>
                  {sessionContext.membership?.role === "admin" ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 px-2 text-muted-foreground hover:text-foreground"
                      onClick={() => {
                        setDraftName(organization?.name ?? "");
                        setEditingName(true);
                      }}
                    >
                      <Pencil className="h-4 w-4 mr-2" />
                      Rename
                    </Button>
                  ) : null}
                </div>
              )}
            </div>
          </div>
        </SettingsSection>

        <SettingsSection title="Access management" icon={<Users className="h-4 w-4 text-primary" />}>
          <div className="grid gap-5 px-5 py-5">
            <div className="rounded-xl border border-border bg-background/35 px-4 py-4">
              <Badge variant="outline" className="border-primary/25 bg-primary/10 text-primary">
                Invite code
              </Badge>
              <div className="mt-2 font-mono text-lg font-semibold tracking-[0.16em] text-foreground">
                {organization?.join_code ?? "Unavailable"}
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                Share this with members who need access.
              </p>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium text-foreground">Pending requests</div>
                <Badge variant="outline" className="border-border bg-background/50 text-muted-foreground">
                  {joinRequests.length}
                </Badge>
              </div>

              {joinRequests.length === 0 ? (
                <InlineEmptyState
                  title="No pending requests"
                  description="New access requests will appear here."
                />
              ) : (
                <div className="overflow-hidden rounded-lg border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead>Requester</TableHead>
                        <TableHead>Requested</TableHead>
                        <TableHead className="w-[180px] text-left">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {joinRequests.map((joinRequest) => {
                        const isReviewing = reviewingJoinRequestId === joinRequest.id;
                        return (
                          <TableRow key={joinRequest.id}>
                            <TableCell>
                              <div className="font-medium text-foreground">
                                {formatRequesterPrimaryLine(joinRequest)}
                              </div>
                              {formatRequesterSecondaryLine(joinRequest) ? (
                                <div className="mt-1 text-sm text-muted-foreground">
                                  {formatRequesterSecondaryLine(joinRequest)}
                                </div>
                              ) : null}
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {formatDateTime(joinRequest.created_at)}
                            </TableCell>
                            <TableCell>
                              <div className="flex justify-start gap-2">
                                <Button
                                  size="sm"
                                  onClick={() => void handleReviewJoinRequest(joinRequest.id, true)}
                                  disabled={isReviewing}
                                >
                                  {isReviewing && reviewingAction === "approve" ? (
                                    <LoaderCircle className="animate-spin" />
                                  ) : null}
                                  Approve
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => void handleReviewJoinRequest(joinRequest.id, false)}
                                  disabled={isReviewing}
                                >
                                  {isReviewing && reviewingAction === "reject" ? (
                                    <LoaderCircle className="animate-spin" />
                                  ) : null}
                                  Reject
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium text-foreground">Members</div>
                <Badge variant="outline" className="border-border bg-background/50 text-muted-foreground">
                  {members.length}
                </Badge>
              </div>

              {members.length === 0 ? (
                <InlineEmptyState title="No members found" description="Approved members will appear here." />
              ) : (
                <div className="overflow-hidden rounded-lg border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead>User</TableHead>
                        <TableHead>Role</TableHead>
                        <TableHead>Joined</TableHead>
                        <TableHead className="w-[180px] text-left">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {members.map((member) => (
                        <TableRow key={member.user_id}>
                          <TableCell>
                            <div className="font-medium text-foreground">{member.display_name}</div>
                            {member.email && member.email !== member.display_name ? (
                              <div className="mt-1 text-sm text-muted-foreground">{member.email}</div>
                            ) : null}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge
                                variant="outline"
                                className={
                                  member.role === "admin"
                                    ? "border-primary/25 bg-primary/10 text-primary"
                                    : "border-border bg-background/50 text-muted-foreground"
                                }
                              >
                                <span className="capitalize">{member.role}</span>
                              </Badge>
                              {member.is_current_user ? (
                                <Badge variant="outline" className="border-border bg-background/50">
                                  You
                                </Badge>
                              ) : null}
                            </div>
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {formatDateTime(member.joined_at)}
                          </TableCell>
                          <TableCell>
                            <div className="flex justify-start">
                              {member.is_removable ? (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => void handleRemoveMember(member.user_id)}
                                  disabled={removingMemberId === member.user_id}
                                >
                                  {removingMemberId === member.user_id ? (
                                    <LoaderCircle className="animate-spin" />
                                  ) : null}
                                  Remove
                                </Button>
                              ) : (
                                <div className="text-sm text-muted-foreground">
                                  {member.is_current_user ? "Use account page to leave" : "Not removable"}
                                </div>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          </div>
        </SettingsSection>

        <SettingsSection
          title="Etsy accounts"
          description="Connect Etsy shops and see which stores are ready."
          icon={<Link2 className="h-4 w-4 text-primary" />}
        >
          <div className="px-5 py-5">
            <div className="flex flex-col gap-4 pb-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="font-medium text-foreground">Shop discovery</div>
                  <Badge
                    variant="outline"
                    className={
                      etsyConnection.is_connected
                        ? "border-primary/25 bg-primary/10 text-primary"
                        : "border-border bg-background/50 text-muted-foreground"
                    }
                  >
                    {etsyConnection.is_connected ? "Connected" : "Not connected"}
                  </Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
                  {etsyDiscoverySummaryChips.map((chip) => (
                    <MetadataChip key={chip.label} label={chip.label} value={chip.value} />
                  ))}
                </div>
                {etsyConnection.connected_account_count > 0 ? (
                  <p className="mt-3 max-w-2xl text-xs text-muted-foreground">
                    If Etsy opens the wrong account, sign out there first or use a private window.
                  </p>
                ) : null}
              </div>

              <div className="flex shrink-0 flex-wrap gap-2">
                {etsyConnection.is_connected ? (
                  <>
                    <Button
                      type="button"
                      onClick={() => void handleRefreshEtsyConnection()}
                      disabled={syncingEtsy || connectingEtsy}
                    >
                      {syncingEtsy ? <LoaderCircle className="animate-spin" /> : null}
                      Refresh shops
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => void handleOpenEtsyOAuth()}
                      disabled={connectingEtsy || syncingEtsy}
                    >
                      {connectingEtsy ? <LoaderCircle className="animate-spin" /> : null}
                      Add account
                    </Button>
                  </>
                ) : (
                  <Button
                    type="button"
                    onClick={() => void handleOpenEtsyOAuth()}
                    disabled={connectingEtsy}
                  >
                    {connectingEtsy ? <LoaderCircle className="animate-spin" /> : null}
                    Connect account
                  </Button>
                )}
              </div>
            </div>

            {etsyConnection.connected_accounts.length > 0 ? (
              <div className="border-t border-border/70 py-5">
                <div className="flex items-baseline justify-between gap-3">
                  <div className="text-sm font-medium text-foreground">Connected accounts</div>
                  <div className="text-xs text-muted-foreground">
                    {etsyConnection.connected_account_count} connected
                  </div>
                </div>
                <div className="mt-2 divide-y divide-border/60">
                  {etsyConnection.connected_accounts.map((account) => (
                    <div
                      key={account.credential_key}
                      className="flex items-center justify-between gap-3 py-3 first:pt-2 last:pb-0"
                    >
                      <div className="min-w-0">
                        <div className="font-medium text-foreground">
                          {account.shop_name ?? "Etsy account"}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          Updated {formatDateTime(account.last_synced_at)}
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        {!account.scopes.includes("transactions_r") ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => void handleOpenEtsyOAuth(account.seller_user_id)}
                            disabled={connectingEtsy || syncingEtsy}
                          >
                            Grant analytics access
                          </Button>
                        ) : (
                          <Badge
                            variant="outline"
                            className="border-primary/25 bg-primary/10 text-primary"
                          >
                            Analytics ready
                          </Badge>
                        )}
                        {account.shop_url ? (
                          <Button asChild type="button" variant="ghost" size="sm">
                            <a href={account.shop_url} target="_blank" rel="noreferrer">
                              Open shop
                              <ExternalLink className="ml-2 h-4 w-4" />
                            </a>
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="min-w-0 border-t border-border/70 pt-5">
              <div className="flex items-baseline justify-between gap-3">
                <div>
                  <div className="font-medium text-foreground">Etsy shops</div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {etsyStoreConnectionCount === 0
                      ? "Connect a fulfillment store to link Etsy shops."
                      : etsyConnection.unmapped_connection_count > 0
                        ? `${etsyConnection.unmapped_connection_count} store${etsyConnection.unmapped_connection_count === 1 ? "" : "s"} need setup in Printing partners.`
                        : "All connected stores are ready."}
                  </p>
                </div>
                <div className="text-xs text-muted-foreground">
                  {etsyConnection.connected_shops.length} found
                </div>
              </div>

              <div className="mt-3 divide-y divide-border/70">
                {etsyConnection.connected_shops.length === 0 ? (
                  <InlineEmptyState
                    title={
                      etsyConnection.is_connected
                        ? "No Etsy shops found yet"
                        : "Connect Etsy to find shops"
                    }
                    description={
                      etsyConnection.is_connected
                        ? "Try refreshing your Etsy shops."
                        : "Your connected shops will appear here."
                    }
                  />
                ) : (
                  etsyConnection.connected_shops.map((shop) => {
                    const matchedConnections = resolveEtsyShopMatchedConnections(
                      shop,
                      storeConnections
                    );
                    const hasMatch =
                      matchedConnections.length > 0 ||
                      shop.matched_connection_ids.length > 0 ||
                      Boolean(shop.matched_connection_id);

                    return (
                      <div
                        key={shop.shop_id}
                        className="grid gap-3 py-4 first:pt-3 last:pb-0 md:grid-cols-[minmax(0,1fr)_minmax(220px,0.9fr)_auto] md:items-center"
                      >
                        <div className="min-w-0">
                          <div className="font-medium text-foreground">{shop.shop_name}</div>
                          <Badge
                            variant="outline"
                            className={
                              hasMatch
                                ? "mt-2 border-primary/25 bg-primary/10 text-primary"
                                : "mt-2 border-border bg-background/50 text-muted-foreground"
                            }
                          >
                            {hasMatch ? "Ready" : "Needs setup"}
                          </Badge>
                        </div>

                        <div className="min-w-0">
                          <div className="text-xs font-medium text-muted-foreground">
                            Fulfillment stores
                          </div>
                          {matchedConnections.length > 0 ? (
                            <div className="mt-2 space-y-1.5">
                              {matchedConnections.map((connection) => (
                                <div
                                  key={connection.id}
                                  className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground"
                                >
                                  <span className="font-medium text-foreground">
                                    {connection.provider}
                                  </span>
                                  <span>{connection.storeLabel}</span>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="mt-1 text-sm text-muted-foreground">
                              Link this shop in Printing partners below.
                            </p>
                          )}
                        </div>

                        {shop.shop_url ? (
                          <Button asChild type="button" variant="ghost" size="sm">
                            <a href={shop.shop_url} target="_blank" rel="noreferrer">
                              Open shop
                              <ExternalLink className="ml-2 h-4 w-4" />
                            </a>
                          </Button>
                        ) : null}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </SettingsSection>

        <SettingsSection title="Printing partners" icon={<PlugZap className="h-4 w-4 text-primary" />}>
          <div className="space-y-5 px-5 py-5">
            <div className="grid gap-4 lg:grid-cols-2">
              {providerKeys.map((providerKey) => (
                <ProviderSelectorCard
                  key={providerKey}
                  providerKey={providerKey}
                  provider={providers.find((provider) => provider.id === providerKey) ?? null}
                  credentialStatus={credentialStatuses[providerKey]}
                  storeCount={providerStoreCounts[providerKey]}
                  isSelected={selectedProvider === providerKey}
                  disabled={providerSetupLocked}
                  onSelect={() =>
                    setSelectedProvider((current) => (current === providerKey ? null : providerKey))
                  }
                />
              ))}
            </div>

            {providerSetupLocked ? (
              <div className="rounded-md border border-border bg-background/25 px-4 py-3 text-sm text-muted-foreground">
                Connect Etsy first to set up Printify or Gelato.
              </div>
            ) : null}

            {selectedProvider && selectedCredentialStatus ? (
              <div className="border-t border-border/80 pt-5">
                <div className="border-b border-border/70 pb-5">
                  <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
                    <div className="flex items-start gap-3">
                      <ProviderLogo provider={selectedProvider} />
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-base font-semibold text-foreground">
                            {selectedProviderRecord?.name ?? providerLabel(selectedProvider)}
                          </h3>
                          <ProviderStatusBadge isConfigured={selectedCredentialStatus.is_configured} />
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {selectedProvider === "gelato"
                            ? "Stores update from recent Gelato orders. You can also add a store manually."
                            : `Manage your connected ${providerLabel(selectedProvider)} stores.`}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 text-sm xl:justify-end">
                      <div className="text-muted-foreground">
                        <span className="mr-2 text-xs">Stores</span>
                        <span className="text-foreground">
                          {formatStorefrontCount(providerStoreCounts[selectedProvider])}
                        </span>
                      </div>
                      <div className="text-muted-foreground">
                        <span className="mr-2 text-xs">Last updated</span>
                        <span className="text-foreground">
                          {formatDateTime(selectedProviderRecord?.last_sync_at ?? null)}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="grid items-start gap-6 pt-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.85fr)]">
                  <div className="space-y-3">
                    <div className="font-medium text-foreground">Connections</div>
                    {selectedCredentialGroups.length === 0 ? (
                      <InlineEmptyState
                        title={`No ${providerLabel(selectedProvider)} connection yet`}
                        description="Add an access key to connect this partner."
                      />
                    ) : (
                      selectedCredentialGroups.map(({ credential, connections }) => {
                        const actionKey = buildCredentialActionKey(
                          selectedProvider,
                          credential.credential_key
                        );

                        return (
                          <CredentialCard
                            key={credential.credential_key}
                            provider={selectedProvider}
                            credential={credential}
                            connections={connections}
                            setupLocked={providerSetupLocked}
                            isSyncing={syncingCredential === actionKey}
                            isDeleting={deletingCredential === actionKey}
                            deletingStoreId={deletingStoreId}
                            onSync={() => void handleSync(selectedProvider, credential.credential_key)}
                            onDelete={() =>
                              void handleDeleteCredentials(selectedProvider, credential.credential_key)
                            }
                            onDeleteStore={(connectionId) => void handleDeleteStore(connectionId)}
                            onAddStore={() =>
                              setEditingStoreSeed({ credentialKey: credential.credential_key, seed: null })
                            }
                            onEditStore={
                              selectedProvider === "gelato" && !providerSetupLocked
                                ? (connection) =>
                                    setEditingStoreSeed({
                                      credentialKey: credential.credential_key,
                                      seed: createManualStoreSeed({
                                        provider_store_id: connection.provider_store_id,
                                        storefront_type: connection.storefront_type,
                                        storefront_display_name: connection.storefront_display_name,
                                        label: connection.label || null,
                                        etsy_shop_id: connection.etsy_shop_id
                                      })
                                    })
                                : undefined
                            }
                            editingEtsyConnectionId={editingEtsyConnectionId}
                            editingEtsyShopIdDraft={editingEtsyShopIdDraft}
                            savingEtsyConnectionId={savingEtsyConnectionId}
                            onStartEditEtsyShopId={handleStartEditEtsyShopId}
                            onCancelEditEtsyShopId={handleCancelEditEtsyShopId}
                            onChangeEtsyShopIdDraft={setEditingEtsyShopIdDraft}
                            onSaveEtsyShopId={handleSaveEtsyShopId}
                          />
                        );
                      })
                    )}
                  </div>

                  <div className="border-t border-border/70 pt-5 xl:border-l xl:border-t-0 xl:pl-6 xl:pt-0">
                    <div className="flex items-center gap-2">
                      <Plus className="h-4 w-4 text-primary" />
                      <div className="font-medium text-foreground">Add connection</div>
                    </div>

                    <div className="mt-4 grid gap-4">
                      <div className="grid gap-2">
                        <Label htmlFor={`${selectedProvider}-display-name`}>Connection name</Label>
                        <Input
                          id={`${selectedProvider}-display-name`}
                          value={drafts[selectedProvider].display_name}
                          disabled={providerSetupLocked}
                          onChange={(event) =>
                            setDrafts((current) => ({
                              ...current,
                              [selectedProvider]: {
                                ...current[selectedProvider],
                                display_name: event.target.value
                              }
                            }))
                          }
                          placeholder={
                            selectedProvider === "printify"
                              ? "Main Printify connection"
                              : "Main Gelato connection"
                          }
                        />
                      </div>

                      <div className="grid gap-2">
                        <Label htmlFor={`${selectedProvider}-secret`}>
                          Access key
                        </Label>
                        <PasswordInput
                          id={`${selectedProvider}-secret`}
                          autoComplete="off"
                          visibilityLabel="access key"
                          disabled={providerSetupLocked}
                          value={
                            selectedProvider === "printify"
                              ? drafts.printify.api_token
                              : drafts.gelato.api_key
                          }
                          onChange={(event) =>
                            setDrafts((current) => ({
                              ...current,
                              [selectedProvider]:
                                selectedProvider === "printify"
                                  ? {
                                      ...current.printify,
                                      api_token: event.target.value
                                    }
                                  : {
                                      ...current.gelato,
                                      api_key: event.target.value
                                    }
                            }))
                          }
                          placeholder={
                            selectedProvider === "printify"
                              ? "Paste your Printify access key"
                              : "Paste your Gelato access key"
                          }
                        />
                      </div>

                      <Button
                        type="button"
                        onClick={() => void handleSave(selectedProvider)}
                        disabled={providerSetupLocked || savingProvider === selectedProvider}
                        className="w-full"
                      >
                        {savingProvider === selectedProvider ? (
                          <LoaderCircle className="animate-spin" />
                        ) : null}
                        Save connection
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <InlineEmptyState
                title="Select a partner"
                description="Choose Printify or Gelato to manage connections and stores."
              />
            )}
          </div>
        </SettingsSection>
      </div>
    </>
  );
}
