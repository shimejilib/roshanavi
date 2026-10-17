// Live communication map: cytoscape + dagre (left -> right) + particle overlay.
//
// Elements are patched incrementally (add / remove / data update) on each
// 1 s frame. The dagre layout only runs when the topology changes, animated,
// so unchanged graphs never jump.

import cytoscape, { type CollectionReturnValue, type Core, type EventObject, type NodeSingular } from 'cytoscape';
import dagre from 'cytoscape-dagre';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { TrafficEntry } from '../api/types';
import type { MenuAnchor } from './MapMenu';
import type { MenuTarget } from './menuModel';
import { diffElements, indexElements } from './diff';
import { focusSet } from './focus';
import { topicElementId, type EdgeData, type Element } from './model';
import { LOW_RATE_HZ } from './particles';
import { loadPins, NO_PINS, savePins, withPin, type Pins } from './pins';
import { stylesheet, type Palette } from './style';
import { useParticles } from './useParticles';

cytoscape.use(dagre);

const FLASH_MS = 350;
const LAYOUT_MS = 450;
const MAX_FIT_ZOOM = 1.3; // small graphs should not be blown up to fill the screen

export interface GraphViewProps {
  elements: Element[];
  traffic: Map<string, TrafficEntry>;
  tick: number;
  palette: Palette;
  paused: boolean;
  active: boolean;
  selectedId: string | null;
  onSelect: (elementId: string | null) => void;
  fitSignal: number;
  /** Increment to re-run the layout from scratch ("整列し直す"). */
  layoutSignal: number;
  /** Open project (null while unknown): pinned positions are saved under it. */
  projectKey: string | null;
  /** Right-click menu (nodes, topics, edges, blank area). */
  renderMenu?: (anchor: MenuAnchor, close: () => void) => ReactNode;
}

interface Tooltip {
  x: number;
  y: number;
  text: string;
}

function capZoom(cy: Core): void {
  if (cy.zoom() > MAX_FIT_ZOOM) {
    cy.zoom(MAX_FIT_ZOOM);
    cy.center();
  }
}

/** Automatic layout; dragged ("pinned") vertices keep their position. */
function runLayout(cy: Core, animate: boolean, pins: Pins): void {
  const layout = cy.layout({
    name: 'dagre',
    rankDir: 'LR',
    nodeSep: 18,
    rankSep: 90,
    edgeSep: 8,
    animate,
    animationDuration: LAYOUT_MS,
    fit: !animate,
    padding: 30,
    transform: (node: NodeSingular, pos: cytoscape.Position) => pins[node.id()] ?? pos,
  } as cytoscape.LayoutOptions);
  if (!animate) layout.one('layoutstop', () => capZoom(cy));
  layout.run();
}

function byIds(cy: Core, ids: readonly string[]): CollectionReturnValue {
  return ids.reduce((acc, id) => acc.union(cy.getElementById(id)), cy.collection());
}

function applyPatch(cy: Core, prev: Map<string, Element>, next: Element[], pins: Pins): boolean {
  const patch = diffElements(prev, next);
  cy.batch(() => {
    if (patch.removed.length) cy.remove(byIds(cy, patch.removed));
    for (const el of patch.updated) cy.getElementById(el.data.id).data(el.data);
    if (patch.added.length) {
      // Start new vertices next to an existing neighbour so the layout animation reads as "grow".
      const added = cy.add(patch.added.map((el) => ({ group: el.group, data: { ...el.data } })));
      added.nodes().forEach((n) => {
        const pin = pins[n.id()];
        if (pin) {
          n.position({ ...pin });
          return;
        }
        const neighbour = n.neighborhood('node').filter((m) => !added.contains(m)).first() as NodeSingular;
        if (neighbour.nonempty()) n.position({ ...neighbour.position() });
      });
    }
  });
  return patch.topologyChanged;
}

