// Full resource snapshot over /ws/resources (1 Hz) while the リソース tab is open.

import { useEffect, useState } from 'react';
import { ReconnectingSocket, wsUrl, type SocketStatus } from '../api/reconnect';
import type { ResourceSnapshot } from '../api/resourceTypes';

const POLICY_VIOLATION = 1008;

export function isSnapshot(value: unknown): value is ResourceSnapshot {
  return typeof value === 'object' && value !== null && typeof (value as { available?: unknown }).available === 'boolean';
}

export function useResourceStream(): { snapshot: ResourceSnapshot | null; status: SocketStatus } {
  const [snapshot, setSnapshot] = useState<ResourceSnapshot | null>(null);
  const [status, setStatus] = useState<SocketStatus>('connecting');
  useEffect(() => {
    const socket = new ReconnectingSocket({
      url: wsUrl('/ws/resources'),
      onStatus: setStatus,
      onMessage: (data) => {
        if (isSnapshot(data)) setSnapshot(data);
      },
      fatalCodes: [POLICY_VIOLATION],
    });
    return () => socket.close();
  }, []);
  return { snapshot, status };
}
