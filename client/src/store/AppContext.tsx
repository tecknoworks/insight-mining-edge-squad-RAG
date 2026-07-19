// App-wide state via React Context + hooks. This is a minimal skeleton — real
// state (uploaded datasets, selected cluster, chat history) is added as the
// pipeline features land.
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

interface AppState {
  apiReady: boolean;
  setApiReady: (ready: boolean) => void;
}

const AppContext = createContext<AppState | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [apiReady, setApiReady] = useState(false);
  const value = useMemo(() => ({ apiReady, setApiReady }), [apiReady]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppState(): AppState {
  const ctx = useContext(AppContext);
  if (ctx === undefined) {
    throw new Error('useAppState must be used within an AppProvider');
  }
  return ctx;
}
