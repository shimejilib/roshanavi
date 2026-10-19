// つなぎ口 (ports) drawn over the cytoscape map as real buttons (focusable, labelled for screen
// readers), the wire being dragged, and the wiring dialogs (docs/design/wiring.md).
// Positions follow the map imperatively on every cytoscape render (no React render per frame).

import type { Core, EventObject } from 'cytoscape';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { api, describeError } from '../api/client';
import type { GraphTopic, Target } from '../api/types';
import { kindLabel, type KindCatalog } from '../datakind/kinds';
import { nodeElementId, portFraction, topicElementId } from '../graph/model';
import { t } from '../i18n';
import { useLatestMessages } from '../transform/useLatestMessages';
import { planDisconnect } from './edit';
import { dropOutcome, hitAt, notesOf, refusalOf, type DragSource, type DropContext, type DropOutcome } from './drop';
import { allInputs, allOutputs, findPort, portLabel, type NodePorts, type Port } from './ports';
import { timingText } from './timing';
import type { Wiring } from './useWiring';
import { WireDialog } from './WireDialog';
import { NewChannelPrompt, WireToolbar, type SelectedWire } from './WireBits';

const CLICK_SLOP = 4;
const REFOCUS_MS = 15_000;

interface Props {
  cy: Core;
  nodes: readonly NodePorts[];
  targets: readonly Target[];
  topics: readonly GraphTopic[];
  catalog: KindCatalog;
  wiring: Wiring;
  selected: SelectedWire | null;
  onCloseSelected: () => void;
}

interface Slot {
  elementId: string;
  side: 'in' | 'out';
  index: number;
  count: number;
}

interface Drag {
  source: DragSource;
  x0: number;
  y0: number;
  x: number;
  y: number;
  moved: boolean;
  outcome: DropOutcome;
}

/** 「入力口 text (文字列)」 */
export function portTitle(p: Port): string {
  const kind = p.kind ? kindLabel(p.kind) : p.type ? t('kind.special', { type: p.type }) : '';
  return t(p.ref.side === 'in' ? 'wiring.port.inTitle' : 'wiring.port.outTitle', { name: p.label, kind });
}

/** Screen-reader label: what the port is, what it is wired to, how to wire it. */
export function portAria(np: NodePorts, p: Port): string {
  const where = p.topic ? t('wiring.port.wiredTo', { topic: p.topic }) : t('wiring.port.unwired');
  const method = p.method ? t('wiring.port.ofMethod', { method: p.method }) : '';
  return `${np.name} ${method}${portTitle(p)}、${where}。${t('wiring.port.keys')}`;
}

function slotsOf(nodes: readonly NodePorts[]): Map<string, Slot> {
  const slots = new Map<string, Slot>();
  for (const np of nodes) {
    const elementId = nodeElementId(np.nodeId);
    const ins = allInputs(np);
    const outs = allOutputs(np);
    ins.forEach((p, index) => slots.set(p.key, { elementId, side: 'in', index, count: ins.length }));
    outs.forEach((p, index) => slots.set(p.key, { elementId, side: 'out', index, count: outs.length }));
  }
  return slots;
}

function zoomClass(zoom: number): string {
  if (zoom < 0.55) return 'tiny';
  return zoom < 0.7 ? 'small' : 'full';
}

