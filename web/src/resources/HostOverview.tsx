// PC 全体: CPU per core, memory / swap, the data_dir volume, NICs, UDP buffer drops, GPU.

import type { HostInfo } from '../api/resourceTypes';
import { t, tDynamic } from '../i18n';
import { formatBytes, formatRate } from '../lib/format';
import { formatCpu, loadLevel } from './model';

function Meter({ pct, level }: { pct: number | null | undefined; level?: string }) {
  const width = Math.max(0, Math.min(100, pct ?? 0));
  return (
    <div className={`res-meter ${level ? `lv-${level}` : ''}`} role="meter" aria-valuenow={Math.round(width)} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${width}%` }} />
    </div>
  );
}

function CpuCard({ cpu }: { cpu: HostInfo['cpu'] }) {
  return (
    <article className="res-card" data-testid="res-host-cpu">
      <header><h4>{t('res.host.cpu')}</h4><span className="muted small">{t('res.host.cores', { n: cpu.cores })}</span></header>
      <div className="res-big">{formatCpu(cpu.total_pct)}</div>
      <Meter pct={cpu.total_pct} level={loadLevel(cpu.total_pct)} />
      <div className="res-cores" aria-label={t('res.host.cpu')}>
        {cpu.per_core.map((v, i) => (
          <span key={i} className={`lv-${loadLevel(v)}`} style={{ height: `${Math.max(4, v)}%` }} title={`#${i}: ${formatCpu(v)}`} />
        ))}
      </div>
    </article>
  );
}

function MemCard({ mem }: { mem: HostInfo['mem'] }) {
  return (
    <article className="res-card" data-testid="res-host-mem">
      <header><h4>{t('res.host.mem')}</h4><span className="muted small">{mem.pct == null ? '' : `${mem.pct}%`}</span></header>
      <div className="res-big">{formatBytes(mem.used)}</div>
      <Meter pct={mem.pct} level={loadLevel(mem.pct)} />
      <div className="muted small">{t('res.host.memValue', { used: formatBytes(mem.used), total: formatBytes(mem.total) })}</div>
      <div className="muted small">
        {mem.swap_total > 0 ? t('res.host.swap', { used: formatBytes(mem.swap_used), total: formatBytes(mem.swap_total) }) : t('res.host.noSwap')}
      </div>
    </article>
  );
}

function DiskCard({ disk }: { disk: HostInfo['disk'] }) {
  const level = disk.level ?? 'ok';
  const usedPct = disk.free_pct == null ? null : 100 - disk.free_pct;
  return (
    <article className={`res-card disk-${level}`} data-testid="res-host-disk">
      <header><h4>{t('res.host.disk', { path: disk.path })}</h4><span className={`badge disk-level-${level}`}>{tDynamic(`res.host.diskLevel.${level}`, 'res.host.diskLevel.ok')}</span></header>
      {disk.error ? (
        <p className="error-text small">{disk.error}</p>
      ) : (
        <>
          <div className="res-big">{t('res.host.diskFree', { free: formatBytes(disk.free), pct: disk.free_pct ?? '?' })}</div>
          <Meter pct={usedPct} level={level === 'ok' ? 'low' : level === 'warn' ? 'mid' : 'high'} />
          <div className="muted small">
            {disk.read_bps == null && disk.write_bps == null
              ? t('res.host.diskIoUnknown')
              : t('res.host.diskIo', { read: formatRate(disk.read_bps), write: formatRate(disk.write_bps) })}
            {disk.device ? ` (${disk.device})` : ''}
          </div>
        </>
      )}
    </article>
  );
}

function NetCard({ nics, udp }: { nics: HostInfo['nics']; udp: HostInfo['udp'] }) {
  return (
    <article className="res-card res-card-wide" data-testid="res-host-net">
      <header><h4 title={t('res.host.nicHelp')}>{t('res.host.nic')} ⓘ</h4></header>
      {nics.length === 0 && <p className="muted small">{t('res.host.nicNone')}</p>}
      <ul className="res-nics">
        {nics.map((n) => (
          <li key={n.name}>
            <span className="mono">{n.name}</span>
            <span>{t('res.host.nicRow', { rx: formatRate(n.rx_bps), tx: formatRate(n.tx_bps) })}</span>
            <span className={n.errin + n.errout + n.dropin + n.dropout > 0 ? 'warn-text small' : 'muted small'}>
              {t('res.host.nicErr', { err: n.errin + n.errout, drop: n.dropin + n.dropout })}
            </span>
          </li>
        ))}
      </ul>
      <div className="res-udp" title={t('res.host.udpHelp')}>
        <span className="muted small">{t('res.host.udp')} ⓘ</span>{' '}
        {udp ? (
          <span className={udp.rcvbuf_recent > 0 ? 'warn-text' : ''} data-testid="res-udp">
            {t('res.host.udpValue', { total: udp.rcvbuf_errors, recent: udp.rcvbuf_recent, sec: udp.recent_sec })}
          </span>
        ) : (
          <span className="muted">{t('res.host.udpNone')}</span>
        )}
      </div>
    </article>
  );
}

function GpuCard({ gpu }: { gpu: HostInfo['gpu'] }) {
  return (
    <article className="res-card" data-testid="res-host-gpu">
      <header><h4>{t('res.host.gpu')}</h4></header>
      {!gpu.available ? (
        <p className="muted small">{tDynamic(`res.host.gpuUnavailable.${gpu.reason ?? 'off'}`, 'res.host.gpuUnavailable.off')}</p>
      ) : (
        <>
          {gpu.devices.map((d) => (
            <div key={d.index}>
              <div className="small">{d.name ?? `GPU ${d.index}`}</div>
              <Meter pct={d.util_pct} level={loadLevel(d.util_pct)} />
              <div className="muted small">
                {t('res.host.gpuValue', {
                  util: d.util_pct == null ? '—' : `${d.util_pct}%`,
                  used: formatBytes(d.mem_used),
                  total: formatBytes(d.mem_total),
                  temp: d.temp_c == null ? '—' : `${d.temp_c}°C`,
                })}
              </div>
            </div>
          ))}
          {!gpu.per_process && <p className="muted small">{t('res.host.gpuNoPerProcess')}</p>}
        </>
      )}
      {gpu.wsl && <p className="muted small">{t('res.host.gpuWsl')}</p>}
    </article>
  );
}

export function HostOverview({ host }: { host: HostInfo }) {
  return (
    <section className="res-host" aria-labelledby="res-host-title">
      <h3 id="res-host-title">{t('res.host.title')}</h3>
      <div className="res-cards">
        <CpuCard cpu={host.cpu} />
        <MemCard mem={host.mem} />
        <DiskCard disk={host.disk} />
        <GpuCard gpu={host.gpu} />
        <NetCard nics={host.nics} udp={host.udp} />
      </div>
    </section>
  );
}
