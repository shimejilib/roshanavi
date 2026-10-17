// Start / stop / restart buttons for a map node (right pane and context menu).

import type { GraphNode } from '../api/types';
import { t } from '../i18n';
import { ConfirmDialog } from '../lib/ConfirmDialog';
import { actionLabel, type ControlAction } from './nodeControl';
import type { NodeControlState } from './useNodeControl';

interface Props {
  node: GraphNode | undefined;
  state: NodeControlState;
  /** Menu mode: role="menuitem" buttons for the context menu. */
  asMenu?: boolean;
}

export function NodeControlButtons({ state, asMenu }: Props) {
  // `node` is part of Props for callers' readability; the state already holds it.
  const { control } = state;
  const role = asMenu ? 'menuitem' : undefined;
  if (control.kind === 'none') {
    return (
      <span title={control.reason} className="control-disabled">
        <button type="button" role={role} disabled aria-disabled="true" data-testid="node-stop" aria-describedby="control-reason">
          {t('control.stop')}
        </button>
        <span id="control-reason" className="muted small">{control.reason}</span>
      </span>
    );
  }
  return (
    <>
      {control.actions.map((action: ControlAction) => (
        <button
          key={action}
          type="button"
          role={role}
          className={action === 'stop' ? 'danger' : undefined}
          disabled={state.busy}
          onClick={() => state.request(action)}
          data-testid={`node-${action}`}
        >
          {actionLabel(action, control)}
        </button>
      ))}
    </>
  );
}

/** Confirm dialog + result message for a control state (render once per owner). */
export function NodeControlFeedback({ state }: { state: NodeControlState }) {
  return (
    <>
      {state.pending && (
        <ConfirmDialog
          title={t('control.confirmTitle')}
          text={state.pending.text}
          okLabel={state.pending.action === 'restart' ? t('control.confirmRestartOk') : t('control.confirmOk')}
          onOk={state.confirm}
          onCancel={state.cancel}
        />
      )}
      {state.message && (
        <p className={state.message.kind === 'ok' ? 'ok-box' : 'error-box'} role={state.message.kind === 'ok' ? 'status' : 'alert'}>
          {state.message.text}
        </p>
      )}
    </>
  );
}