/** Moves the port buttons / action buttons / channel handle to where cytoscape drew things. */
function place(cy: Core, layer: HTMLElement, slots: ReadonlyMap<string, Slot>, handleTopic: string | null): void {
  layer.dataset.zoom = zoomClass(cy.zoom());
  layer.style.setProperty('--wire-zoom', cy.zoom().toFixed(3)); // labels scale with the boxes
  layer.querySelectorAll<HTMLElement>('[data-port]').forEach((el) => {
    const slot = slots.get(el.dataset.port ?? '');
    const node = slot ? cy.getElementById(slot.elementId) : null;
    if (!slot || !node || node.empty()) {
      el.style.display = 'none';
      return;
    }
    const pos = node.renderedPosition();
    const x = pos.x + (slot.side === 'in' ? -1 : 1) * node.renderedOuterWidth() / 2;
    const y = pos.y + portFraction(slot.index, slot.count) * node.renderedOuterHeight();
    el.style.display = '';
    el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    el.classList.toggle('faded', node.hasClass('faded'));
  });
  layer.querySelectorAll<HTMLElement>('[data-actions]').forEach((el) => {
    const node = cy.getElementById(el.dataset.actions ?? '');
    if (node.empty()) {
      el.style.display = 'none';
      return;
    }
    const pos = node.renderedPosition();
    el.style.display = '';
    el.style.transform = `translate(${pos.x.toFixed(1)}px, ${(pos.y - node.renderedOuterHeight() / 2).toFixed(1)}px)`;
  });
  const handle = layer.querySelector<HTMLElement>('[data-handle]');
  if (handle) {
    const node = handleTopic ? cy.getElementById(topicElementId(handleTopic)) : null;
    if (!node || node.empty()) {
      handle.style.display = 'none';
    } else {
      const pos = node.renderedPosition();
      handle.style.display = 'flex';
      handle.style.transform = `translate(${(pos.x + node.renderedOuterWidth() / 2 + 6).toFixed(1)}px, ${pos.y.toFixed(1)}px)`;
    }
  }
}

function centerOf(el: Element, container: HTMLElement): { x: number; y: number } {
  const r = el.getBoundingClientRect();
  const c = container.getBoundingClientRect();
  return { x: r.left + r.width / 2 - c.left, y: r.top + r.height / 2 - c.top };
}

