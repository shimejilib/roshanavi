// Delete the selected registrations (after confirmation) and offer 「元に戻す」 for 10 s.

import { useEffect, useRef, useState } from 'react';
import { describeError } from '../api/client';
import type { NodeListResponse } from '../api/nodeListTypes';
import { takeoverApi } from '../api/takeoverTypes';
import { t } from '../i18n';
import type { BulkMessage } from './useBulkAction';
import { planRemoveFromSnapshot, removeConfirmText, type RemovePlan } from './remove';

export const UNDO_MS = 10_000;

export interface RemoveState {
  pending: { plan: RemovePlan; text: string } | null;
  request: (snapshot: NodeListResponse, selected: ReadonlySet<string>) => void;
  confirm: () => void;
  cancel: () => void;
  undo: () => void;
  /** Present while 「元に戻す」 is offered. */
  undoable: { count: number } | null;
  busy: boolean;
  message: BulkMessage | null;
}

export function useRemoveAction(onDone: () => void): RemoveState {
  const [pending, setPending] = useState<RemoveState['pending']>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<BulkMessage | null>(null);
  const [undoable, setUndoable] = useState<{ id: string; count: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const offerUndo = (id: string, count: number) => {
    if (timer.current) clearTimeout(timer.current);
    setUndoable({ id, count });
    timer.current = setTimeout(() => setUndoable(null), UNDO_MS);
  };

  const request = (snapshot: NodeListResponse, selected: ReadonlySet<string>) => {
    const plan = planRemoveFromSnapshot(snapshot, selected);
    if (plan.steps.length === 0) {
      setMessage({ kind: 'error', text: t('nodes.delete.nothing') });
      return;
    }
    setMessage(null);
    setPending({ plan, text: removeConfirmText(plan) });
  };

  const confirm = () => {
    const current = pending;
    setPending(null);
    if (!current) return;
    setBusy(true);
    takeoverApi
      .deleteEntries(current.plan.steps.map((s) => s.targetId))
      .then((r) => {
        setMessage({ kind: 'ok', text: t('nodes.delete.done', { n: r.removed.length }) });
        offerUndo(r.undo_id, r.removed.length);
      })
      .catch((err: unknown) => setMessage({ kind: 'error', text: describeError(err) }))
      .finally(() => {
        setBusy(false);
        onDone();
      });
  };

  const undo = () => {
    const current = undoable;
    if (!current) return;
    if (timer.current) clearTimeout(timer.current);
    setUndoable(null);
    setBusy(true);
    takeoverApi
      .undoDelete(current.id)
      .then((r) => setMessage(r.errors.length === 0
        ? { kind: 'ok', text: t('nodes.delete.undone', { n: r.restored.length }) }
        : { kind: 'error', text: [t('nodes.delete.undoFailed'), ...r.errors.map((e) => `${e.id}: ${e.message}`)].join('\n') }))
      .catch((err: unknown) => setMessage({ kind: 'error', text: `${t('nodes.delete.undoFailed')}\n${describeError(err)}` }))
      .finally(() => {
        setBusy(false);
        onDone();
      });
  };

  return {
    pending, request, confirm, cancel: () => setPending(null), undo,
    undoable: undoable ? { count: undoable.count } : null, busy, message,
  };
}
