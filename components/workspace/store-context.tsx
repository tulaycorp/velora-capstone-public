"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState
} from "react";
import {
  fetchProviders,
  fetchStoreConnections,
  type PodProvider,
  type ProviderStoreConnection
} from "@/lib/backend-api";
import {
  persistStoreSelectionInBrowser,
  readPersistedStoreSelectionFromBrowser,
  syncStoreSelection
} from "@/components/workspace/store-context-state";
import { useRefetchOnWindowFocus } from "@/hooks/use-refetch-on-window-focus";

type StoreContextValue = {
  providers: PodProvider[];
  storeConnections: ProviderStoreConnection[];
  selectedStoreId: string;
  selectedStore: ProviderStoreConnection | null;
  selectionReady: boolean;
  loading: boolean;
  error: string | null;
  setSelectedStoreId: (value: string) => void;
  refresh: (options?: { silent?: boolean }) => Promise<void>;
};

const StoreContext = createContext<StoreContextValue | null>(null);

export function StoreContextProvider({
  children,
  initialSelectedStoreId = null
}: {
  children: React.ReactNode;
  initialSelectedStoreId?: string | null;
}) {
  const [providers, setProviders] = useState<PodProvider[]>([]);
  const [storeConnections, setStoreConnections] = useState<ProviderStoreConnection[]>([]);
  const [selectedStoreId, setSelectedStoreIdState] = useState(initialSelectedStoreId ?? "all");
  const [selectionReady, setSelectionReady] = useState(initialSelectedStoreId !== null);
  const [hasLoadedStoreConnections, setHasLoadedStoreConnections] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const lastLoadedAtRef = useRef(0);

  useEffect(() => {
    const savedValue = readPersistedStoreSelectionFromBrowser();
    if (savedValue) {
      setSelectedStoreIdState(savedValue);
    }
    setSelectionReady(true);
  }, [initialSelectedStoreId]);

  const refresh = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;

    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const [nextProviders, nextConnections] = await Promise.all([
        fetchProviders(),
        fetchStoreConnections()
      ]);
      setProviders(nextProviders);
      setStoreConnections(nextConnections);
      setHasLoadedStoreConnections(true);
      lastLoadedAtRef.current = Date.now();
      setError(null);
    } catch (refreshError) {
      if (!silent) {
        setError(
          refreshError instanceof Error
            ? refreshError.message
            : "Unable to load stores right now."
        );
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useRefetchOnWindowFocus(
    useCallback(async () => {
      await refresh({ silent: true });
    }, [refresh]),
    {
      shouldRefetch: () =>
        Date.now() - lastLoadedAtRef.current >= 60_000
    }
  );

  function persistSelectedStoreId(value: string) {
    setSelectedStoreIdState(value);
    persistStoreSelectionInBrowser(value);
  }

  useEffect(() => {
    const selectionSyncState = syncStoreSelection({
      canValidateSelection: hasLoadedStoreConnections,
      selectedStoreId,
      storeConnections
    });

    if (selectionSyncState.shouldUpdateSelectedStoreId) {
      persistSelectedStoreId(selectionSyncState.nextSelectedStoreId);
    }
  }, [hasLoadedStoreConnections, selectedStoreId, storeConnections]);

  function setSelectedStoreId(value: string) {
    persistSelectedStoreId(value);
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  }

  const selectedStore =
    selectedStoreId === "all"
      ? null
      : storeConnections.find((connection) => connection.id === selectedStoreId) ?? null;

  return (
    <StoreContext.Provider
      value={{
        providers,
        storeConnections,
        selectedStoreId,
        selectedStore,
        selectionReady,
        loading,
        error,
        setSelectedStoreId,
        refresh
      }}
    >
      {children}
    </StoreContext.Provider>
  );
}

export function useStoreContext() {
  const context = useContext(StoreContext);
  if (!context) {
    throw new Error("useStoreContext must be used inside StoreContextProvider.");
  }
  return context;
}
