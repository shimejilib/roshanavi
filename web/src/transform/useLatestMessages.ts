// Latest message of each input topic over /ws/echo (left side of the transform preview).

import { useEffect, useState } from 'react';
import { ReconnectingSocket, wsUrl } from '../api/reconnect';
import type { EchoMessage } from '../api/types';
import { topicPath } from '../lib/topics';

const POLICY_VIOLATION = 1008;
const TOPIC_RE = /^(\/[A-Za-z_][A-Za-z0-9_]*)+$/;

function isEcho(value: unknown): value is EchoMessage {
  return typeof value === 'object' && value !== null && 'msg' in value && 'seq' in value;
}

/** `{topic: latest message (display dict)}` for the given topics; absent until one arrives. */
export function useLatestMessages(topics: readonly string[]): Record<string, Record<string, unknown>> {
  const [latest, setLatest] = useState<Record<string, Record<string, unknown>>>({});
  const key = topics.filter((topic) => TOPIC_RE.test(topic)).join('\n');

  useEffect(() => {
    const valid = key ? key.split('\n') : [];
    setLatest((prev) => Object.fromEntries(Object.entries(prev).filter(([topic]) => valid.includes(topic))));
    const sockets = valid.map((topic) => new ReconnectingSocket({
      url: wsUrl(topicPath('/ws/echo', topic)),
      fatalCodes: [POLICY_VIOLATION],
      onStatus: () => undefined,
      onMessage: (data) => {
        if (isEcho(data) && typeof data.msg === 'object' && data.msg !== null) {
          setLatest((prev) => ({ ...prev, [topic]: data.msg as Record<string, unknown> }));
        }
      },
    }));
    return () => sockets.forEach((socket) => socket.close());
  }, [key]);

  return latest;
}
