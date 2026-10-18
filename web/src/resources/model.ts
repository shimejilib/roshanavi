// Resource monitoring view model (pure, unit-tested): load colours, badge text, grouping.

import type { Breakdown, ConnInfo, LeakState, NodeBadge, ProcGroup, ProcInfo, ResourceSnapshot } from '../api/resourceTypes';
import { t, tDynamic } from '../i18n';
import { formatBytes } from '../lib/format';

export type LoadLevel = 'none' | 'low' | 'mid' | 'high';

/** CPU of one process, 100 = one core (like `top`). */
export const LOAD_MID_PCT = 40;
export const LOAD_HIGH_PCT = 80;

export function loadLevel(cpuPct: number | null | undefined): LoadLevel {
  if (cpuPct == null || !Number.isFinite(cpuPct)) return 'none';
  if (cpuPct >= LOAD_HIGH_PCT) return 'high';
  if (cpuPct >= LOAD_MID_PCT) return 'mid';
  return 'low';
}

export function formatCpu(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return '—';
  if (pct >= 10) return `${pct.toFixed(0)}%`;
  return `${pct.toFixed(1)}%`;
}

export function formatMem(bytes: number | null | undefined): string {
  return bytes == null ? '—' : formatBytes(bytes);
}

/** Second label line on the map: `CPU 12% · 45 MB (推定)`. */
export function badgeLabel(badge: NodeBadge | undefined): string {
  if (!badge) return '';
  const text = t('res.badge', { cpu: formatCpu(badge.cpu_pct), mem: formatMem(badge.rss) });
  return badge.confidence === 'exact' ? text : `${text} (${t('res.estimated')})`;
}

export function selfLabel(label: string): string {
  return tDynamic(`res.self.${label}`, 'res.self.helper');
}

/** Short "who" text of a process: its nodes, else its role label, else its name. */
export function processWho(p: Pick<ProcInfo, 'nodes' | 'group' | 'label' | 'name'>): string {
  if (p.nodes && p.nodes.length > 0) return p.nodes.join(', ');
  if (p.group === 'self') return selfLabel(p.label);
  return p.label || p.name;
}

export function connWho(c: ConnInfo): string {
  if (c.nodes && c.nodes.length > 0) return c.nodes.join(', ');
  if (c.group === 'self' && c.label) return selfLabel(c.label);
  return c.label || c.name || String(c.pid);
}

export function connRemote(c: Pick<ConnInfo, 'rhost' | 'raddr' | 'local'>): string {
  const base = c.rhost && c.rhost !== 'localhost' ? `${c.rhost} (${c.raddr})` : c.raddr;
  return c.local ? `${base} · ${t('res.conn.local')}` : base;
}

export function growthText(leak: LeakState | null | undefined): string {
  if (!leak) return '—';
  if (leak.warming_up) return t('res.growthWarming');
  if (leak.slope_mb_per_min == null) return t('res.growthMeasuring', { sec: Math.round(leak.span_sec) });
  const v = leak.slope_mb_per_min;
  return t('res.growthValue', { v: `${v >= 0 ? '+' : ''}${v.toFixed(2)}` });
}

/** `3 MB/min` -> `3.0`, `0.3` -> `0.30`, `12.7` -> `13`: two significant digits. */
export function formatGrowthRate(mbPerMin: number): string {
  const v = Math.abs(mbPerMin);
  return v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2);
}

/** `45 分`, `2 時間`, `2.5 時間` (the growth lasted at least this long). */
export function formatGrowthDuration(sec: number): string {
  const min = Math.max(1, Math.round(sec / 60));
  if (min < 90) return t('res.duration.min', { n: min });
  const hours = Math.round((min / 60) * 2) / 2;
  return t('res.duration.hour', { n: Number.isInteger(hours) ? hours : hours.toFixed(1) });
}

/** One line for the leak verdict: the suspicion with rate and duration, the quiet "watching"
 *  note, or null. */
export function leakStatusText(leak: LeakState | null | undefined): { kind: 'suspect' | 'watch'; text: string } | null {
  if (!leak) return null;
  if (leak.suspect) {
    return {
      kind: 'suspect',
      text: t('res.leak.suspect', {
        rate: formatGrowthRate(leak.rate_mb_per_min ?? leak.slope_mb_per_min ?? 0),
        duration: formatGrowthDuration(leak.duration_sec ?? leak.span_sec),
      }),
    };
  }
  return leak.watch ? { kind: 'watch', text: t('res.leak.watch') } : null;
}

export interface ProcessGroups {
  ros: ProcInfo[];
  self: ProcInfo[];
  other: ProcInfo[];
}

function byCpu(a: ProcInfo, b: ProcInfo): number {
  return (b.cpu_pct ?? 0) - (a.cpu_pct ?? 0) || a.pid - b.pid;
}

/** ROS nodes grouped by launcher target / node, roshanavi itself by role, others by CPU. */
export function groupProcesses(snap: ResourceSnapshot): ProcessGroups {
  const procs = snap.processes ?? [];
  const pick = (g: ProcGroup) => procs.filter((p) => p.group === g);
  const ros = pick('ros').sort((a, b) => a.label.localeCompare(b.label) || byCpu(a, b));
  const self = pick('self').sort((a, b) => a.label.localeCompare(b.label) || byCpu(a, b));
  return { ros, self, other: [...(snap.others ?? [])].sort(byCpu) };
}

export interface ShareSegment {
  key: 'ros' | 'self' | 'other' | 'idle';
  pct: number;
}

/** Stacked bar of the whole PC (percent of all cores): ROS / roshanavi / other / idle. */
export function cpuSegments(b: Breakdown | undefined): ShareSegment[] {
  if (!b) return [];
  const clamp = (v: number) => Math.max(0, Math.min(100, v));
  const ros = clamp(b.cpu.ros);
  const self = clamp(b.cpu.self);
  const other = clamp(b.cpu.other ?? 0);
  const used = Math.min(100, ros + self + other);
  return [
    { key: 'ros', pct: ros },
    { key: 'self', pct: self },
    { key: 'other', pct: other },
    { key: 'idle', pct: Math.max(0, 100 - used) },
  ];
}

export function memSegments(b: Breakdown | undefined, totalBytes: number | undefined): ShareSegment[] {
  if (!b || !totalBytes) return [];
  const pct = (v: number | null) => Math.max(0, Math.min(100, ((v ?? 0) / totalBytes) * 100));
  const ros = pct(b.mem.ros);
  const self = pct(b.mem.self);
  const other = pct(b.mem.other);
  return [
    { key: 'ros', pct: ros },
    { key: 'self', pct: self },
    { key: 'other', pct: other },
    { key: 'idle', pct: Math.max(0, 100 - ros - self - other) },
  ];
}

/** Sparkline input: nulls (not measured yet) become 0. */
export function sparkValues(series: readonly (number | null)[] | undefined, scale = 1): number[] {
  return (series ?? []).map((v) => (v == null ? 0 : v / scale));
}

/** Read + write bytes per second per point. */
export function ioValues(read: readonly (number | null)[] | undefined, write: readonly (number | null)[] | undefined): number[] {
  const r = read ?? [];
  const w = write ?? [];
  return r.map((v, i) => (v ?? 0) + (w[i] ?? 0));
}
