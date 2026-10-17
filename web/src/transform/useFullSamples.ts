// Whole (untruncated) latest messages for the transform preview (#10).
//
// The echo view shows long arrays cut to 32 items. A transform such as `len(msg.points)` computed on that copy
// would differ from the running node, so for topics whose echo copy is truncated the server's
// GET /api/echo/<topic>/sample is polled. The server only sends the whole message up to a size cap; a bigger
// one stays truncated here (and the preview says so).

import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { hasTruncation } from './sampleTruncation';

const POLL_MS = 1000;

type Sample = Record<string, unknown>;

/** `{topic: whole message}` for the topics whose echo copy in `display` is truncated and fits the server's cap. */
export function useFullSamples(display: Readonly<Record<string, Sample>>): Record<string, Sample> {
  const [full, setFull] = useState<Record<string, Sample>>({});
  const needed = Object.entries(display).filter(([, msg]) => hasTruncation(msg)).map(([topic]) => topic);
  const key = needed.join('\n');

  useEffect(() => {
    const topics = key ? key.split('\n') : [];
    setFull((prev) => Object.fromEntries(Object.entries(prev).filter(([topic]) => topics.includes(topic))));
    if (topics.length === 0) return undefined;
    let cancelled = false;
    const poll = () => {
      for (const topic of topics) {
        api.echoSample(topic)
          .then((res) => {
            if (cancelled) return;
            const whole = res.msg !== null && !res.capped ? (res.msg as Sample) : null;
            setFull((prev) => {
              if (whole === null) return Object.fromEntries(Object.entries(prev).filter(([name]) => name !== topic));
              return { ...prev, [topic]: whole };
            });
          })
          .catch(() => undefined); // keep the echo copy
      }
    };
    poll();
    const timer = window.setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [key]);

  return full;
}
