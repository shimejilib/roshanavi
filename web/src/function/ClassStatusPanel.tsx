// Live status of a class node: state, parameters, counters, the last error with file:line, the
// "state was reset" notice and one button per action method (「<method> を呼ぶ」).

import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { ActionRecord, ClassSpec, ClassStatus } from '../api/classTypes';
import type { Target } from '../api/types';
import { t, tDynamic } from '../i18n';
import { formatClock } from '../lib/format';
import { DependencyPanel } from './DependencyPanel';

export function classStatusOf(target: Target): ClassStatus | null {
  const status = target.function_status;
  return status && 'kind' in status && status.kind === 'class' ? status : null;
}

function ActionButton({ target, method, record }: { target: Target; method: string; record: ActionRecord | undefined }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const running = target.status === 'running';
  const call = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await api.callClassMethod(target.id, method);
      const ok = res.record ? res.record.ok !== false : true;
      setMessage({ ok, text: ok ? t('class.called', { method, result: res.record?.result ?? '—' }) : t('class.callFailed', { method, message: res.record?.error?.message ?? '' }) });
    } catch (err) {
      setMessage({ ok: false, text: describeError(err) });
    } finally {
      setBusy(false);
    }
  };
  const last = record?.last_at ? record : null;
  return (
    <li className="class-action" data-testid={`class-action-${method}`}>
      <button type="button" onClick={() => void call()} disabled={!running || busy} title={running ? undefined : t('class.notRunning')} data-testid={`class-call-${method}`}>
        {t('class.callButton', { method })}
      </button>
      {last && (
        <span className="muted small" data-testid={`class-last-${method}`}>
          {t('class.lastCall', { count: last.count, time: formatClock(last.last_at ?? 0) })}
          {last.ok ? (last.result ? ` → ${last.result}` : '') : ` — ${last.error?.message ?? ''}`}
        </span>
      )}
      {message && <span className={message.ok ? 'ok-text small' : 'error-text small'} role="status" data-testid={`class-call-result-${method}`}>{message.text}</span>}
    </li>
  );
}

export function ClassStatusPanel({ target }: { target: Target }) {
  const status = classStatusOf(target);
  const spec = target.spec as ClassSpec;
  if (!status) {
    return (
      <section className="function-status" data-testid="class-status" data-state="none">
        <h4>{t('function.status')}</h4>
        <p className="muted small">{t('function.status.none')}</p>
      </section>
    );
  }
  const error = status.state === 'running' ? status.last_error : (status.problem ?? status.last_error);
  const notice = status.notice;
  return (
    <section className="function-status" data-testid="class-status" data-state={status.state}>
      <h4>{t('function.status')}</h4>
      <p>
        <span className={`status-chip ${status.state === 'running' ? 'st-running' : status.state === 'starting' ? 'st-starting' : 'st-bad'}`}>
          {tDynamic(`class.status.${status.state}`, 'class.status.running')}
        </span>{' '}
        {status.signature && <code className="mono">{status.signature}</code>}
      </p>
      {status.location && <p className="muted small">{t('function.defined', { location: status.location })}</p>}
      {notice && (
        <p className="notice-box small" role="status" data-testid="class-notice" data-kind={notice.kind}>
          {t(notice.kind === 'reset' ? 'class.notice.reset' : 'class.notice.kept', { time: formatClock(notice.at), reason: t(`class.reason.${notice.reason}`) })}
        </p>
      )}
      {status.params.length > 0 && (
        <dl className="stats" data-testid="class-param-values">
          {status.params.filter((p) => p.kind !== null).map((p) => (
            <div key={p.name}><dt className="mono">{p.name}</dt><dd className="mono">{p.value === null ? t('class.unset') : String(p.value)}</dd></div>
          ))}
        </dl>
      )}
      <p className="small" data-testid="class-stats">{t('class.stats', { ...status.stats })}</p>
      {status.warnings.map((w) => <p key={w} className="muted small">⚠ {w}</p>)}
      {error && (
        <div className="error-box" role="alert" data-testid="class-error">
          <strong>{t('class.lastError')}</strong>
          {error.location && <div className="mono small">{t('function.where', { location: error.location })}</div>}
          <div className="mono small">{error.message}</div>
        </div>
      )}
      {spec.actions.length > 0 && (
        <ul className="plain-list class-actions" data-testid="class-actions">
          {spec.actions.map((method) => <ActionButton key={method} target={target} method={method} record={status.actions[method]} />)}
        </ul>
      )}
      <DependencyPanel module={spec.module} environment={status.environment} notices={status.notices} problem={status.problem} lastError={status.last_error} />
    </section>
  );
}
