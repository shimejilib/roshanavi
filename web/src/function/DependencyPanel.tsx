// Which Python runs a function / class node, its requirements.txt check, notices (slow import, rclpy,
// extension modules) and — when an import failed for a missing library — what to do about it:
// ① package.xml + rosdep (recommended) or ② a venv. roshanavi never runs pip (docs/design/user-code.md).

import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { CodeNotice, DependencyHint, NodeEnvironment } from '../api/codeTypes';
import type { FunctionProblem } from '../api/functionTypes';
import { t } from '../i18n';
import { missingModuleOf, noticeText, requirementsLines, rosdepRoute } from './codeLocations';

interface Props {
  module: string;
  environment?: NodeEnvironment;
  notices?: CodeNotice[];
  problem?: Pick<FunctionProblem, 'missing_module'> | null;
  lastError?: Pick<FunctionProblem, 'missing_module'> | null;
}

function Command({ code }: { code: string }) {
  return <pre className="mono code-command">{code}</pre>;
}

function MissingLibrary({ missing, module }: { missing: string; module: string }) {
  const [hint, setHint] = useState<DependencyHint | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setHint(null);
    api
      .dependencyHint(missing, module)
      .then((body) => !cancelled && setHint(body))
      .catch((err: unknown) => !cancelled && setError(describeError(err)));
    return () => {
      cancelled = true;
    };
  }, [missing, module]);
  const route1 = hint ? rosdepRoute(hint) : null;
  const places = hint?.code_places;
  const inRegistered = hint?.route === 'code_path_restart' || hint?.route === 'code_path_missing';
  return (
    <div className="dep-missing" data-testid="dep-missing" data-route={hint?.route}>
      <p className="error-text"><strong>{t('dep.missing', { module: missing })}</strong></p>
      {!hint && !error && <p className="muted small">{t('dep.loading')}</p>}
      {error && <p className="error-text small">{error}</p>}
      {hint && places && hint.route === 'code_path_restart' && places.found_in && (
        <p className="notice-box small" data-testid="dep-code-path">
          {t('dep.codePath.restart', { path: places.found_in.path, module: hint.top, file: places.found_in.file })}
        </p>
      )}
      {hint && places && hint.route === 'code_path_missing' && places.looks_like && (
        <p className="notice-box small" data-testid="dep-code-path">
          {t('dep.codePath.missing', { path: places.looks_like.path, module: hint.top })}
        </p>
      )}
      {hint && !inRegistered && places && (
        <p className="small" data-testid="dep-code-places">
          {places.registered.length > 0
            ? t('dep.codePath.registeredNone', { paths: places.registered.map((r) => r.path).join(', '), module: hint.top })
            : null}{' '}
          {t('dep.codePath.register', { module: hint.top })}
        </p>
      )}
      {hint && !inRegistered && (
        <>
          <section className={hint.route === 'rosdep' ? 'dep-route recommended' : 'dep-route'} data-testid="dep-route-rosdep">
            <h5>{t('dep.route1')}</h5>
            {route1 ? (
              route1.map((step, i) => (
                <div key={i}>
                  <p className="small">{step.text}</p>
                  {step.code && <Command code={step.code} />}
                </div>
              ))
            ) : (
              <p className="small">{t('dep.route1.none', { module: hint.top, tried: (hint.rosdep.tried ?? []).join(', ') || '—' })}</p>
            )}
          </section>
          <section className={hint.route === 'venv' ? 'dep-route recommended' : 'dep-route'} data-testid="dep-route-venv">
            <h5>{t('dep.route2')}</h5>
            <p className="small">{hint.venv.active ? t('dep.route2.active') : t('dep.route2.help')}</p>
            <Command code={hint.venv.commands.join('\n')} />
            {hint.venv.pip_name_differs && <p className="small">{t('dep.route2.pipName', { pip: hint.venv.pip_name, module: hint.top })}</p>}
            {!hint.venv.active && <p className="muted small">{t('dep.route2.restart')}</p>}
            <p className="muted small">{t('dep.never')}</p>
          </section>
          <p className="small" data-testid="dep-after">{t('dep.afterInstall')}</p>
        </>
      )}
    </div>
  );
}

export function DependencyPanel({ module, environment, notices, problem, lastError }: Props) {
  const missing = missingModuleOf(problem, lastError);
  if (!environment && !missing && !(notices && notices.length)) return null;
  const python = environment?.python;
  return (
    <section className="dep-panel" data-testid="dep-panel">
      <h5>{t('dep.title')}</h5>
      {python && (
        <p className="small" data-testid="dep-python" data-venv={python.venv ? 'yes' : 'no'}>
          {t('dep.python', { executable: python.executable, version: python.version })} — {python.venv ? t('dep.venvYes') : t('dep.venvNo')}
        </p>
      )}
      {environment?.scope === 'installed' && environment.loaded_from && (
        <p className="muted small">{t('dep.loadedFrom', { file: environment.loaded_from })}</p>
      )}
      {(environment?.requirements ?? []).map((req) => (
        <div key={req.file} className="dep-req small" data-testid="dep-requirements">
          <p className="small">{t('dep.requirements', { file: req.file })}</p>
          <ul className="plain-list">
            {requirementsLines(req).map((line) => <li key={line.text} className={line.bad ? 'error-text' : undefined}>{line.text}</li>)}
          </ul>
        </div>
      ))}
      {(notices ?? []).map((notice) => (
        <p key={notice.code} className="notice-box small" data-testid="dep-notice" data-code={notice.code}>{noticeText(notice)}</p>
      ))}
      {missing && <MissingLibrary missing={missing} module={module} />}
    </section>
  );
}
