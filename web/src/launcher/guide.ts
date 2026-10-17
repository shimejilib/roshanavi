// First-run guide of the Launcher (pure, DESIGN §6.5).

import type { Target, TargetSpec, WorkspacePackage } from '../api/types';
import { makeTargetId } from './form';

export const TRY_PACKAGE = 'demo_nodes_cpp';
export const TRY_EXECUTABLE = 'talker';

/** The guide shows while the launch list has no run / launch target (input nodes do not count). */
export function needsGuide(targets: readonly Target[]): boolean {
  return !targets.some((tg) => tg.kind === 'run' || tg.kind === 'launch');
}

/** Whether the "try talker" button can work in this environment. */
export function canTryTalker(packages: readonly WorkspacePackage[]): boolean {
  return packages.some((p) => p.name === TRY_PACKAGE && p.executables.includes(TRY_EXECUTABLE));
}

/** Spec for "試しに talker を起動してみる": a named talker marked as the user's own node. */
export function tryTalkerSpec(targets: readonly Target[]): TargetSpec {
  const id = makeTargetId(TRY_EXECUTABLE, targets.map((tg) => tg.id));
  return { id, kind: 'run', package: TRY_PACKAGE, executable: TRY_EXECUTABLE, name: id.replace(/-/g, '_'), role: 'mine', autostart: false, auto_restart: false };
}
