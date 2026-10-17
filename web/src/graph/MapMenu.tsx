// Right-click menu on the map (nodes by role, topics, edges, blank area; docs/design/ui.md).
// Start / stop / restart keep their confirmation flow (useNodeControl); disabled
// items show why in a tooltip and a visible hint.

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { describeError } from '../api/client';
import { t } from '../i18n';
import { useLive } from '../state/LiveProvider';
import { NodeControlFeedback } from './NodeControlButtons';
import { menuItems, menuTitle, type MenuAction, type MenuItem, type MenuTarget } from './menuModel';
import { useMenuActions, type MapCommands } from './useMenuActions';
import { useNodeControl } from './useNodeControl';

export interface MenuAnchor {
  x: number;
  y: number;
  target: MenuTarget;
}

interface MapMenuProps {
  anchor: MenuAnchor;
  buildable: ReadonlySet<string>;
  commands: MapCommands;
  onClose: () => void;
}

const CONTROL: ReadonlySet<MenuAction> = new Set(['start', 'stop', 'restart']);

/** Arrow keys move between items, Escape / Tab closes (WAI-ARIA menu pattern). */
function onMenuKey(e: KeyboardEvent<HTMLDivElement>, close: () => void): void {
  const items = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('button:not([disabled])')];
  const index = items.indexOf(document.activeElement as HTMLButtonElement);
  if (e.key === 'Escape' || e.key === 'Tab') {
    e.preventDefault();
    close();
  } else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && items.length > 0) {
    e.preventDefault();
    const step = e.key === 'ArrowDown' ? 1 : -1;
    items[(index + step + items.length) % items.length]?.focus();
  }
}

function MenuButton({ entry, onRun }: { entry: MenuItem; onRun: (action: MenuAction) => void }) {
  return (
    <button
      type="button"
      role="menuitem"
      className={entry.danger && entry.enabled ? 'danger' : undefined}
      disabled={!entry.enabled}
      title={entry.reason}
      onClick={() => onRun(entry.action)}
      data-testid={`menu-${entry.action}`}
    >
      {entry.label}
      {!entry.enabled && entry.reason && <span className="menu-reason muted small">{entry.reason}</span>}
    </button>
  );
}

export function MapMenu({ anchor, buildable, commands, onClose }: MapMenuProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const { live } = useLive();
  const { target } = anchor;
  const node = target.kind === 'node' ? live.graph?.nodes.find((n) => n.id === target.nodeId) : undefined;
  const control = useNodeControl(node, onClose);
  const run = useMenuActions(target, commands);
  const [error, setError] = useState<string | null>(null);
  const topic = target.kind === 'topic' ? target.topic : '';
  const items = useMemo(
    () => menuItems(target, {
      node,
      targets: live.targets,
      jobs: live.jobs,
      buildable,
      traffic: topic ? live.traffic.get(topic) : undefined,
      topicTypes: topic ? live.graph?.topics.find((tp) => tp.name === topic)?.types : undefined,
    }),
    [target, node, live.targets, live.jobs, buildable, live.traffic, live.graph, topic],
  );

  useEffect(() => {
    (ref.current?.querySelector<HTMLButtonElement>('button:not([disabled])') ?? ref.current)?.focus();
  }, []);
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (!control.pending && ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [onClose, control.pending]);

  const onRun = (action: MenuAction) => {
    if (CONTROL.has(action)) {
      control.request(action as 'start' | 'stop' | 'restart');
      return;
    }
    setError(null);
    run(action)
      .then(onClose)
      .catch((err: unknown) => setError(describeError(err)));
  };

  return (
    <>
      <div
        ref={ref}
        className="node-menu"
        role="menu"
        tabIndex={-1}
        aria-label={t('control.menuLabel', { node: menuTitle(target) })}
        style={{ left: anchor.x, top: anchor.y }}
        onKeyDown={(e) => onMenuKey(e, onClose)}
        data-testid="map-menu"
        data-kind={target.kind}
      >
        <div className="node-menu-title mono">{menuTitle(target)}</div>
        {items.map((entry) => (
          <MenuButton key={entry.action} entry={entry} onRun={onRun} />
        ))}
        {error && <p className="error-box small" role="alert">{error}</p>}
      </div>
      <NodeControlFeedback state={{ ...control, message: control.message?.kind === 'error' ? control.message : null }} />
    </>
  );
}
