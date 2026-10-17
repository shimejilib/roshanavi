import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { MediaTypeInfo } from '../api/mediaTypes';

const DEBOUNCE_MS = 300;

/** Supported media types and, for a topic, the type its endpoints use (debounced). */
export function useMediaTypes(topic: string, enabled: boolean): { info: MediaTypeInfo | null; error: string | null } {
  const [info, setInfo] = useState<MediaTypeInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    const valid = topic.trim().startsWith('/') && topic.trim().length > 1;
    const timer = setTimeout(() => {
      api
        .mediaTypes(valid ? topic.trim() : undefined)
        .then((body) => {
          if (cancelled) return;
          setInfo(body);
          setError(null);
        })
        .catch((err: unknown) => !cancelled && setError(describeError(err)));
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [topic, enabled]);
  return { info, error };
}
