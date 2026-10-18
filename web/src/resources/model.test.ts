import { describe, expect, it } from 'vitest';
import type { Breakdown, NodeBadge, ProcInfo, ResourceSnapshot } from '../api/resourceTypes';
import type { Diagnostic } from '../api/types';
import { diagnosticTargets, diagnosticText } from '../graph/diagnosticsText';
import { buildElements, type NodeData } from '../graph/model';
import { applyLive, EMPTY_LIVE } from '../state/live';
import { chatterGraph } from '../test/fixtures';
import {
  badgeLabel,
  connRemote,
  connWho,
  cpuSegments,
  formatCpu,
  groupProcesses,
  formatGrowthDuration,
  formatGrowthRate,
  growthText,
  leakStatusText,
  ioValues,
  loadLevel,
  memSegments,
  processWho,
  sparkValues,
} from './model';
import { isSnapshot } from './useResourceStream';

const badge = (over: Partial<NodeBadge> = {}): NodeBadge => ({
  cpu_pct: 12.3,
  cpu_norm_pct: 0.5,
  rss: 45_000_000,
  confidence: 'exact',
  shared: [],
  scope: 'process',
  pid: 42,
  leak: null,
  ...over,
});

function proc(over: Partial<ProcInfo>): ProcInfo {
  return {
    pid: 1, ppid: 0, name: 'p', exe: 'p', group: 'other', label: 'p', role: null, target_id: null, nodes: [],
    cpu_pct: 0, cpu_norm_pct: 0, rss: 0, uss: null, threads: null, fds: null, read_bps: null, write_bps: null,
    ...over,
  };
}

describe('load and formatting', () => {
  it('colours CPU of one process at 40 % and 80 % of a core', () => {
    expect(loadLevel(null)).toBe('none');
    expect(loadLevel(39.9)).toBe('low');
    expect(loadLevel(40)).toBe('mid');
    expect(loadLevel(93)).toBe('high');
    expect(formatCpu(null)).toBe('—');
    expect(formatCpu(3.456)).toBe('3.5%');
    expect(formatCpu(150.4)).toBe('150%');
  });

  it('writes the map badge and marks estimated mappings', () => {
    expect(badgeLabel(undefined)).toBe('');
    expect(badgeLabel(badge())).toBe('CPU 12% · 45.0 MB');
    expect(badgeLabel(badge({ confidence: 'heuristic' }))).toBe('CPU 12% · 45.0 MB (推定)');
  });

  it('explains the memory growth state', () => {
    expect(growthText(null)).toBe('—');
    expect(growthText({ slope_mb_per_min: null, suspect: false, span_sec: 0, warming_up: true })).toContain('起動直後');
    expect(growthText({ slope_mb_per_min: null, suspect: false, span_sec: 42.4, warming_up: false })).toContain('42 秒');
    expect(growthText({ slope_mb_per_min: 1.234, suspect: true, span_sec: 200, warming_up: false })).toBe('+1.23 MB/分');
  });

  it('names who owns a process or a connection', () => {
    expect(processWho(proc({ nodes: ['/a', '/b'] }))).toBe('/a, /b');
    expect(processWho(proc({ group: 'self', label: 'probe' }))).toBe('計測ノード');
    expect(processWho(proc({ group: 'self', label: 'unknown_label' }))).toBe('roshanavi の補助プロセス');
    expect(connWho({ pid: 7, proto: 'tcp', laddr: '', raddr: '', rhost: null, status: '', local: false, group: 'self', label: 'server' })).toBe('サーバー本体');
    expect(connRemote({ rhost: 'api.example.com', raddr: '93.184.216.34:443', local: false })).toBe('api.example.com (93.184.216.34:443)');
    expect(connRemote({ rhost: 'localhost', raddr: '127.0.0.1:8080', local: true })).toBe('127.0.0.1:8080 · この PC 内');
  });

  it('turns history series into sparkline values', () => {
    expect(sparkValues([null, 2_097_152], 1_048_576)).toEqual([0, 2]);
    expect(ioValues([1, null], [2, 3])).toEqual([3, 3]);
    expect(sparkValues(undefined)).toEqual([]);
  });
});

