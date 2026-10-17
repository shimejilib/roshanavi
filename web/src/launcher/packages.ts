// Package picker logic (pure): search + ordering (workspace packages first).

import type { WorkspacePackage } from '../api/types';

export interface PackageMatch {
  pkg: WorkspacePackage;
  executables: string[];
  launchFiles: string[];
}

function rank(pkg: WorkspacePackage): number {
  return pkg.origin === 'workspace' ? 0 : 1;
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
