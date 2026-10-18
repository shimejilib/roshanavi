// The keyboard path of wiring (and what a click on a port opens): choose what to connect the port
// to from a list, then confirm. Incompatible channels are listed, disabled, with the reason.

import { useMemo, useRef, useState, useEffect } from 'react';
import type { GraphTopic, Target } from '../api/types';
import type { KindCatalog } from '../datakind/kinds';
import { t } from '../i18n';
import { termPair } from '../i18n/glossary';
import { flowStep, initialFlow, wireOptions, type FlowKey, type FlowState, type WireChoice } from './keyboard';
import { portTitle } from './PortOverlay';
import type { NodePorts, Port } from './ports';
import { timingText } from './timing';

const KEYS: readonly string[] = ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' ', 'Escape'];

interface Props {
  np: NodePorts;
  port: Port;
  target: Target | undefined;
  topics: readonly GraphTopic[];
  catalog: KindCatalog;
  onChoose: (choice: WireChoice) => void;
  onClose: () => void;
}

export function WireDialog({ np, port, target, topics, catalog, onChoose, onClose }: Props) {
  const options = useMemo(() => (target ? wireOptions(np, port, target, topics, catalog) : []), [np, port, target, topics, catalog]);
  const [state, setState] = useState<FlowState>(() => initialFlow(options));
  const listRef = useRef<HTMLUListElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const group = np.groups.find((g) => g.inputs.includes(port) || g.outputs.includes(port));

  useEffect(() => {
    if (state.step === 'choose') listRef.current?.focus();
    else confirmRef.current?.focus();
  }, [state.step]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${state.focus}"]`)?.scrollIntoView?.({ block: 'nearest' });
  }, [state.focus]);

  const dispatch = (event: Parameters<typeof flowStep>[1]) => {
    const next = flowStep(state, event, options);
    if (next === 'cancel') onClose();
    else if ('done' in next) {
      onClose();
      onChoose(next.done);
    } else setState(next);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (!KEYS.includes(e.key)) return;
    if (state.step === 'confirm' && e.target instanceof HTMLInputElement && e.key !== 'Enter' && e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    dispatch({ type: 'key', key: e.key as FlowKey });
  };
  const chosen = state.selected == null ? undefined : options[state.selected];
  const titleId = `wire-dialog-title-${port.key.replace(/[^A-Za-z0-9_-]/g, '_')}`;

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal wire-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} data-testid="wire-dialog"
        onMouseDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <div className="modal-head">
          <h3 id={titleId}>{t('wiring.dialog.title', { name: np.name, port: portTitle(port) })}</h3>
          <button type="button" className="modal-x" onClick={onClose} aria-label={t('common.close')}>×</button>
        </div>
        <div className="modal-body">
          <p className="muted small">{port.topic ? t('wiring.port.wiredTo', { topic: port.topic }) : t('wiring.port.unwired')}
            {group && <> — {timingText(group.timing)}</>}</p>
          {state.step === 'choose' ? (
            <>
              <p className="small" id={`${titleId}-help`}>{t('wiring.dialog.help', { channel: termPair('topic') })}</p>
              <ul ref={listRef} className="wire-options" role="listbox" tabIndex={0} aria-labelledby={titleId} aria-describedby={`${titleId}-help`}
                aria-activedescendant={`${titleId}-opt-${state.focus}`} data-testid="wire-options">
                {options.map((o, i) => (
                  <li key={o.id} id={`${titleId}-opt-${i}`} role="option" data-index={i} aria-selected={i === state.focus} aria-disabled={o.disabled}
                    className={`wire-option ${o.status} ${i === state.focus ? 'focused' : ''} ${o.disabled ? 'disabled' : ''}`}
                    data-testid={`wire-option-${o.id}`} onClick={() => dispatch({ type: 'pick', index: i })}>
                    <span className="wire-option-label">{o.status === 'refuse' && !o.current ? '✕ ' : o.status === 'convert' ? '↻ ' : ''}{o.label}</span>
                    {o.detail && <span className="wire-option-detail muted small">{o.detail}</span>}
                  </li>
                ))}
              </ul>
              <p className="muted small">{t('wiring.dialog.keys')}</p>
            </>
          ) : chosen && (
            <div className="wire-confirm" data-testid="wire-confirm">
              {chosen.choice.kind === 'new' ? (
                <label>
                  {t('wiring.dialog.newName', { channel: termPair('topic') })}
                  <input value={state.newName} onChange={(e) => dispatch({ type: 'rename', name: e.target.value })} data-testid="wire-new-name" spellCheck={false} />
                </label>
              ) : chosen.choice.kind === 'disconnect' ? (
                <p>{t('wiring.dialog.confirmDisconnect', { topic: port.topic })}</p>
              ) : (
                <p>{t('wiring.dialog.confirmConnect', { topic: chosen.label })}{chosen.detail && <> — {chosen.detail}</>}</p>
              )}
              <p className="muted small">{t(np.owner === 'class' ? 'wiring.dialog.restartClass' : 'wiring.dialog.restart')}</p>
              <div className="row end">
                <button type="button" onClick={() => dispatch({ type: 'key', key: 'Escape' })}>{t('wiring.dialog.back')}</button>
                <button ref={confirmRef} type="button" className="primary" onClick={() => dispatch({ type: 'key', key: 'Enter' })} data-testid="wire-confirm-ok">
                  {chosen.choice.kind === 'disconnect' ? t('wiring.dialog.doDisconnect') : t('wiring.dialog.doConnect')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
