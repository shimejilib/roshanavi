import { useMemo, useState } from 'react';
import type { WorkspacePackage } from '../api/types';
import { t } from '../i18n';
import { filterPackages, type PackageMatch } from './packages';

export interface Pick {
  pkg: WorkspacePackage;
  kind: 'run' | 'launch';
  file: string;
}

interface Props {
  packages: WorkspacePackage[];
  onPick: (pick: Pick) => void;
  onBuild: (pkg: string) => void;
  onRefresh: () => void;
  buildBusy: boolean;
}

const AUTO_EXPAND = 6;

function Badges({ pkg }: { pkg: WorkspacePackage }) {
  return (
    <>
      <span className={`badge origin-${pkg.origin}`}>{t(`launcher.origin.${pkg.origin}`)}</span>
      {!pkg.built && <span className="badge warn-text">{t('launcher.notBuilt')}</span>}
      {pkg.built && pkg.origin === 'workspace' && !pkg.sourced && (
        <span className="badge warn-text" title={t('launcher.notSourcedHelp')}>{t('launcher.notSourced')}</span>
      )}
    </>
  );
}

function PackageItems({ match, onPick }: { match: PackageMatch; onPick: Props['onPick'] }) {
  const { pkg } = match;
  return (
    <div className="pkg-items">
      {match.executables.length > 0 && <div className="muted small">{t('launcher.executables')}</div>}
      {match.executables.map((exe) => (
        <button key={exe} type="button" className="pick mono" onClick={() => onPick({ pkg, kind: 'run', file: exe })} data-testid={`pick-run-${pkg.name}-${exe}`}>
          ▶ {exe}
        </button>
      ))}
      {match.launchFiles.length > 0 && <div className="muted small">{t('launcher.launchFiles')}</div>}
      {match.launchFiles.map((file) => (
        <button key={file} type="button" className="pick mono" onClick={() => onPick({ pkg, kind: 'launch', file })} data-testid={`pick-launch-${pkg.name}-${file}`}>
          ⧉ {file}
        </button>
      ))}
    </div>
  );
}

export function PackagePicker({ packages, onPick, onBuild, onRefresh, buildBusy }: Props) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<Set<string>>(new Set());
  const matches = useMemo(() => filterPackages(packages, query), [packages, query]);
  const autoOpen = query.trim() !== '' && matches.length <= AUTO_EXPAND;
  const toggle = (name: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  return (
    <aside className="pkg-picker" aria-label={t('launcher.packages', { n: matches.length })}>
      <div className="pkg-toolbar">
        <input type="search" placeholder={t('launcher.search')} value={query} onChange={(e) => setQuery(e.target.value)} data-testid="launcher-search" />
        <button type="button" onClick={onRefresh} title={t('launcher.refresh')}>⟳</button>
      </div>
      <div className="muted small">{t('launcher.packages', { n: matches.length })}</div>
      {matches.length === 0 && <p className="muted">{t('launcher.noPackages')}</p>}
      <ul className="pkg-list">
        {matches.map((match) => {
          const { pkg } = match;
          const expanded = autoOpen || open.has(pkg.name);
          return (
            <li key={pkg.name} className={`pkg origin-${pkg.origin}`} data-testid={`pkg-${pkg.name}`}>
              <div className="pkg-head">
                <button type="button" className="pkg-name mono" aria-expanded={expanded} onClick={() => toggle(pkg.name)}>
                  {expanded ? '▾' : '▸'} {pkg.name}
                </button>
                <Badges pkg={pkg} />
                {pkg.origin === 'workspace' && pkg.source_dir && (
                  <button type="button" className="small" disabled={buildBusy} onClick={() => onBuild(pkg.name)} data-testid={`build-${pkg.name}`}>
                    {t('launcher.build')}
                  </button>
                )}
              </div>
              {expanded && <PackageItems match={match} onPick={onPick} />}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
