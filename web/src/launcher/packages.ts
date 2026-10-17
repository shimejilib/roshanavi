// Package picker logic (pure): search + ordering (workspace packages first).

import type { WorkspacePackage } from '../api/types';

export interface PackageMatch {
  pkg: WorkspacePackage;
  executables: string[];
  launchFiles: string[];
}

/** Demo / sample packages listed even when ROS standard packages are hidden. */
export const DEMO_PACKAGES: ReadonlySet<string> = new Set(['demo_nodes_cpp', 'demo_nodes_py', 'roshanavi_examples']);
/** The tool itself lives in the workspace but is not the user's own package. */
const SELF_PACKAGE = 'roshanavi';

function rank(pkg: WorkspacePackage): number {
  if (pkg.origin === 'workspace') return 0;
  return DEMO_PACKAGES.has(pkg.name) ? 1 : 2;
}

/** Default list: workspace + demo packages; `showSystem` adds every ROS standard package. */
export function visiblePackages(packages: WorkspacePackage[], showSystem: boolean): WorkspacePackage[] {
  return showSystem ? packages : packages.filter((p) => p.origin === 'workspace' || DEMO_PACKAGES.has(p.name));
}

/** True when the workspace holds at least one package of the user's own (not just roshanavi). */
export function workspaceConfigured(packages: WorkspacePackage[]): boolean {
  return packages.some((p) => p.origin === 'workspace' && p.name !== SELF_PACKAGE);
}

/** Packages whose name, executables or launch files contain `query` (case-insensitive). */
export function filterPackages(packages: WorkspacePackage[], query: string): PackageMatch[] {
  const q = query.trim().toLowerCase();
  const matches: PackageMatch[] = [];
  for (const pkg of packages) {
    const nameHit = !q || pkg.name.toLowerCase().includes(q);
    const executables = nameHit ? pkg.executables : pkg.executables.filter((e) => e.toLowerCase().includes(q));
    const launchFiles = nameHit ? pkg.launch_files : pkg.launch_files.filter((f) => f.toLowerCase().includes(q));
    if (nameHit || executables.length || launchFiles.length) matches.push({ pkg, executables, launchFiles });
  }
  return matches.sort((a, b) => rank(a.pkg) - rank(b.pkg) || a.pkg.name.localeCompare(b.pkg.name));
}

/** Workspace packages that have a source directory (can be built). */
export function buildablePackages(packages: WorkspacePackage[]): WorkspacePackage[] {
  return packages.filter((p) => p.origin === 'workspace' && p.source_dir);
}
