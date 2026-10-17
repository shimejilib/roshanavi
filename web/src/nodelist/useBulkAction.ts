// Runs a confirmed bulk plan: launcher target actions + lifecycle goals, all in parallel.

import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { NodeListResponse } from '../api/nodeListTypes';
import type { ControlAction } from '../graph/nodeControl';
import { t } from '../i18n';
import { bulkConfirmText, isEmptyPlan, planFromSnapshot, type BulkPlan } from './bulk';

export interface BulkMessage {
  kind: 'ok' | 'error';
  text: string;
}

export interface BulkState {
  pending: { plan: BulkPlan; text: string } | null;
  /** Plan from one node-list snapshot (rows + targets of the same response). */
  request: (action: ControlAction, snapshot: NodeListResponse, selected: ReadonlySet<string>) => void;
  confirm: () => void;
  cancel: () => void;
  busy: boolean;
  message: BulkMessage | null;
}

async function runPlan(plan: BulkPlan): Promise<string[]> {
  const jobs: Promise<unknown>[] = [
    ...plan.targets.map((s) => api.targetAction(s.targetId, plan.action)),
    ...plan.lifecycle.map((s) => api.changeLifecycle(s.node, { goal: s.goal, allow_external: s.external })),
  ];
  const names = [...plan.targets.map((s) => s.label), ...plan.lifecycle.map((s) => s.node)];
  const results = await Promise.allSettled(jobs);
  return results.flatMap((r, i) => (r.status === 'rejected' ? [`${names[i]}: ${describeError(r.reason)}`] : []));
}

export function useBulkAction(onDone: () => void): BulkState {
  const [pending, setPending] = useState<BulkState['pending']>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<BulkMessage | null>(null);

  const request = (action: ControlAction, snapshot: NodeListResponse, selected: ReadonlySet<string>) => {
    const plan = planFromSnapshot(action, snapshot, selected);
    if (isEmptyPlan(plan)) {
      setMessage({ kind: 'error', text: bulkConfirmText(plan) || t('nodes.bulk.nothing') });
      return;
    }
    setMessage(null);
    setPending({ plan, text: bulkConfirmText(plan) });
  };

  const confirm = () => {
    const current = pending;
    setPending(null);
    if (!current) return;
    setBusy(true);
    runPlan(current.plan)
      .then((failures) => {
        const count = current.plan.targets.length + current.plan.lifecycle.length;
        setMessage(failures.length === 0
          ? { kind: 'ok', text: t('nodes.bulk.done', { n: count }) }
          : { kind: 'error', text: [t('nodes.bulk.failed', { n: failures.length }), ...failures].join('\n') });
      })
      .finally(() => {
        setBusy(false);
        onDone();
      });
  };
  return { pending, request, confirm, cancel: () => setPending(null), busy, message };
}
