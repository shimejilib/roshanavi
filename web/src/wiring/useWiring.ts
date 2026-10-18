// Applies a wire to the node's own config (PUT of its spec) and restarts the node so the change
// is live. The function / class runner has no way to change its subscriptions while it runs
// (no control channel), so a rewire is a restart of ~1-2 s; we say so in a short notice.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, describeError } from '../api/client';
import type { ClassSpec } from '../api/classTypes';
import type { FunctionSpec } from '../api/functionTypes';
import type { TransformSpec } from '../api/transformTypes';
import type { DummySpec, Target } from '../api/types';
import { t } from '../i18n';
import type { WirePlan, WireSpec } from './edit';
import type { NodePorts } from './ports';

const NOTICE_MS = 7000;

export interface WireNotice {
  ok: boolean;
  text: string;
}

async function save(np: NodePorts, spec: WireSpec): Promise<unknown> {
  switch (np.owner) {
    case 'function':
      return api.updateFunction(spec as FunctionSpec);
    case 'class':
      return api.updateClass(spec as ClassSpec);
    case 'transform':
      return api.updateTransform(spec as TransformSpec);
    default:
      return api.updateDummy(spec as DummySpec);
  }
}

export type ApplyResult = 'applied' | 'unchanged' | 'failed';

export interface Wiring {
  busy: boolean;
  notice: WireNotice | null;
  /** Shows a refusal (or any message) without changing anything. */
  tell: (notice: WireNotice) => void;
  clear: () => void;
  /** Saves the plan's spec and restarts the node. */
  apply: (np: NodePorts, target: Target | undefined, plan: WirePlan, done: string) => Promise<ApplyResult>;
  /** The live targets with the specs just saved (the live data catches up about a second later;
   *  the next wire must start from what was saved, not from the stale spec). */
  targets: readonly Target[];
}

/** A spec just saved, and the live spec it replaced (as JSON). */
export interface Saved {
  spec: WireSpec;
  before: string;
}

/** Pure: `targets` with the `saved` specs, until the live spec moves on from `before`. */
export function withSaved(targets: readonly Target[], saved: Readonly<Record<string, Saved>>): Target[] {
  return targets.map((tg) => {
    const entry = saved[tg.id];
    return entry && JSON.stringify(tg.spec) === entry.before ? { ...tg, spec: entry.spec } : tg;
  });
}

export function useWiring(liveTargets: readonly Target[]): Wiring {
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<Record<string, Saved>>({});
  const [notice, setNotice] = useState<WireNotice | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const tell = useCallback((next: WireNotice) => {
    setNotice(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setNotice(null), NOTICE_MS);
  }, []);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const apply = useCallback(async (np: NodePorts, target: Target | undefined, plan: WirePlan, done: string): Promise<ApplyResult> => {
    if (!plan.ok) {
      tell({ ok: false, text: plan.reason });
      return 'failed';
    }
    if (!target) return 'failed';
    if (plan.unchanged) return 'unchanged';
    setBusy(true);
    try {
      await save(np, plan.spec);
      setSaved((prev) => ({ ...prev, [target.id]: { spec: plan.spec, before: JSON.stringify(liveTargets.find((tg) => tg.id === target.id)?.spec ?? null) } }));
      const restart = target.status === 'running' || target.status === 'starting';
      if (restart) await api.targetAction(target.id, 'restart');
      const parts = [done, plan.note, restart ? t(np.owner === 'class' ? 'wiring.restartedClass' : 'wiring.restarted', { name: np.name }) : t('wiring.savedStopped')];
      tell({ ok: true, text: parts.filter(Boolean).join(' ') });
      return 'applied';
    } catch (err) {
      tell({ ok: false, text: describeError(err) });
      return 'failed';
    } finally {
      setBusy(false);
    }
  }, [tell, liveTargets]);

  const targets = useMemo(() => withSaved(liveTargets, saved), [liveTargets, saved]);
  // Forget saved specs the live data already shows.
  useEffect(() => {
    const stale = Object.keys(saved).filter((id) => {
      const live = liveTargets.find((tg) => tg.id === id);
      return !live || JSON.stringify(live.spec) !== saved[id]?.before;
    });
    if (stale.length) setSaved((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => !stale.includes(id))));
  }, [liveTargets, saved]);

  return { busy, notice, tell, clear: () => setNotice(null), apply, targets };
}