describe('grouping and breakdown', () => {
  const snap: ResourceSnapshot = {
    available: true,
    processes: [
      proc({ pid: 3, group: 'self', label: 'server', cpu_pct: 5 }),
      proc({ pid: 2, group: 'ros', label: 'tk', cpu_pct: 1 }),
      proc({ pid: 4, group: 'ros', label: 'cam', cpu_pct: 90 }),
      proc({ pid: 5, group: 'self', label: 'probe', cpu_pct: 1 }),
    ],
    others: [proc({ pid: 9, cpu_pct: 1 }), proc({ pid: 8, cpu_pct: 50 })],
  };

  it('groups ROS nodes and roshanavi itself by label, others by CPU', () => {
    const g = groupProcesses(snap);
    expect(g.ros.map((p) => p.pid)).toEqual([4, 2]);
    expect(g.self.map((p) => p.pid)).toEqual([5, 3]);
    expect(g.other.map((p) => p.pid)).toEqual([8, 9]);
  });

  it('builds share bars of the whole PC that never exceed 100 %', () => {
    const b: Breakdown = {
      cpu: { ros: 10, self: 2, other: 30, total: 42, other_top: [] },
      mem: { ros: 1000, self: 500, other: 2500, total: 4000, other_top: [] },
      counts: { ros: 1, self: 1, other: 1 },
    };
    expect(cpuSegments(b).map((s) => [s.key, s.pct])).toEqual([['ros', 10], ['self', 2], ['other', 30], ['idle', 58]]);
    expect(memSegments(b, 10_000).map((s) => s.pct)).toEqual([10, 5, 25, 60]);
    const over = { ...b, cpu: { ...b.cpu, other: 120 } };
    expect(cpuSegments(over).find((s) => s.key === 'idle')?.pct).toBe(0);
    expect(cpuSegments(undefined)).toEqual([]);
  });

  it('accepts only snapshot-shaped frames', () => {
    expect(isSnapshot({ available: false, reason: 'off' })).toBe(true);
    expect(isSnapshot({ traffic: [] })).toBe(false);
    expect(isSnapshot(null)).toBe(false);
  });
});

describe('map badges', () => {
  it('adds CPU / memory to node labels with a load level and a leak flag', () => {
    const els = buildElements(chatterGraph(), new Map(), 0, {
      '/talker': badge({ cpu_pct: 93 }),
      '/listener': badge({ cpu_pct: 1, confidence: 'heuristic', leak: { slope_mb_per_min: 3, suspect: true, span_sec: 200, warming_up: false } }),
    });
    const nodes = els.filter((e) => e.group === 'nodes' && (e.data as NodeData).kind === 'node').map((e) => e.data as NodeData);
    const talker = nodes.find((n) => n.ref === '/talker');
    const listener = nodes.find((n) => n.ref === '/listener');
    expect(talker?.label).toBe('/talker\nCPU 93% · 45.0 MB');
    expect(talker?.load).toBe('high');
    expect(listener?.label).toContain('(推定)');
    expect(listener?.load).toBe('low');
    expect(listener?.leak).toBe(true);
    const plain = buildElements(chatterGraph(), new Map(), 0);
    expect((plain.find((e) => (e.data as NodeData).ref === '/talker')?.data as NodeData).load).toBe('none');
  });

  it('keeps the last resources when a live frame has none', () => {
    const resources = { available: true, nodes: { '/talker': badge() }, diagnostics: [] };
    const first = applyLive(EMPTY_LIVE, { traffic: [], jobs: [], resources }, 1);
    expect(applyLive(first, { traffic: [], jobs: [] }, 2).resources).toBe(resources);
  });
});

