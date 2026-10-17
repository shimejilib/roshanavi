// Right-click menu on a map node: start / stop / restart for nodes roshanavi owns.

import { useEffect, useRef, type KeyboardEvent } from 'react';
import type { GraphNode } from '../api/types';
import { t } from '../i18n';
import { NodeControlButtons, NodeControlFeedback } from './NodeControlButtons';
import { useNodeControl } from './useNodeControl';

export interface MenuAnchor {
  x: number;
  y: number;
  nodeId: string;
}

interface NodeMenuProps {
  anchor: MenuAnchor;
  node: GraphNode | undefined;
  onClose: () => void;
}

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

export function NodeMenu({ anchor, node, onClose }: NodeMenuProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const state = useNodeControl(node, onClose);
  useEffect(() => {
    (ref.current?.querySelector<HTMLButtonElement>('button:not([disabled])') ?? ref.current)?.focus();
  }, []);
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (!state.pending && ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [onClose, state.pending]);
  return (
    <>
      <div
        ref={ref}
        className="node-menu"
        role="menu"
        tabIndex={-1}
        aria-label={t('control.menuLabel', { node: anchor.nodeId })}
        style={{ left: anchor.x, top: anchor.y }}
        onKeyDown={(e) => onMenuKey(e, onClose)}
        data-testid="node-menu"
      >
        <div className="node-menu-title mono">{anchor.nodeId}</div>
        <NodeControlButtons node={node} state={state} asMenu />
      </div>
      <NodeControlFeedback state={{ ...state, message: state.message?.kind === 'error' ? state.message : null }} />
    </>
  );
}
