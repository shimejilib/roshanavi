import { describe, expect, it } from 'vitest';
import type { MessageKey } from '../i18n';
import { ja } from '../i18n/messages';
import { OPS, STEP_KINDS } from './editSteps';

// Keys built at runtime (tDynamic) must exist, or the UI shows a fallback label.
describe('scenario messages', () => {
  it('has a label for every status, step kind, op, field reason and recorded operation', () => {
    const keys = [
      ...['pending', 'running', 'passed', 'failed', 'error', 'skipped', 'cancelled'].flatMap((s) => [`scn.status.${s}`, `scn.result.${s}`]),
      ...STEP_KINDS.map((k) => `scn.kind.${k}`),
      ...OPS.map((op) => `scn.op.${op}`),
      ...['volatile', 'changes', 'big', 'element'].map((r) => `scn.pick.reason.${r}`),
      ...['once', 'periodic', 'stream', 'media', 'bag'].map((m) => `scn.rec.mode.${m}`),
      ...['target_start', 'target_stop', 'target_restart'].map((o) => `scn.rec.op.${o}`),
      ...['always', 'never', 'rate', 'throughput', 'latency'].map((k) => `scn.rec.rangeKind.${k}`),
      ...['topic', 'input', 'output', 'within', 'count', 'for', 'min_count', 'min_hz', 'max_hz', 'min_ratio', 'p50_ms', 'p95_ms', 'max_ms',
        'node', 'cpu_max', 'mem_max_mb', 'max_mb_per_min']
        .map((f) => `scn.field.${f}`),
    ];
    for (const key of keys) expect(ja[key as MessageKey], key).toBeTruthy();
  });
});