describe('leak wording', () => {
  const state = { slope_mb_per_min: 0.3, span_sec: 7200, warming_up: false, suspect: false };

  it('writes rate and duration with two significant digits', () => {
    expect(formatGrowthRate(0.3)).toBe('0.30');
    expect(formatGrowthRate(3.04)).toBe('3.0');
    expect(formatGrowthRate(12.7)).toBe('13');
    expect(formatGrowthDuration(30)).toBe('1 分');
    expect(formatGrowthDuration(45 * 60)).toBe('45 分');
    expect(formatGrowthDuration(2 * 3600)).toBe('2 時間');
    expect(formatGrowthDuration(2.5 * 3600)).toBe('2.5 時間');
  });

  it('tells a suspicion (rate, duration, no slowing) from a quiet watching note', () => {
    expect(leakStatusText(null)).toBeNull();
    expect(leakStatusText(state)).toBeNull();
    expect(leakStatusText({ ...state, suspect: true, rate_mb_per_min: 0.3, duration_sec: 7200 })).toEqual({
      kind: 'suspect',
      text: '毎分 0.30 MB で 2 時間増え続けています (減速なし)。リークの疑い',
    });
    expect(leakStatusText({ ...state, watch: true })?.kind).toBe('watch');
    expect(leakStatusText({ ...state, watch: true })?.text).toContain('様子見');
  });
});

describe('resource diagnostics', () => {
  const base = { severity: 'warning' as const, topic: '', nodes: [] as string[] };

  it('renders leak / disk / UDP warnings in plain Japanese', () => {
    const leak: Diagnostic = { ...base, code: 'mem_leak', nodes: ['/detector'], detail: { rate_mb_per_min: 0.3, duration_sec: 7200 } };
    expect(diagnosticText(leak)).toBe('/detector のメモリが毎分 0.30 MB で 2 時間増え続けています (減速なし)。メモリリークの疑いがあります');
    const procLeak: Diagnostic = { ...base, code: 'gpu_mem_leak', detail: { name: 'trainer', rate_mb_per_min: 10, duration_sec: 1200 } };
    expect(diagnosticText(procLeak)).toContain('trainer の GPU メモリが毎分 10 MB で 20 分増え続けています');
    const own: Diagnostic = { ...base, code: 'mem_leak', detail: { group: 'self', label: 'server', rate_mb_per_min: 1.5, duration_sec: 3600 } };
    expect(diagnosticText(own)).toContain('roshanavi 自身 (サーバー本体) のメモリが毎分 1.5 MB で 60 分増え続けています');
    const disk: Diagnostic = { ...base, code: 'disk_low', detail: { path: '/data', free: 900_000_000, free_pct: 3.1, level: 'warn', recording: true } };
    expect(diagnosticText(disk)).toBe('データフォルダ (/data) のディスクの空きが少なくなっています (残り 900 MB、3.1%)。録画中です。さらに減ると録画は自動で止まります');
    const full: Diagnostic = { ...base, severity: 'error', code: 'disk_low', detail: { path: '/data', free: 100_000_000, free_pct: 0.5, level: 'stop' } };
    expect(diagnosticText(full)).toContain('録画は開始できず');
    const udp: Diagnostic = { ...base, code: 'udp_rcvbuf', topic: '/camera/image', detail: { rcvbuf_recent: 42 } };
    expect(diagnosticText(udp)).toContain('net.core.rmem_max');
    expect(diagnosticText(udp)).toContain('/camera/image');
  });

  it('focuses the node of a leak and the topic of a UDP warning', () => {
    expect(diagnosticTargets({ ...base, code: 'mem_leak', nodes: ['/d'], detail: {} })).toEqual({ topics: [], nodes: ['/d'] });
    expect(diagnosticTargets({ ...base, code: 'udp_rcvbuf', topic: '/img', detail: {} }).topics).toEqual(['/img']);
  });
});
