// Polls the launch takeover status and the leftover processes for the banner.

import { useCallback, useEffect, useState } from 'react';
import { describeError } from '../api/client';
import { takeoverApi, type LeftoverState, type TakeoverStatus } from '../api/takeoverTypes';

const POLL_MS = 3000;

export interface TakeoverState {
  status: TakeoverStatus | null;
  leftovers: LeftoverState | null;
  error: string | null;
  reload: () => void;
  reloadLeftovers: () => void;
}

export function useTakeover(): TakeoverState {
  const [status, setStatus] = useState<TakeoverStatus | null>(null);
  const [leftovers, setLeftovers] = useState<LeftoverState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    takeoverApi
      .status()
      .then((body) => {
        setStatus(body);
        setError(null);
      })
      .catch((err: unknown) => setError(describeError(err)));
  }, []);
  const reloadLeftovers = useCallback(() => {
    takeoverApi
      .leftovers()
      .then(setLeftovers)
      .catch(() => setLeftovers(null));
  }, []);
  useEffect(() => {
    reload();
    reloadLeftovers(); // once: leftovers only come from a previous, force-killed run
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [reload, reloadLeftovers]);
  return { status, leftovers, error, reload, reloadLeftovers };
}
