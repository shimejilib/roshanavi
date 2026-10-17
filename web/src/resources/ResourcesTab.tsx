// リソース tab: PC overview, ROS / roshanavi / other breakdown, processes by role, connections.

import { useMemo } from 'react';
import { t, tDynamic } from '../i18n';
import { useAppState } from '../state/AppState';
import { ConnectionsView } from './ConnectionsView';
import { HostOverview } from './HostOverview';
import { formatCpu, groupProcesses } from './model';
import { BreakdownView, ProcessGroupTable } from './ProcessTable';
import { useResourceStream } from './useResourceStream';

export function ResourcesTab() {
  const { snapshot } = useResourceStream();
  const { select, setTab } = useAppState();
  const groups = useMemo(() => (snapshot ? groupProcesses(snapshot) : null), [snapshot]);
  const estimated = useMemo(
    () => new Set(Object.values(snapshot?.nodes ?? {}).filter((n) => n.confidence !== 'exact').map((n) => n.node)),
    [snapshot],
  );
  const openNode = (node: string) => {
    select({ kind: 'node', id: node });
    setTab('graph');
  };

  if (!snapshot || !snapshot.available || !snapshot.host || !groups) {
    const reason = snapshot?.reason ?? 'starting';
    return (
      <div className="resources-tab" data-testid="resources-tab">
        <h2>{t('res.title')}</h2>
        <p className="muted">{tDynamic(`res.unavailable.${reason}`, 'res.unavailable.unknown')}</p>
      </div>
    );
  }
  const sampler = snapshot.sampler;
  return (
    <div className="resources-tab" data-testid="resources-tab">
      <header className="res-head">
        <h2>{t('res.title')}</h2>
        <span className="badge" data-testid="res-this-pc">{t('res.updated')}</span>
        <span className="spacer" />
        {sampler && (
          <span className="muted small" data-testid="res-sampler">
            {t('res.sampler', { cpu: formatCpu(sampler.cpu_pct), ms: sampler.last_ms.toFixed(1), n: sampler.processes })}
          </span>
        )}
      </header>
      <p className="res-scope-note" data-testid="res-scope-note">
        {t('res.thisPcOnly', { host: snapshot.hostname ?? '?' })} {t(snapshot.own_user_only ? 'res.ownUserOnly' : 'res.allUsers')}
      </p>
      <HostOverview host={snapshot.host} />
      {snapshot.breakdown && <BreakdownView breakdown={snapshot.breakdown} memTotal={snapshot.host.mem.total} />}
      <section className="res-proc-groups" aria-label={t('res.procs.title')}>
        <h3>{t('res.procs.title')}</h3>
        <ProcessGroupTable title="res.procs.group.ros" procs={groups.ros} onNode={openNode} detailed estimated={estimated} />
        <ProcessGroupTable title="res.procs.group.self" procs={groups.self} onNode={openNode} detailed estimated={estimated} />
        <ProcessGroupTable title="res.procs.group.other" procs={groups.other} detailed={false} />
      </section>
      <ConnectionsView connections={snapshot.connections ?? []} events={snapshot.events ?? []} />
    </div>
  );
}