export function PortOverlay({ cy, nodes, targets, topics, catalog, wiring, selected, onCloseSelected }: Props) {
  const layerRef = useRef<HTMLDivElement | null>(null);
  const slots = useMemo(() => slotsOf(nodes), [nodes]);
  const [handleTopic, setHandleTopic] = useState<string | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [dialogPort, setDialogPort] = useState<string | null>(null);
  const [ask, setAsk] = useState<{ port: string; suggestion: string; x: number; y: number } | null>(null);
  const [hoverPort, setHoverPort] = useState<string | null>(null);
  // Keyboard users keep their place: the port gets the focus back, also after the node restarted
  // (its ports disappear from the map for a moment while it restarts).
  const refocus = useRef<{ key: string; until: number } | null>(null);
  const ctx: DropContext = useMemo(() => ({ nodes, targets, topics, catalog }), [nodes, targets, topics, catalog]);
  const container = cy.container() as HTMLElement;
  const placeRef = useRef(() => undefined as void);
  placeRef.current = () => {
    const layer = layerRef.current;
    if (!layer) return;
    place(cy, layer, slots, handleTopic);
    const want = refocus.current;
    if (!want) return;
    if (Date.now() > want.until) {
      refocus.current = null;
      return;
    }
    const el = layer.querySelector<HTMLElement>(`[data-port="${CSS.escape(want.key)}"]`);
    // Only when the focus was lost (the old button went away), never away from something else.
    const lost = !document.activeElement || document.activeElement === document.body;
    if (el && el.style.display !== 'none' && lost && !document.querySelector('[role="dialog"][aria-modal="true"]')) {
      el.focus();
    }
  };
  const keepFocus = (key: string) => {
    refocus.current = { key, until: Date.now() + REFOCUS_MS };
    requestAnimationFrame(() => placeRef.current());
  };

  // Follow the map: one placement per animation frame, whatever cytoscape redrew.
  useEffect(() => {
    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        placeRef.current();
      });
    };
    cy.on('render', schedule);
    return () => {
      cy.off('render', schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [cy]);
  useLayoutEffect(() => placeRef.current());

  // The channel handle appears while the pointer is over a channel (topic) of the map.
  useEffect(() => {
    let hide: ReturnType<typeof setTimeout> | null = null;
    const over = (evt: EventObject) => {
      if (hide) clearTimeout(hide);
      setHandleTopic(String(evt.target.data('ref')));
    };
    const out = () => {
      hide = setTimeout(() => setHandleTopic((cur) => (layerRef.current?.querySelector('[data-handle]:hover') ? cur : null)), 400);
    };
    cy.on('mouseover', 'node[kind = "topic"]', over);
    cy.on('mouseout', 'node[kind = "topic"]', out);
    return () => {
      cy.off('mouseover', 'node[kind = "topic"]', over);
      cy.off('mouseout', 'node[kind = "topic"]', out);
      if (hide) clearTimeout(hide);
    };
  }, [cy]);

  const run = async (outcome: DropOutcome, x: number, y: number) => {
    if (outcome.kind === 'none') return;
    if (outcome.kind === 'ask') {
      setAsk({ port: outcome.port, suggestion: outcome.suggestion, x, y });
      return;
    }
    const refusal = refusalOf(outcome);
    if (refusal) {
      wiring.tell({ ok: false, text: refusal });
      return;
    }
    if (outcome.kind !== 'steps') return;
    for (const step of outcome.steps) {
      const done = t(step.port.ref.side === 'out' ? 'wiring.doneOut' : 'wiring.done', { topic: step.topic, name: step.node.name, port: step.port.label });
      if ((await wiring.apply(step.node, step.target, step.plan, done)) === 'failed') return;
    }
  };

  // ---- dragging ---------------------------------------------------------------------------------
  const local = (e: { clientX: number; clientY: number }) => {
    const c = container.getBoundingClientRect();
    return { x: e.clientX - c.left, y: e.clientY - c.top };
  };
  const hitFor = (e: { clientX: number; clientY: number }, source: DragSource) => {
    const { x, y } = local(e);
    const under = document.elementsFromPoint(e.clientX, e.clientY)
      .map((el) => (el as HTMLElement).dataset?.port)
      .find((key) => key && !(source.kind === 'port' && key === source.key)) ?? null;
    return dropOutcome(ctx, source, hitAt(cy, x, y, under));
  };

  const startDrag = (e: ReactPointerEvent<HTMLElement>, source: DragSource) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    const start = centerOf(e.currentTarget, container);
    setHoverPort(null);
    setDrag({ source, x0: start.x, y0: start.y, ...local(e), moved: false, outcome: { kind: 'none' } });
  };
  const moveDrag = (e: ReactPointerEvent<HTMLElement>) => {
    if (!drag) return;
    const p = local(e);
    const moved = drag.moved || Math.hypot(p.x - drag.x0, p.y - drag.y0) > CLICK_SLOP * 2;
    setDrag({ ...drag, ...p, moved, outcome: moved ? hitFor(e, drag.source) : drag.outcome });
  };
  const endDrag = (e: ReactPointerEvent<HTMLElement>) => {
    if (!drag) return;
    const current = drag;
    setDrag(null);
    setHoverPort(null);
    if (!current.moved) {
      if (current.source.kind === 'port') setDialogPort(current.source.key); // a click = the keyboard path
      return;
    }
    const p = local(e);
    void run(hitFor(e, current.source), p.x, p.y);
  };

  // Esc while dragging: drop nothing.
  const dragging = drag !== null;
  useEffect(() => {
    if (!dragging) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDrag(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dragging]);

  const disconnect = (key: string) => {
    const found = findPort(nodes, key);
    const target = found && targets.find((tg) => tg.id === found.node.targetId);
    if (!found || !target) return;
    const plan = planDisconnect(found.node, found.port, target, catalog);
    void wiring.apply(found.node, target, plan, t('wiring.unwired', { name: found.node.name, port: found.port.label }));
  };

  const onPortKey = (e: React.KeyboardEvent, key: string) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setDialogPort(key);
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault();
      keepFocus(key);
      disconnect(key);
    } else if (e.key === 'Tab' || e.key === 'Escape') {
      refocus.current = null; // the user moves on
    }
  };

  const hovered = hoverPort ? findPort(nodes, hoverPort) : null;
  const dragHint = drag?.moved ? (refusalOf(drag.outcome) || notesOf(drag.outcome) || hintOf(drag.outcome)) : '';
  const dragBad = drag?.moved ? Boolean(refusalOf(drag.outcome)) : false;
  const dialog = dialogPort ? findPort(nodes, dialogPort) : null;
  const askFound = ask ? findPort(nodes, ask.port) : null;

  return (
    <div ref={layerRef} className="wire-layer" data-testid="wire-layer" data-dragging={drag ? 'true' : undefined}>
      {nodes.map((np) => (
        <div key={np.targetId} className="wire-node" role="group" aria-label={t('wiring.node.aria', { name: np.name })} data-testid={`wire-node-${np.targetId}`}>
          {[...allInputs(np), ...allOutputs(np)].map((p) => (
            <button key={p.key} type="button" data-port={p.key} data-testid={`port-${np.name}-${p.ref.side}-${p.ref.group}-${p.ref.index}`}
              data-topic={p.topic} className={`wire-port ${p.ref.side} ${p.topic ? 'wired' : 'open'}`}
              aria-label={portAria(np, p)} aria-haspopup="dialog"
              onPointerDown={(e) => startDrag(e, { kind: 'port', key: p.key })} onPointerMove={moveDrag} onPointerUp={endDrag}
              onPointerCancel={() => setDrag(null)} onKeyDown={(e) => onPortKey(e, p.key)}
              onMouseEnter={() => setHoverPort(p.key)} onMouseLeave={() => setHoverPort((k) => (k === p.key ? null : k))}
              onFocus={() => setHoverPort(p.key)} onBlur={() => setHoverPort((k) => (k === p.key ? null : k))}>
              <span className="wire-dot" aria-hidden="true" />
              <span className="wire-label" aria-hidden="true">{portLabel(p)}</span>
            </button>
          ))}
        </div>
      ))}
      {nodes.filter((np) => np.actions.length > 0).map((np) => (
        <div key={`a:${np.targetId}`} className="wire-actions" data-actions={nodeElementId(np.nodeId)}>
          {np.actions.map((method) => (
            <ActionButton key={method} np={np} method={method} wiring={wiring} />
          ))}
        </div>
      ))}
      <button type="button" tabIndex={-1} className="wire-handle" data-handle="true" aria-hidden="true" title={t('wiring.handle')}
        data-testid="wire-handle" onMouseLeave={() => setHandleTopic(null)}
        onPointerDown={(e) => handleTopic && startDrag(e, { kind: 'topic', topic: handleTopic })} onPointerMove={moveDrag} onPointerUp={endDrag}
        onPointerCancel={() => setDrag(null)}>
        <span aria-hidden="true">＋</span>
      </button>
      {drag?.moved && (
        <svg className="wire-drag" aria-hidden="true">
          <line x1={drag.x0} y1={drag.y0} x2={drag.x} y2={drag.y} className={dragBad ? 'bad' : 'ok'} />
        </svg>
      )}
      {drag?.moved && dragHint && (
        <div className={`wire-hint ${dragBad ? 'bad' : 'ok'}`} style={{ left: drag.x + 14, top: drag.y - 40 }} role="status" data-testid="wire-hint">
          {dragBad ? '✕ ' : '✓ '}{dragHint}
        </div>
      )}
      {hovered && !drag && <PortTip np={hovered.node} port={hovered.port} />}
      {wiring.notice && (
        <div className={`wire-notice ${wiring.notice.ok ? 'ok-box' : 'error-box'}`} role={wiring.notice.ok ? 'status' : 'alert'} data-testid="wire-notice">
          {wiring.notice.text}
          <button type="button" className="small" onClick={wiring.clear} aria-label={t('common.close')}>×</button>
        </div>
      )}
      {wiring.busy && <div className="wire-busy muted small" role="status">{t('wiring.busy')}</div>}
      {selected && (
        <WireToolbar selected={selected} nodes={nodes} onClose={onCloseSelected}
          onDisconnect={(key) => { onCloseSelected(); disconnect(key); }}
          onRewire={(key) => { onCloseSelected(); setDialogPort(key); }} />
      )}
      {ask && askFound && (
        <NewChannelPrompt x={ask.x} y={ask.y} suggestion={ask.suggestion} onCancel={() => setAsk(null)}
          onCreate={(name) => {
            setAsk(null);
            void run(dropOutcome(ctx, { kind: 'port', key: ask.port }, { kind: 'topic', topic: name }), ask.x, ask.y);
          }} />
      )}
      {dialog && (
        <WireDialog np={dialog.node} port={dialog.port} target={targets.find((tg) => tg.id === dialog.node.targetId)} topics={topics} catalog={catalog}
          onClose={() => {
            const key = dialogPort;
            setDialogPort(null);
            if (key) keepFocus(key);
          }}
          onChoose={(choice) => {
            if (choice.kind === 'disconnect') disconnect(dialog.port.key);
            else void run(dropOutcome(ctx, { kind: 'port', key: dialog.port.key }, { kind: 'topic', topic: choice.topic }), 0, 0);
          }} />
      )}
    </div>
  );
}