export function GraphView(props: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const indexRef = useRef<Map<string, Element>>(new Map());
  const onSelectRef = useRef(props.onSelect);
  onSelectRef.current = props.onSelect;
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);
  const [menu, setMenu] = useState<MenuAnchor | null>(null);
  const pinsRef = useRef<Pins>(NO_PINS);
  const pinsOwnerRef = useRef<string | null>(null); // project the pins in memory belong to (null: not known yet)
  const projectRef = useRef<string | null>(props.projectKey);
  projectRef.current = props.projectKey;

  const setPins = (next: Pins) => {
    pinsRef.current = next;
    if (projectRef.current !== null) savePins(projectRef.current, next);
  };

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const cy = cytoscape({
      container: containerRef.current,
      style: stylesheet(props.palette),
      wheelSensitivity: 0.3,
      minZoom: 0.1,
      maxZoom: 4,
      selectionType: 'single',
    });
    cy.on('tap', (evt: EventObject) => {
      if (evt.target === cy) onSelectRef.current(null);
      else if (evt.target.isNode()) onSelectRef.current(evt.target.id());
      else onSelectRef.current(topicElementId((evt.target.data() as EdgeData).topic)); // edge -> its topic
    });
    // A vertex the user moved stays where it was put until "整列し直す".
    cy.on('dragfree', 'node', (evt: EventObject) => {
      const node = evt.target as NodeSingular;
      setPins(withPin(pinsRef.current, node.id(), node.position()));
    });
    cy.on('mouseover', 'edge', (evt: EventObject) => {
      const data = evt.target.data() as EdgeData;
      const text = data.qosBad ? data.qosReason : `${data.topic}${data.label ? `\n${data.label}` : ''}${data.rateNote ? `\n${data.rateNote}` : ''}`;
      setTooltip({ x: evt.renderedPosition.x, y: evt.renderedPosition.y, text });
    });
    cy.on('mouseout', 'edge', () => setTooltip(null));
    // Right click (cxttap) only: left-click selection and drag-panning stay untouched.
    cy.on('cxttap', (evt: EventObject) => {
      const pos = evt.renderedPosition;
      setMenu({ x: pos.x, y: pos.y, target: menuTargetOf(evt, cy) });
    });
    cy.on('tap viewport', () => setMenu(null));
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
      indexRef.current = new Map();
    };
    // Created once; the palette is applied by the effect below.
  }, []);

  useEffect(() => {
    cyRef.current?.style(stylesheet(props.palette));
  }, [props.palette]);

  // The project is known only after a fetch (and changes on a switch): load its pins, move what is on the map.
  useEffect(() => {
    if (props.projectKey === null) return;
    const loaded = loadPins(props.projectKey);
    // Pins dragged before the project was known belong to it; after a switch the old project's pins do not.
    pinsRef.current = pinsOwnerRef.current === null ? { ...loaded, ...pinsRef.current } : loaded;
    pinsOwnerRef.current = props.projectKey;
    savePins(props.projectKey, pinsRef.current);
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      for (const [id, pos] of Object.entries(pinsRef.current)) {
        const node = cy.getElementById(id);
        if (node.nonempty()) node.position({ ...pos });
      }
    });
  }, [props.projectKey]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const first = indexRef.current.size === 0;
    const changed = applyPatch(cy, indexRef.current, props.elements, pinsRef.current);
    indexRef.current = indexElements(props.elements);
    if (changed && cy.nodes().length > 0) runLayout(cy, !first, pinsRef.current);
  }, [props.elements]);

  useEffect(() => {
    const cy = cyRef.current;
    if (props.active && cy) {
      cy.resize();
    }
  }, [props.active]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || props.layoutSignal === 0) return;
    setPins(NO_PINS); // 整列し直す: unpin everything, then lay out from scratch
    if (cy.nodes().length > 0) runLayout(cy, true, NO_PINS);
  }, [props.layoutSignal]);

  useEffect(() => {
    const cy = cyRef.current;
    if (cy && props.fitSignal > 0) {
      cy.fit(cy.elements(), 30);
      capZoom(cy);
    }
  }, [props.fitSignal]);

  const edges = useMemo(
    () => props.elements.filter((el): el is { group: 'edges'; data: EdgeData } => el.group === 'edges').map((el) => el.data),
    [props.elements],
  );
  const focusKey = useFocus(cyRef, edges, props.selectedId);
  const field = useParticles({ cyRef, canvasRef, edges, palette: props.palette, paused: props.paused, active: props.active, focusKey });
  useLowRateFlashes(cyRef, edges, props.traffic, props.tick, props.paused, field.pulse.bind(field));

  return (
    <div className="graph-canvas-wrap">
      <div ref={containerRef} className="graph-canvas" data-testid="graph-canvas" onContextMenu={(e) => e.preventDefault()} />
      <canvas ref={canvasRef} className="graph-particles" aria-hidden="true" />
      <MapOutline elements={props.elements} />
      {menu && props.renderMenu?.(menu, () => setMenu(null))}
      {tooltip && (
        <div className="graph-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y + 12 }}>
          {tooltip.text}
        </div>
      )}
    </div>
  );
}

