// 「コードの場所」 in the create dialog (docs/design/user-code.md): what scopes A / B / C found, the
// reasons other code is not a candidate (with the user's real paths and the next step), where to
// put code, which Python runs the nodes, adding / removing B paths and C modules, and 「ひな形を作る」.

import { useCallback, useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { CodeLocationsReport, ScaffoldResult } from '../api/codeTypes';
import { t, type MessageKey } from '../i18n';
import {
  addEntry,
  checkCodePath,
  checkModuleName,
  checkPackageName,
  DEFAULT_SCAFFOLD_NAME,
  placeHereText,
  problemText,
  removeEntry,
  type Check,
} from './codeLocations';

interface Props {
  /** A package was generated: preselect its function / class in the dialog. */
  onScaffolded: (result: ScaffoldResult) => void;
  /** Scope B / C changed: the module list must be read again. */
  onChanged: () => void;
}

function checkText(check: Check | null): string | null {
  return check ? t(check.key, check.params) : null;
}

function EntryAdder({ label, placeholder, testId, validate, onAdd }: {
  label: string;
  placeholder: string;
  testId: string;
  validate: (value: string) => Check | null;
  onAdd: (value: string) => Promise<string | null>;
}) {
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const add = async () => {
    const problem = checkText(validate(value));
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    const failed = await onAdd(value.trim());
    setBusy(false);
    setError(failed);
    if (!failed) setValue('');
  };
  return (
    <div className="code-adder">
      <div className="row">
        <label className="grow">
          {label}
          <input
            value={value}
            placeholder={placeholder}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void add();
              }
            }}
            data-testid={`${testId}-input`}
          />
        </label>
        <button type="button" onClick={() => void add()} disabled={busy} data-testid={`${testId}-add`}>{t('code.add')}</button>
      </div>
      {error && <p className="error-text small" role="alert" data-testid={`${testId}-error`}>{error}</p>}
    </div>
  );
}

