import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import type { DialogRequest } from '../dialogs/dialogTypes';

export type Selection = { kind: 'topic' | 'node'; id: string } | null;

/** Map isolation: show only a node's inputs/outputs, or a topic's upstream/downstream. */
export type Isolation = { mode: 'io' | 'flow'; elementId: string } | null;

interface AppStateValue {
  tab: string;
  setTab: (tab: string) => void;
  selection: Selection;
  select: (selection: Selection) => void;
  /** Topic the Inject tab should prefill (set by "inject to this topic"). */
  injectTopic: string | null;
  openInject: (topic: string) => void;
  /** Log shown in the Launcher tab (target id or `_build`). */
  logTarget: string | null;
  openLogs: (targetId: string, switchTab?: boolean) => void;
  /** Modal dialog shown above everything (create input node, parameters, ...). */
  dialog: DialogRequest | null;
  openDialog: (dialog: DialogRequest) => void;
  closeDialog: () => void;
  isolation: Isolation;
  setIsolation: (isolation: Isolation) => void;
  /** Launcher requests from other tabs: open the add-node picker or a target's settings. */
  launcherRequest: { kind: 'add' } | { kind: 'edit'; targetId: string } | null;
  openLauncher: (request: { kind: 'add' } | { kind: 'edit'; targetId: string }) => void;
  clearLauncherRequest: () => void;
  /** Topic preselected when the recordings tab opens from a map menu. */
  recordTopic: string | null;
  openRecord: (topic: string) => void;
}

const AppStateContext = createContext<AppStateValue | null>(null);

export function AppStateProvider({ children, initialTab }: { children: ReactNode; initialTab: string }) {
  const [tab, setTab] = useState(initialTab);
  const [selection, select] = useState<Selection>(null);
  const [injectTopic, setInjectTopic] = useState<string | null>(null);
  const [logTarget, setLogTarget] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogRequest | null>(null);
  const [isolation, setIsolation] = useState<Isolation>(null);
  const [launcherRequest, setLauncherRequest] = useState<AppStateValue['launcherRequest']>(null);
  const [recordTopic, setRecordTopic] = useState<string | null>(null);
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
      logTarget,
      openLogs: (targetId: string, switchTab = true) => {
        setLogTarget(targetId);
        if (switchTab) setTab('launcher');
      },
      dialog,
      openDialog: setDialog,
      closeDialog: () => setDialog(null),
      isolation,
      setIsolation,
      launcherRequest,
      openLauncher: (request) => {
        setLauncherRequest(request);
        setTab('launcher');
      },
      clearLauncherRequest: () => setLauncherRequest(null),
      recordTopic,
      openRecord: (topic: string) => {
        setRecordTopic(topic);
        setTab('recordings');
      },
    }),
    [tab, selection, injectTopic, logTarget, dialog, isolation, launcherRequest, recordTopic],
  );
  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState(): AppStateValue {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error('useAppState must be used inside <AppStateProvider>');
  return ctx;
}
