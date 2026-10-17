import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ReconnectingSocket, wsUrl, type SocketStatus } from '../api/reconnect';
import { DEFAULT_WINDOW, type WindowSec } from '../timing/timing';
import { applyLive, EMPTY_LIVE, isLiveMessage, type LiveData } from './live';

interface LiveContextValue {
  live: LiveData;
  status: SocketStatus;
  url: string;
  paused: boolean;
  setPaused: (paused: boolean) => void;
  /** Averaging window of every hz / bandwidth shown (the server computes it). */
  windowSec: WindowSec;
  setWindowSec: (sec: WindowSec) => void;
}

const LiveContext = createContext<LiveContextValue | null>(null);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [windowSec, setWindowSec] = useState<WindowSec>(DEFAULT_WINDOW);
  const url = useMemo(() => wsUrl(`/ws/live?window=${windowSec}`), [windowSec]);
  const [status, setStatus] = useState<SocketStatus>('connecting');
  const [live, setLive] = useState<LiveData>(EMPTY_LIVE);
  const [paused, setPausedState] = useState(false);
  // Frames keep being applied to `latest` while paused so resume shows fresh data.
  const latest = useRef<LiveData>(EMPTY_LIVE);
  const pausedRef = useRef(false);

  useEffect(() => {
    const socket = new ReconnectingSocket({
      url,
      onStatus: setStatus,
      onMessage: (data) => {
        if (!isLiveMessage(data)) return;
        latest.current = applyLive(latest.current, data, Date.now());
        if (!pausedRef.current) setLive(latest.current);
      },
    });
    return () => socket.close();
  }, [url]);

  const value = useMemo<LiveContextValue>(
    () => ({
      live,
      status,
      url,
      paused,
      setPaused: (next: boolean) => {
        pausedRef.current = next;
        setPausedState(next);
        if (!next) setLive(latest.current);
      },
      windowSec,
      setWindowSec,
    }),
    [live, status, url, paused, windowSec],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveContextValue {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error('useLive must be used inside <LiveProvider>');
  return ctx;
}
