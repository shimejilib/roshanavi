// Right pane: CPU / memory / disk I/O / connections of the selected node's process, with
// 5-minute sparklines (resource monitoring, docs/design/resources.md).

import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { NodeHistoryResponse } from '../api/resourceTypes';
import { t } from '../i18n';
import { formatRate } from '../lib/format';
import { useLive } from '../state/LiveProvider';
import { Sparkline } from '../traffic/Sparkline';
import { ConfidenceBadge } from '../resources/ConfidenceBadge';
import { connRemote, formatCpu, formatMem, growthText, ioValues, leakStatusText, sparkValues } from '../resources/model';

const POLL_MS = 2000;
const MAX_CONNECTIONS = 10;
const MIB = 1024 * 1024;

function useNodeHistory(nodeId: string, enabled: boolean): NodeHistoryResponse | null {
  const [data, setData] = useState<NodeHistoryResponse | null>(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    const load = () => {
      api.resourceHistory(nodeId).then(
        (res) => alive && setData(res),
        () => alive && setData(null), // a failed poll shows the live badge values only
      );
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [nodeId, enabled]);
  return data;
}

function Row({ label, value, help }: { label: string; value: string; help?: string }) {
  return (
    <>
      <dt title={help}>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

export function NodeResources({ nodeId }: { nodeId: string }) {
  const { live } = useLive();
  const res = live.resources;
  const badge = res?.nodes[nodeId];
  const data = useNodeHistory(nodeId, Boolean(res?.available && badge));
  if (!res?.available) return null;
  if (!badge) {
    return (
      <section className="node-resources" data-testid="node-resources">
        <h4>{t('res.node.title')}</h4>
        <p className="muted small">{t('res.node.none')}</p>
      </section>
    );
  }
  const cur = data?.current;
  const leakNote = leakStatusText(cur?.leak ?? badge.leak);
  const hist = data?.history;
  const pidText = cur && cur.pids.length > 1 ? t('res.node.pids', { pids: cur.pids.join(', ') }) : t('res.node.pid', { pid: badge.pid ?? '?' });
  return (
    <section className="node-resources" data-testid="node-resources">
      <h4>
        {t('res.node.title')} <ConfidenceBadge confidence={badge.confidence} shared={badge.shared} scope={badge.scope} target={cur?.target_id ?? null} />
      </h4>
      <div className="muted small">{pidText}</div>
      <dl className="res-grid">
        <Row label={t('res.cpu')} help={t('res.cpuHelp')} value={formatCpu(badge.cpu_pct)} />
        <Row label={t('res.rss')} help={t('res.rssHelp')} value={formatMem(badge.rss)} />
        {cur?.uss != null && <Row label={t('res.uss')} help={t('res.ussHelp')} value={formatMem(cur.uss)} />}
        <Row label={t('res.growth')} value={growthText(cur?.leak ?? badge.leak)} />
        {cur && <Row label={t('res.io')} value={t('res.ioValue', { read: formatRate(cur.read_bps), write: formatRate(cur.write_bps) })} />}
        {cur?.threads != null && <Row label={t('res.threads')} value={String(cur.threads)} />}
        {cur?.fds != null && <Row label={t('res.fds')} value={String(cur.fds)} />}
        {cur?.gpu_mem != null && <Row label={t('res.gpuMem')} value={formatMem(cur.gpu_mem)} />}
      </dl>
      {leakNote && (
        <p className={leakNote.kind === 'suspect' ? 'warn-text small' : 'muted small'} title={leakNote.kind === 'watch' ? t('res.leak.watchHelp') : undefined}>
          {leakNote.kind === 'suspect' ? '⚠ ' : ''}{leakNote.text}
        </p>
      )}
      {hist && (
        <div className="res-sparks" aria-label={t('res.node.history')}>
          <div><span className="muted small">{t('res.cpu')}</span><Sparkline values={sparkValues(hist.cpu_pct)} color="#2563eb" /></div>
          <div><span className="muted small">{t('res.rss')} (MB)</span><Sparkline values={sparkValues(hist.rss, MIB)} color="#16a34a" /></div>
          <div><span className="muted small">{t('res.io')}</span><Sparkline values={ioValues(hist.read_bps, hist.write_bps)} color="#d97706" /></div>
        </div>
      )}
      {data && (
        <div className="res-conns">
          <div className="muted small">{t('res.node.connections', { n: data.connections.length })}</div>
          {data.connections.length === 0 ? (
            <p className="muted small">{t('res.node.noConnections')}</p>
          ) : (
            <ul className="res-conn-list">
              {data.connections.slice(0, MAX_CONNECTIONS).map((c) => (
                <li key={`${c.pid}:${c.proto}:${c.laddr}:${c.raddr}`} className="mono small">
                  {c.proto.toUpperCase()} → {connRemote(c)} <span className="muted">{c.status}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
