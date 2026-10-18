// Breakdown bars (ROS / roshanavi / other) and the process table grouped by role.

import type { Breakdown, ProcInfo } from '../api/resourceTypes';
import { t, type MessageKey } from '../i18n';
import { formatRate } from '../lib/format';
import { ConfidenceBadge } from './ConfidenceBadge';
import { cpuSegments, formatCpu, formatMem, growthText, leakStatusText, loadLevel, memSegments, selfLabel, type ShareSegment } from './model';

function ShareBar({ segments, label }: { segments: ShareSegment[]; label: string }) {
  return (
    <div className="res-share" aria-label={label}>
      {segments.map((s) => (
        <span key={s.key} className={`seg seg-${s.key}`} style={{ width: `${s.pct}%` }} title={`${s.key}: ${s.pct.toFixed(1)}%`} />
      ))}
    </div>
  );
}

export function BreakdownView({ breakdown, memTotal }: { breakdown: Breakdown; memTotal: number }) {
  const cpu = breakdown.cpu;
  const top = cpu.other_top.filter((i) => i.cpu_norm_pct > 0).map((i) => `${i.name} ${formatCpu(i.cpu_norm_pct)}`);
  const memTop = breakdown.mem.other_top.map((i) => `${i.name} ${formatMem(i.rss)}`);
  return (
    <section className="res-breakdown" aria-labelledby="res-breakdown-title" data-testid="res-breakdown">
      <h3 id="res-breakdown-title">{t('res.breakdown.title')}</h3>
      <div className="res-share-row">
        <span className="res-share-label">{t('res.cpu')}</span>
        <ShareBar segments={cpuSegments(breakdown)} label={t('res.cpu')} />
        <span className="res-share-legend">
          <span className="key seg-ros" />{t('res.breakdown.ros')} {formatCpu(cpu.ros)}
          <span className="key seg-self" />{t('res.breakdown.self')} {formatCpu(cpu.self)}
          <span className="key seg-other" />{t('res.breakdown.other')} {formatCpu(cpu.other)}
        </span>
      </div>
      {top.length > 0 && <div className="muted small">{t('res.breakdown.otherTop', { items: top.join('、') })}</div>}
      <div className="res-share-row">
        <span className="res-share-label">{t('res.mem')}</span>
        <ShareBar segments={memSegments(breakdown, memTotal)} label={t('res.mem')} />
        <span className="res-share-legend">
          <span className="key seg-ros" />{t('res.breakdown.ros')} {formatMem(breakdown.mem.ros)}
          <span className="key seg-self" />{t('res.breakdown.self')} {formatMem(breakdown.mem.self)}
          <span className="key seg-other" />{t('res.breakdown.other')} {formatMem(breakdown.mem.other)}
        </span>
      </div>
      {memTop.length > 0 && <div className="muted small">{t('res.breakdown.otherTop', { items: memTop.join('、') })}</div>}
      <p className="muted small">{t('res.breakdown.memNote')} {t('res.breakdown.otherNote')}</p>
    </section>
  );
}

/** The `ros2 run` launcher process of a target (no node of its own). */
function isWrapper(p: ProcInfo): boolean {
  return p.group === 'ros' && p.nodes.length === 0 && p.exe === 'ros2';
}

function GrowthCell({ p }: { p: ProcInfo }) {
  const note = leakStatusText(p.leak);
  return (
    <td className={note?.kind === 'suspect' ? 'warn-text small' : 'small'} data-testid="res-growth">
      {growthText(p.leak)}
      {note && (
        <div className={note.kind === 'watch' ? 'muted' : undefined} title={note.kind === 'watch' ? t('res.leak.watchHelp') : undefined}>
          {note.text}
        </div>
      )}
    </td>
  );
}

function rowClass(p: ProcInfo): string {
  return [`lv-${loadLevel(p.cpu_pct)}`, p.leak?.suspect ? 'leak' : '', isWrapper(p) ? 'wrapper' : ''].filter(Boolean).join(' ');
}

interface TableProps {
  title: MessageKey;
  titleParams?: Record<string, string | number>;
  procs: ProcInfo[];
  onNode?: (node: string) => void;
  detailed: boolean;
  estimated?: ReadonlySet<string>;
}

function RoleCell({ p, onNode, estimated }: { p: ProcInfo; onNode?: (node: string) => void; estimated?: ReadonlySet<string> }) {
  if (p.nodes.length > 0) {
    return (
      <>
        {p.nodes.map((n) => (
          <button key={n} type="button" className="link mono" onClick={() => onNode?.(n)} data-testid="res-proc-node">
            {n}
          </button>
        ))}
        {p.nodes.some((n) => estimated?.has(n)) && <ConfidenceBadge confidence="heuristic" />}
      </>
    );
  }
  if (p.group === 'self') return <span>{selfLabel(p.label)}</span>;
  if (p.group === 'ros') return <span className="mono">{p.target_id ?? p.label}</span>;
  return <span className="muted">—</span>;
}

export function ProcessGroupTable({ title, titleParams, procs, onNode, detailed, estimated }: TableProps) {
  return (
    <section className="res-procs">
      <h4>{t(title, titleParams)}</h4>
      {procs.length === 0 ? (
        <p className="muted small">{t('res.procs.empty')}</p>
      ) : (
        <table className="res-table">
          <thead>
            <tr>
              <th>{t('res.procs.name')}</th>
              <th>{t('res.procs.label')}</th>
              <th className="num" title={t('res.cpuHelp')}>{t('res.cpu')}</th>
              <th className="num" title={t('res.rssHelp')}>{t('res.rss')}</th>
              {detailed && <th className="num" title={t('res.ussHelp')}>{t('res.uss')}</th>}
              {detailed && <th>{t('res.io')}</th>}
              {detailed && <th className="num">{t('res.threads')}</th>}
              {detailed && <th className="num">{t('res.fds')}</th>}
              {detailed && <th>{t('res.growth')}</th>}
            </tr>
          </thead>
          <tbody>
            {procs.map((p) => (
              <tr key={p.pid} className={rowClass(p)} data-testid={`res-proc-${p.group}`}>
                <td className="mono" title={isWrapper(p) ? `pid ${p.pid}: ${t('res.procs.wrapperHelp')}` : `pid ${p.pid}`}>{p.name}</td>
                <td><RoleCell p={p} onNode={onNode} estimated={estimated} /></td>
                <td className="num">{formatCpu(p.cpu_pct)}</td>
                <td className="num">{formatMem(p.rss)}</td>
                {detailed && <td className="num">{formatMem(p.uss)}</td>}
                {detailed && <td className="small">{t('res.ioValue', { read: formatRate(p.read_bps), write: formatRate(p.write_bps) })}</td>}
                {detailed && <td className="num">{p.threads ?? '—'}</td>}
                {detailed && <td className="num">{p.fds ?? '—'}</td>}
                {detailed && <GrowthCell p={p} />}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
