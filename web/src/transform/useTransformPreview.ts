// Debounced dry run of the transform being edited (POST /api/transforms/preview).

import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { PreviewResult, TransformSpec } from '../api/transformTypes';
import type { Result } from '../inject/buildRequest';

const DEBOUNCE_MS = 300;

export interface PreviewState {
  result: PreviewResult | null;
  /** The form cannot be turned into a spec yet (plain-language reason). */
  formError: string | null;
  /** The request itself failed (network, server). */
  requestError: string | null;
  busy: boolean;
}

export function useTransformPreview(spec: Result<TransformSpec>, samples: Record<string, Record<string, unknown>>): PreviewState {
  const [state, setState] = useState<PreviewState>({ result: null, formError: null, requestError: null, busy: false });
  const specKey = JSON.stringify(spec);
  const samplesKey = JSON.stringify(samples);

  useEffect(() => {
    if (!spec.ok) {
      setState({ result: null, formError: spec.error, requestError: null, busy: false });
      return undefined;
    }
    let cancelled = false;
    setState((prev) => ({ ...prev, formError: null, busy: true }));
    const timer = window.setTimeout(() => {
      api
        .previewTransform(spec.value, samples)
        .then((result) => !cancelled && setState({ result, formError: null, requestError: null, busy: false }))
        .catch((err: unknown) => !cancelled && setState({ result: null, formError: null, requestError: describeError(err), busy: false }));
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // The keys capture the values; `spec` / `samples` objects are rebuilt every render.
  }, [specKey, samplesKey]);

  return state;
}
