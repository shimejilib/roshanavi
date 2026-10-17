// /ws/scenarios: the running scenario's progress and the record-mode timeline, shared by
// the Scenarios tab and the "recording" badge in the top bar.

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ReconnectingSocket, wsUrl } from '../api/reconnect';
import type { RecordEvent, RecordStatus, RunResult, ScenarioFrame } from '../api/scenarioTypes';

export const MAX_TIMELINE_EVENTS = 3000;

interface ScenarioLiveValue {
  run: RunResult | null;
  running: boolean;
  record: RecordStatus;
  events: RecordEvent[];
}

const EMPTY: ScenarioLiveValue = { run: null, running: false, record: { active: false, session: null }, events: [] };
const ScenarioLiveContext = createContext<ScenarioLiveValue>(EMPTY);

function isFrame(data: unknown): data is ScenarioFrame {
  return typeof data === 'object' && data !== null && 'record' in data;
}

/** Appends a frame's events; a new recording session starts a new timeline. */
export function mergeEvents(previous: ScenarioLiveValue, frame: ScenarioFrame): ScenarioLiveValue {
  const sessionId = frame.record.session?.id ?? null;
  const sameSession = (previous.record.session?.id ?? null) === sessionId;
  const base = sameSession ? previous.events : [];
  const lastSeq = base.at(-1)?.seq ?? 0;
  const fresh = frame.record.events.filter((e) => e.seq > lastSeq);
  const merged = fresh.length ? [...base, ...fresh].slice(-MAX_TIMELINE_EVENTS) : base;
  return {
    run: frame.run ?? previous.run,
    running: frame.running,
    record: { active: frame.record.active, session: frame.record.session },
    events: merged,
  };
}

export function ScenarioLiveProvider({ children }: { children: ReactNode }) {
  const [value, setValue] = useState<ScenarioLiveValue>(EMPTY);
  useEffect(() => {
    const socket = new ReconnectingSocket({
      url: wsUrl('/ws/scenarios'),
      onStatus: () => undefined,
      onMessage: (data) => {
        if (isFrame(data)) setValue((prev) => mergeEvents(prev, data));
      },
    });
    return () => socket.close();
  }, []);
  const memo = useMemo(() => value, [value]);
  return <ScenarioLiveContext.Provider value={memo}>{children}</ScenarioLiveContext.Provider>;
}

export function useScenarioLive(): ScenarioLiveValue {
  return useContext(ScenarioLiveContext);
}
