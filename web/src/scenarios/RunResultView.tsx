// Result of a scenario run: per step status with the plain explanation and cause hints.

import type { RunResult, RunStatus, SetupResult, StepResult } from '../api/scenarioTypes';
import { t, tDynamic } from '../i18n';

const MARK: Record<RunStatus, string> = {
  pending: '·',
  running: '▶',
  passed: '✔',
  failed: '✘',
  error: '✘',
  skipped: '−',
  cancelled: '■',
};

function StatusMark({ status }: { status: RunStatus }) {
  return (
    <span className={`scn-mark scn-${status}`} aria-label={tDynamic(`scn.status.${status}`, 'scn.status.pending')}>
      {MARK[status]}
    </span>
  );
}

function Details({ step }: { step: StepResult }) {
  const values = step.details.last_values as unknown[] | undefined;
  const keys = Object.entries(step.details).filter(([k]) => !['last_values', 'mismatches', 'limits', 'value'].includes(k));
  if (!keys.length && !values?.length) return null;
  return (
    <details className="scn-details">
      <summary>{t('scn.details')}</summary>
      <dl>
        {keys.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className="mono">{typeof v === 'number' ? Number(v.toFixed(4)) : JSON.stringify(v)}</dd>
          </div>
        ))}
      </dl>
      {values && values.length > 0 && (
        <>
          <p className="muted small">{t('scn.lastValues')}</p>
          <pre className="mono small">{values.map((v) => JSON.stringify(v)).join('\n')}</pre>
        </>
      )}
    </details>
  );
}

function StepRow({ step, label }: { step: StepResult; label: string }) {
  const showMessage = step.message && (step.status !== 'passed' || ['rate', 'throughput', 'latency'].includes(step.kind));
  return (
    <li className={`scn-step scn-row-${step.status}`} data-testid={`scn-step-${label}`} data-status={step.status}>
      <div className="scn-step-head">
        <StatusMark status={step.status} />
        <span className="scn-step-label">{label}</span>
        <span className="scn-step-summary">{step.summary}</span>
        {step.approx && <span className="badge" title={t('scn.approxHelp')}>{t('scn.approx')}</span>}
        {step.duration_sec !== null && step.status !== 'skipped' && (
          <span className="muted small">{t('scn.seconds', { sec: step.duration_sec.toFixed(2) })}</span>
        )}
      </div>
      {showMessage && (
        <p className={step.status === 'passed' ? 'scn-message' : 'scn-message scn-message-bad'} data-testid="scn-step-message">
          {step.message}
        </p>
      )}
      {step.hints.length > 0 && (
        <ul className="scn-hints">
          {step.hints.map((h, i) => (
            <li key={i}>
              <strong>{t('scn.hint')}</strong> {h.message}
            </li>
          ))}
        </ul>
      )}
      {step.status !== 'pending' && step.status !== 'skipped' && <Details step={step} />}
    </li>
  );
}

function SetupRow({ item }: { item: SetupResult }) {
  return (
    <li className={`scn-step scn-row-${item.status}`}>
      <div className="scn-step-head">
        <StatusMark status={item.status} />
        <span className="scn-step-label">{t('scn.setupLabel', { n: item.index + 1 })}</span>
        <span className="scn-step-summary mono">{item.summary}</span>
      </div>
      {item.message && item.status !== 'passed' && <p className="scn-message scn-message-bad">{item.message}</p>}
      {item.log_tail.length > 0 && item.status === 'failed' && <pre className="mono small scn-log">{item.log_tail.join('\n')}</pre>}
    </li>
  );
}

export function RunResultView({ result, onCancel }: { result: RunResult; onCancel?: () => void }) {
  const running = result.status === 'running' || result.status === 'pending';
  return (
    <section className="scn-result" aria-labelledby="scn-result-title" data-testid="scn-result" data-tour="scn-result" data-status={result.status}>
      <header className={`scn-banner scn-banner-${result.status}`}>
        <h3 id="scn-result-title">
          <StatusMark status={result.status} /> {tDynamic(`scn.result.${result.status}`, 'scn.result.pending')}
          <span className="scn-banner-name">{result.name}</span>
        </h3>
        <p data-testid="scn-result-message">{result.message}</p>
        <p className="muted small">
          {t('scn.when', { when: new Date(result.started_at * 1000).toLocaleString(), sec: result.duration_sec.toFixed(1) })}
        </p>
        {running && onCancel && (
          <button type="button" className="danger" onClick={onCancel} data-testid="scn-cancel">{t('scn.cancel')}</button>
        )}
      </header>
      {result.schema_errors.length > 0 && (
        <ul className="error-box">
          {result.schema_errors.map((e, i) => (
            <li key={i}>{e.line ? t('scn.errorLine', { path: e.path || '-', line: e.line, message: e.message }) : `${e.path}: ${e.message}`}</li>
          ))}
        </ul>
      )}
      {result.setup.length > 0 && (
        <>
          <h4>{t('scn.setup')}</h4>
          <ol className="scn-steps">{result.setup.map((s) => <SetupRow key={s.index} item={s} />)}</ol>
        </>
      )}
      {result.guards.length > 0 && (
        <>
          <h4>{t('scn.guards')}</h4>
          <ol className="scn-steps">
            {result.guards.map((g) => <StepRow key={g.index} step={g} label={t('scn.guardLabel', { n: g.index + 1 })} />)}
          </ol>
        </>
      )}
      {result.steps.length > 0 && (
        <>
          <h4>{t('scn.steps')}</h4>
          <ol className="scn-steps">
            {result.steps.map((s) => <StepRow key={s.index} step={s} label={String(s.index + 1)} />)}
          </ol>
        </>
      )}
    </section>
  );
}
