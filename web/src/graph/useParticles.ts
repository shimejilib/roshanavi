// Canvas overlay that draws flow particles on top of cytoscape.
//
// Why a canvas overlay instead of animating cytoscape styles (e.g.
// line-dash-offset): any style change makes cytoscape re-render the whole
// graph, so per-frame style updates on ~200 edges cost a full redraw at 60 fps.
// Here cytoscape only redraws when data changes (1 Hz) and the overlay draws a
// few hundred dots per frame with one canvas path per colour. Endpoint
// coordinates are cached and refreshed only when nodes move.

import type { Core } from 'cytoscape';
import { useEffect, useRef, type RefObject } from 'react';
import type { EdgeData } from './model';
import { ParticleField, type FlowEdge } from './particles';
import { stateColor, type Palette } from './style';

const RADIUS_PX = 2.6;

interface Segment {
  sx: number;
  sy: number;
  tx: number;
  ty: number;
  color: string;
}

export function isFlowing(e: EdgeData): boolean {
  return !e.qosBad && (e.state === 'active' || e.state === 'drops');
}

function computeSegments(cy: Core, palette: Palette): Map<string, Segment> {
  const segments = new Map<string, Segment>();
  cy.edges().forEach((edge) => {
    if (edge.hasClass('faded') || !edge.visible()) return;
    const s = edge.sourceEndpoint();
    const t = edge.targetEndpoint();
    const data = edge.data() as EdgeData;
    segments.set(edge.id(), { sx: s.x, sy: s.y, tx: t.x, ty: t.y, color: stateColor(palette, data.state, data.qosBad) });
  });
  return segments;
}

interface ParticleOptions {
  cyRef: RefObject<Core | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  edges: readonly EdgeData[];
  palette: Palette;
  paused: boolean;
  active: boolean;
  /** Bumped by the caller when focus classes change (segments must be refreshed). */
  focusKey: string;
}

export function useParticles(opts: ParticleOptions): ParticleField {
  const field = useRef(new ParticleField());
  const segments = useRef<Map<string, Segment>>(new Map());
  const dirty = useRef(true);
  const pausedRef = useRef(opts.paused);
  pausedRef.current = opts.paused;
  const paletteRef = useRef(opts.palette);
  paletteRef.current = opts.palette;

  useEffect(() => {
    const flow: FlowEdge[] = opts.edges.map((e) => ({ id: e.id, hz: e.hz, flowing: isFlowing(e) }));
    field.current.setEdges(flow);
    dirty.current = true;
  }, [opts.edges]);

  useEffect(() => {
    dirty.current = true;
  }, [opts.focusKey, opts.palette]);

  useEffect(() => {
    const cy = opts.cyRef.current;
    const canvas = opts.canvasRef.current;
    if (!cy || !canvas || !opts.active) return undefined;
    const markDirty = () => {
      dirty.current = true;
    };
    cy.on('position add remove', markDirty);
    const ctx = canvas.getContext('2d');
    let frame = 0;
    let last = performance.now();
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      if (!ctx || document.hidden) return;
      const dt = (now - last) / 1000;
      last = now;
      if (!pausedRef.current) field.current.step(dt);
      resizeCanvas(canvas);
      if (dirty.current) {
        segments.current = computeSegments(cy, paletteRef.current);
        dirty.current = false;
      }
      paint(ctx, canvas, cy, field.current, segments.current);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      cy.off('position add remove', markDirty);
    };
  }, [opts.cyRef, opts.canvasRef, opts.active]);

  return field.current;
}

function resizeCanvas(canvas: HTMLCanvasElement): void {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(canvas.clientWidth * dpr);
  const h = Math.round(canvas.clientHeight * dpr);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
}

function paint(
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  cy: Core,
  field: ParticleField,
  segments: Map<string, Segment>,
): void {
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const zoom = cy.zoom();
  const pan = cy.pan();
  ctx.setTransform(dpr * zoom, 0, 0, dpr * zoom, dpr * pan.x, dpr * pan.y);
  const radius = RADIUS_PX / Math.max(zoom, 0.35);
  const byColor = new Map<string, Path2D>();
  for (const p of field.particles()) {
    const seg = segments.get(p.edgeId);
    if (!seg) continue;
    const x = seg.sx + (seg.tx - seg.sx) * p.progress;
    const y = seg.sy + (seg.ty - seg.sy) * p.progress;
    let path = byColor.get(seg.color);
    if (!path) {
      path = new Path2D();
      byColor.set(seg.color, path);
    }
    path.moveTo(x + radius, y);
    path.arc(x, y, radius, 0, Math.PI * 2);
  }
  for (const [color, path] of byColor) {
    ctx.fillStyle = color;
    ctx.fill(path);
  }
}
