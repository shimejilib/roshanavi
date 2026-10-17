// Runs map-node actions (inject job stop / launcher target start-stop-restart) with confirmation.

import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { GraphNode } from '../api/types';
import { t } from '../i18n';
import { useLive } from '../state/LiveProvider';
import { actionLabel, confirmText, nodeControl, type ControlAction, type NodeControl } from './nodeControl';

export interface PendingConfirm {
  action: ControlAction;
  text: string;
}

export interface NodeControlState {
  control: NodeControl;
  request: (action: ControlAction) => void;
  pending: PendingConfirm | null;
  confirm: () => void;
  cancel: () => void;
  busy: boolean;
  message: { kind: 'ok' | 'error'; text: string } | null;
}

async function perform(control: NodeControl, action: ControlAction): Promise<void> {
  if (control.kind === 'job') await api.stopInject(control.jobId);
  else if (control.kind === 'target') await api.targetAction(control.target.id, action);
}

export function useNodeControl(node: GraphNode | undefined, onDone?: () => void): NodeControlState {
  const { live } = useLive();
  const control = nodeControl(node, live.targets);
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<NodeControlState['message']>(null);

  const execute = async (action: ControlAction) => {
    setBusy(true);
    setMessage(null);
    try {
      await perform(control, action);
      setMessage({ kind: 'ok', text: t('control.done', { action: actionLabel(action, control) }) });
      onDone?.();
    } catch (err) {
      setMessage({ kind: 'error', text: describeError(err) });
    } finally {
      setBusy(false);
    }
  };

  const request = (action: ControlAction) => {
    const text = node ? confirmText(action, control, node.id) : null;
    if (text) setPending({ action, text });
    else void execute(action);
  };
  const confirm = () => {
    const current = pending;
    setPending(null);
    if (current) void execute(current.action);
  };
  return { control, request, pending, confirm, cancel: () => setPending(null), busy, message };
}
