// Current sockets with a remote address, and the open / close timeline (metadata only).

import { useState } from 'react';
import type { ConnEvent, ConnInfo } from '../api/resourceTypes';
import { t } from '../i18n';
import { connRemote, connWho } from './model';

const MAX_ROWS = 50;

function clock(epochSec: number): string {
  return new Date(epochSec * 1000).toLocaleTimeString();
}

export function ConnectionsView({ connections, events }: { connections: ConnInfo[]; events: ConnEvent[] }) {
  // The PC's own loopback traffic (the browser's WebSocket to roshanavi, local services) hides
  // what this view is for, the PC's outside communication: shown only on request.
  const [showLocal, setShowLocal] = useState(false);
  const localCount = connections.filter((c) => c.local).length;
  const shown = showLocal ? connections : connections.filter((c) => !c.local);
  const recent = [...events].filter((e) => showLocal || !e.local).reverse().slice(0, MAX_ROWS);
  return (
    <section className="res-conns-view" aria-labelledby="res-conn-title" data-testid="res-connections">
      <h3 id="res-conn-title">{t('res.conn.title')}</h3>
      <p className="muted small">{t('res.conn.help')}</p>
      <label className="check small">
        <input type="checkbox" checked={showLocal} onChange={(e) => setShowLocal(e.target.checked)} data-testid="res-conn-local" />
        {t('res.conn.showLocal', { n: localCount })}
      </label>
      {shown.length === 0 ? (
        <p className="muted small">{t('res.conn.none')}</p>
      ) : (
        <table className="res-table">
          <thead>
            <tr>
              <th>{t('res.conn.who')}</th>
              <th>{t('res.conn.remote')}</th>
              <th>{t('res.conn.state')}</th>
            </tr>
          </thead>
          <tbody>
            {shown.slice(0, MAX_ROWS).map((c) => (
              <tr key={`${c.pid}:${c.proto}:${c.laddr}:${c.raddr}`}>
                <td className="mono">{connWho(c)}</td>
                <td className="mono">{c.proto.toUpperCase()} {connRemote(c)}</td>
                <td className="small">{c.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h4>{t('res.conn.timeline')}</h4>
      {recent.length === 0 ? (
        <p className="muted small">{t('res.conn.timelineNone')}</p>
      ) : (
        <ol className="res-timeline">
          {recent.map((e) => (
            <li key={e.seq} className={`ev-${e.kind}`}>
              <span className="mono small">{clock(e.t)}</span>{' '}
              <span className={`badge ev-badge-${e.kind}`}>{t(e.kind === 'open' ? 'res.conn.open' : 'res.conn.close')}</span>{' '}
              <span className="mono">{connWho(e)}</span> → <span className="mono">{e.proto.toUpperCase()} {connRemote(e)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