function menuTargetOf(evt: EventObject, cy: Core): MenuTarget {
  if (evt.target === cy) return { kind: 'blank' };
  if (evt.target.isEdge()) {
    const data = evt.target.data() as EdgeData;
    return { kind: 'edge', topic: data.topic, node: data.node, dir: data.dir };
  }
  const ref = String(evt.target.data('ref'));
  return evt.target.data('kind') === 'topic' ? { kind: 'topic', topic: ref } : { kind: 'node', nodeId: ref };
}

/** Text outline of the map for screen readers (and E2E tests); the canvas itself is opaque. */
function MapOutline({ elements }: { elements: Element[] }) {
  return (
    <ul className="visually-hidden" aria-label="map" data-testid="graph-outline">
      {elements.map((el) => (
        <li key={el.data.id} data-id={el.data.id} data-role={el.group === 'nodes' ? el.data.role : undefined}>
          {el.group === 'nodes' ? el.data.label : `${el.data.source} → ${el.data.target} ${el.data.label}`}
        </li>
      ))}
    </ul>
  );
}

/** Fade everything outside the selected element's upstream/downstream paths. */
function useFocus(cyRef: React.RefObject<Core | null>, edges: readonly EdgeData[], selectedId: string | null): string {
  const key = selectedId ?? '';
  const edgeKey = edges.map((e) => e.id).join('|');
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass('faded focused');
      if (!selectedId || cy.getElementById(selectedId).empty()) return;
      const keep = focusSet(selectedId, edges);
      cy.elements().forEach((el) => {
        if (!keep.has(el.id())) el.addClass('faded');
      });
      cy.getElementById(selectedId).addClass('focused');
    });
    // edgeKey captures topology changes without re-running on every data tick.
  }, [cyRef, selectedId, edgeKey]);
  return `${key}#${edgeKey.length}`;
}

/** Topics at <= 1 Hz flash their edges (and emit one particle) when a message arrives. */
function useLowRateFlashes(
  cyRef: React.RefObject<Core | null>,
  edges: readonly EdgeData[],
  traffic: Map<string, TrafficEntry>,
  tick: number,
  paused: boolean,
  pulse: (edgeId: string) => void,
): void {
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || paused) return undefined;
    const ids = edges
      .filter((e) => {
        const entry = traffic.get(e.topic);
        return !e.qosBad && entry !== undefined && entry.hz <= LOW_RATE_HZ && entry.recent_count > 0;
      })
      .map((e) => e.id);
    if (ids.length === 0) return undefined;
    ids.forEach(pulse);
    const flashed = byIds(cy, ids);
    flashed.addClass('flash');
    const timer = setTimeout(() => flashed.removeClass('flash'), FLASH_MS);
    return () => clearTimeout(timer);
    // Runs once per live tick by design.
  }, [tick]);
}
