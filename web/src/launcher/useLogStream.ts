// Live log lines of one target (or the build) over /ws/logs/{id}.

import { useCallback, useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import { ReconnectingSocket, wsUrl, type SocketStatus } from '../api/reconnect';
import type { LogLine } from '../api/types';
import { mergeLines } from './logs';

interface LogFrame {
  lines: LogLine[];
}

function isLogFrame(value: unknown): value is LogFrame {
  return typeof value === 'object' && value !== null && Array.isArray((value as LogFrame).lines);
}

export interface LogStream {
  lines: LogLine[];
  status: SocketStatus;
  error: string | null;
  clear: () => void;
}

export function useLogStream(logId: string | null): LogStream {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [status, setStatus] = useState<SocketStatus>('closed');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLines([]);
    setError(null);
    if (!logId) return undefined;
    const socket = new ReconnectingSocket({
      url: wsUrl(`/ws/logs/${encodeURIComponent(logId)}`),
      onStatus: setStatus,
      fatalCodes: [1008],
      onMessage: (data) => {
        if (isLogFrame(data)) setLines((prev) => mergeLines(prev, data.lines));
        else if (typeof data === 'object' && data !== null && 'error' in data) setError(String((data as { error: { message?: string } }).error.message ?? ''));
      },
    });
    return () => socket.close();
  }, [logId]);

  const clear = useCallback(() => {
    if (!logId) return;
    setLines([]);
    api.clearLogs(logId).catch((err: unknown) => setError(describeError(err)));
  }, [logId]);

  return { lines, status, error, clear };
}