function Scaffold({ report, onDone }: { report: CodeLocationsReport; onDone: (result: ScaffoldResult) => void }) {
  const [name, setName] = useState(DEFAULT_SCAFFOLD_NAME);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    const problem = checkText(checkPackageName(name.trim()));
    if (problem) {
      setMessage({ ok: false, text: problem });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.scaffold(name.trim());
      const file = result.files.find((f) => f.endsWith('/logic.py')) ?? result.directory;
      setMessage({ ok: true, text: t('code.scaffold.done', { directory: result.directory, module: result.module, file }) });
      onDone(result);
    } catch (err) {
      setMessage({ ok: false, text: describeError(err) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <fieldset className="code-scaffold" data-testid="scaffold">
      <legend>{t('code.scaffold.title')}</legend>
      <p className="muted small">{t('code.scaffold.help')}</p>
      {report.src_exists && !report.src_writable && <p className="notice-box small">{t('code.scaffold.readonly', { src: report.src })}</p>}
      <div className="row">
        <label className="grow">
          {t('code.scaffold.name')}
          <input value={name} onChange={(e) => setName(e.target.value)} data-testid="scaffold-name" />
        </label>
        <button type="button" onClick={() => void run()} disabled={busy} data-testid="scaffold-submit">{t('code.scaffold.button')}</button>
      </div>
      {message && <p className={message.ok ? 'ok-box small' : 'error-box small'} role="status" data-testid="scaffold-result">{message.text}</p>}
    </fieldset>
  );
}

export function CodeLocationsPanel({ onScaffolded, onChanged }: Props) {
  const [report, setReport] = useState<CodeLocationsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  // Closed by default; opens by itself when no code can be used yet (the reasons are the answer).
  const [open, setOpen] = useState(false);
  const [autoOpened, setAutoOpened] = useState(false);
  const load = useCallback(async (refresh = false) => {
    try {
      setReport(await api.codeLocations(refresh));
      setError(null);
    } catch (err) {
      setError(describeError(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const save = async (codePaths: string[], modules: string[]): Promise<string | null> => {
    try {
      setReport(await api.putCodeLocations({ code_paths: codePaths, installed_modules: modules }));
      setSaved(true);
      onChanged();
      return null;
    } catch (err) {
      return describeError(err);
    }
  };

  const settings = report?.settings ?? { code_paths: [], installed_modules: [] };
  const a = report?.scopes.workspace.packages.length ?? 0;
  const b = report?.scopes.code_paths.reduce((n, c) => n + c.packages.length, 0) ?? 0;
  const c = report?.scopes.installed_modules.filter((m) => m.status === 'found' || m.status === 'extension').length ?? 0;
  const python = report?.python;
  if (report && !autoOpened) {
    setAutoOpened(true);
    if (a + b + c === 0) setOpen(true);
  }
  return (
    <details className="code-locations" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)} data-testid="code-locations">
      <summary>
        <strong>{t('code.title')}</strong>{' '}
        <span className="muted small" data-testid="code-summary">{report ? t('code.summary', { a, b, c }) : t('code.loading')}</span>
        {report && report.problems.length > 0 && <span className="badge warn small">{t('code.problems', { count: report.problems.length })}</span>}
      </summary>
      <p className="muted small">{t('code.intro')}</p>
      {error && <p className="error-box small" role="alert">{error}</p>}
      {report && (
        <>
          <section className="code-scope" data-testid="code-scope-workspace">
            <h5>{t('code.scope.workspace')}</h5>
            <p className="muted small">{t('code.scope.workspaceHelp', { root: report.src })}</p>
            <p className="small">{t('code.packages', { list: report.scopes.workspace.packages.map((p) => p.top).join(', ') || t('code.noPackages') })}</p>
          </section>

          <section className="code-scope" data-testid="code-scope-code-path">
            <h5>{t('code.scope.code_path')}</h5>
            <p className="muted small">{t('code.scope.code_pathHelp')}</p>
            <ul className="plain-list">
              {report.scopes.code_paths.map((entry) => (
                <li key={entry.path} className="code-entry" data-testid="code-path-row" data-status={entry.status}>
                  <code className="mono">{entry.path}</code>{' '}
                  <span className={entry.status === 'ok' ? 'ok-text small' : 'error-text small'}>{t(`code.status.${entry.status}` as MessageKey)}</span>{' '}
                  {entry.packages.length > 0 && <span className="muted small">{t('code.packages', { list: entry.packages.map((p) => p.top).join(', ') })}</span>}
                  <button type="button" className="link small" onClick={() => void save(removeEntry(settings.code_paths, entry.path), settings.installed_modules)} data-testid="code-path-remove">
                    {t('code.remove')}
                  </button>
                </li>
              ))}
            </ul>
            <EntryAdder
              label={t('code.addPathLabel')}
              placeholder={t('code.pathPlaceholder')}
              testId="code-path"
              validate={(v) => checkCodePath(v, settings.code_paths)}
              onAdd={(v) => save(addEntry(settings.code_paths, v), settings.installed_modules)}
            />
          </section>

          <section className="code-scope" data-testid="code-scope-installed">
            <h5>{t('code.scope.installed')}</h5>
            <p className="muted small">{t('code.scope.installedHelp')}</p>
            <ul className="plain-list">
              {report.scopes.installed_modules.map((entry) => (
                <li key={entry.module} className="code-entry" data-testid="code-module-row" data-status={entry.status}>
                  <code className="mono">{entry.module}</code>{' '}
                  <span className={entry.status === 'found' ? 'ok-text small' : 'muted small'}>{t(`code.installed.${entry.status}` as MessageKey)}</span>
                  {entry.file && <span className="muted small"> — {entry.file}</span>}
                  <button type="button" className="link small" onClick={() => void save(settings.code_paths, removeEntry(settings.installed_modules, entry.module))} data-testid="code-module-remove">
                    {t('code.remove')}
                  </button>
                </li>
              ))}
            </ul>
            <EntryAdder
              label={t('code.addModuleLabel')}
              placeholder={t('code.modulePlaceholder')}
              testId="code-module"
              validate={(v) => checkModuleName(v, settings.installed_modules)}
              onAdd={(v) => save(settings.code_paths, addEntry(settings.installed_modules, v))}
            />
          </section>
          {saved && <p className="muted small" role="status">{t('code.saved')}</p>}

          <section className="code-problems" data-testid="code-problems">
            <h5>{report.problems.length > 0 ? t('code.problems', { count: report.problems.length }) : t('code.noProblems')}</h5>
            <ul className="plain-list">
              {report.problems.map((p, i) => (
                <li key={`${p.code}-${i}`} className="code-problem small" data-testid="code-problem" data-code={p.code}>
                  {problemText(p)}
                  {p.command && <pre className="mono code-command">{`cd ${p.root ?? ''}\n${p.command}`}</pre>}
                </li>
              ))}
            </ul>
          </section>

          <section className="code-place" data-testid="code-place-here">
            <h5>{t('code.placeHere')}</h5>
            <ul className="plain-list">
              {report.place_here.map((place) => <li key={`${place.scope}-${place.root}`} className="mono small">{placeHereText(place)}</li>)}
            </ul>
          </section>

          {python && (
            <p className="small" data-testid="code-python">
              {t('code.python', { executable: python.executable ?? t('code.python.unknown'), version: python.version ?? '?' })}{' — '}
              {python.venv ? t('code.python.venv') : t('code.python.notVenv')}
              {python.forced && <span className="muted"> ({t('code.python.forced', { python: python.forced })})</span>}
            </p>
          )}
          <div className="row end">
            <button type="button" className="small" onClick={() => void load(true)} data-testid="code-reload">{t('code.reload')}</button>
          </div>
          <Scaffold report={report} onDone={(result) => { void load(); onScaffolded(result); }} />
        </>
      )}
    </details>
  );
}
