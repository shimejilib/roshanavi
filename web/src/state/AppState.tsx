import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

export type Selection = { kind: 'topic' | 'node'; id: string } | null;

interface AppStateValue {
  tab: string;
  setTab: (tab: string) => void;
  selection: Selection;
  select: (selection: Selection) => void;
  /** Topic the Inject tab should prefill (set by "inject to this topic"). */
  injectTopic: string | null;
  openInject: (topic: string) => void;
}

const AppStateContext = createContext<AppStateValue | null>(null);

export function AppStateProvider({ children, initialTab }: { children: ReactNode; initialTab: string }) {
  const [tab, setTab] = useState(initialTab);
  const [selection, select] = useState<Selection>(null);
  const [injectTopic, setInjectTopic] = useState<string | null>(null);
  const value = useMemo<AppStateValue>(
    () => ({
      tab,
      setTab,
      selection,
      select,
      injectTopic,
      openInject: (topic: string) => {
        setInjectTopic(topic);
        setTab('inject');
      },
    }),
    [tab, selection, injectTopic],
  );
  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState(): AppStateValue {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error('useAppState must be used inside <AppStateProvider>');
  return ctx;
}
