// Cytoscape stylesheet + colour palette (light / dark).

import type { StylesheetJson } from 'cytoscape';
import type { EdgeState } from './model';

export interface Palette {
  text: string;
  textMuted: string;
  labelBg: string;
  topicFill: string;
  topicBorder: string;
  edge: string;
  stale: string;
  drops: string;
  qosBad: string;
  focus: string;
  warn: string;
  roles: Record<'mine' | 'dependency' | 'dummy' | 'other', string>;
}

export const LIGHT: Palette = {
  text: '#1f2937',
  textMuted: '#6b7280',
  labelBg: '#ffffff',
  topicFill: '#eef2ff',
  topicBorder: '#6366f1',
  edge: '#3b82f6',
  stale: '#9ca3af',
  drops: '#f97316',
  qosBad: '#dc2626',
  focus: '#0ea5e9',
  warn: '#d97706',
  roles: { mine: '#16a34a', dependency: '#0891b2', dummy: '#c026d3', other: '#64748b' },
};

export const DARK: Palette = {
  text: '#e5e7eb',
  textMuted: '#9ca3af',
  labelBg: '#111827',
  topicFill: '#1e1b4b',
  topicBorder: '#818cf8',
  edge: '#60a5fa',
  stale: '#6b7280',
  drops: '#fb923c',
  qosBad: '#f87171',
  focus: '#38bdf8',
  warn: '#fbbf24',
  roles: { mine: '#22c55e', dependency: '#22d3ee', dummy: '#e879f9', other: '#94a3b8' },
};

export function prefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches === true;
}

/** Colour of an edge / particle for a given state. */
export function stateColor(p: Palette, state: EdgeState, qosBad: boolean): string {
  if (qosBad) return p.qosBad;
  switch (state) {
    case 'drops':
      return p.drops;
    case 'stale':
    case 'not_monitored':
    case 'idle':
      return p.stale;
    default:
      return p.edge;
  }
}

function roleRules(p: Palette): StylesheetJson {
  return (Object.keys(p.roles) as (keyof Palette['roles'])[]).map((role) => ({
    selector: `node[role = "${role}"]`,
    style: { 'background-color': p.roles[role], 'border-color': p.roles[role] },
  }));
}

export function stylesheet(p: Palette): StylesheetJson {
  return [
    {
      selector: 'node',
      style: {
        label: 'data(label)',
        color: p.text,
        'font-size': 11,
        'min-zoomed-font-size': 7,
        'text-wrap': 'wrap',
        'text-max-width': '160px',
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-background-color': p.labelBg,
        'text-background-opacity': 0.75,
        'text-background-padding': '1px',
        'border-width': 'data(border)',
        'border-opacity': 0.9,
        'transition-property': 'opacity, border-width',
        'transition-duration': 300,
      },
    },
    {
      selector: 'node[kind = "node"]',
      style: { shape: 'round-rectangle', width: 34, height: 22, 'background-opacity': 0.85, 'border-color': '#000' },
    },
    ...roleRules(p),
    {
      selector: 'node[kind = "topic"]',
      style: {
        shape: 'ellipse',
        width: 22,
        height: 22,
        'background-color': p.topicFill,
        'border-color': p.topicBorder,
        'border-width': 'data(border)',
      },
    },
    { selector: 'node[kind = "topic"][state = "stale"]', style: { 'border-style': 'dashed', 'border-color': p.stale } },
    { selector: 'node[kind = "topic"][state = "not_monitored"]', style: { 'border-style': 'dotted', 'border-color': p.stale } },
    { selector: 'node[?warn]', style: { 'underlay-color': p.warn, 'underlay-opacity': 0.35, 'underlay-padding': 5 } },
    {
      selector: 'edge',
      style: {
        width: 'data(width)',
        'curve-style': 'straight',
        'line-color': p.edge,
        'target-arrow-color': p.edge,
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        label: 'data(label)',
        'font-size': 9,
        'min-zoomed-font-size': 9,
        color: p.textMuted,
        'text-rotation': 'autorotate',
        'text-background-color': p.labelBg,
        'text-background-opacity': 0.75,
        'text-background-padding': '1px',
        opacity: 0.8,
        'transition-property': 'line-color, width, opacity',
        'transition-duration': 300,
      },
    },
    { selector: 'edge[state = "stale"], edge[state = "idle"]', style: { 'line-style': 'dashed', 'line-color': p.stale, 'target-arrow-color': p.stale } },
    { selector: 'edge[state = "not_monitored"]', style: { 'line-style': 'dotted', 'line-color': p.stale, 'target-arrow-color': p.stale } },
    { selector: 'edge[state = "drops"]', style: { 'line-color': p.drops, 'target-arrow-color': p.drops } },
    {
      selector: 'edge[?qosBad]',
      style: { 'line-style': 'dashed', 'line-color': p.qosBad, 'target-arrow-color': p.qosBad, 'target-arrow-shape': 'tee', opacity: 1 },
    },
    { selector: 'edge.flash', style: { 'line-color': p.focus, 'target-arrow-color': p.focus, opacity: 1, 'transition-duration': 0 } },
    { selector: '.faded', style: { opacity: 0.12 } },
    { selector: 'node.focused', style: { 'overlay-color': p.focus, 'overlay-opacity': 0.25, 'overlay-padding': 6 } },
    { selector: 'node:selected', style: { 'overlay-color': p.focus, 'overlay-opacity': 0.3, 'overlay-padding': 6 } },
  ];
}