function hintOf(outcome: DropOutcome): string {
  if (outcome.kind === 'ask') return t('wiring.hint.newChannel');
  if (outcome.kind === 'steps') return t('wiring.hint.connect');
  return '';
}

function PortTip({ np, port }: { np: NodePorts; port: Port }) {
  const group = np.groups.find((g) => g.inputs.includes(port) || g.outputs.includes(port));
  const latest = useLatestMessages(port.ref.side === 'out' && port.topic ? [port.topic] : []);
  const value = port.topic ? latest[port.topic] : undefined;
  // A one-field message (文字列・数値 …) shows just its value.
  const shown = value && Object.keys(value).length === 1 && 'data' in value ? value.data : value;
  return (
    <div className="wire-tip" role="tooltip" data-testid="wire-tip">
      <strong>{portTitle(port)}</strong>
      {port.method && <div className="muted small">{t('wiring.port.ofMethod', { method: port.method })}</div>}
      <div>{port.topic ? t('wiring.port.wiredTo', { topic: port.topic }) : t('wiring.port.unwired')}</div>
      {group && <div>{t('wiring.tip.timing')}: {timingText(group.timing)}</div>}
      {port.ref.side === 'out' && port.topic && (
        <div className="mono small" data-testid="wire-tip-value">{t('wiring.tip.latest')}: {shown !== undefined ? JSON.stringify(shown).slice(0, 120) : t('wiring.tip.noValue')}</div>
      )}
      <div className="muted small">{t('wiring.tip.how')}</div>
    </div>
  );
}

function ActionButton({ np, method, wiring }: { np: NodePorts; method: string; wiring: Wiring }) {
  const [busy, setBusy] = useState(false);
  const call = async () => {
    setBusy(true);
    try {
      await api.callClassMethod(np.targetId, method);
      wiring.tell({ ok: true, text: t('wiring.action.called', { name: np.name, method }) });
    } catch (err) {
      wiring.tell({ ok: false, text: describeError(err) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <button type="button" className="wire-action small" disabled={busy || !np.running} onClick={() => void call()}
      aria-label={t('wiring.action.aria', { name: np.name, method })} title={np.running ? undefined : t('wiring.action.stopped')}>
      ▶ {method}
    </button>
  );
}
