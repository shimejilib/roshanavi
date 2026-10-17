// Step 1 of the import: which launch file, and the values of its arguments.

import type { ImportArgument } from '../api/nodeListTypes';
import type { WorkspacePackage } from '../api/types';
import { t } from '../i18n';
import { Term } from '../lib/Term';
import type { SourceForm } from './importModel';

interface Props {
  form: SourceForm;
  onForm: (form: SourceForm) => void;
  packages: WorkspacePackage[];
  args: ImportArgument[];
  values: Record<string, string>;
  missing: readonly string[];
  onValue: (name: string, value: string) => void;
}

function PackagePick({ form, onForm, packages }: Pick<Props, 'form' | 'onForm' | 'packages'>) {
  const files = packages.find((p) => p.name === form.package)?.launch_files ?? [];
  return (
    <div className="row wrap">
      <label>
        {t('import.package')}
        <select value={form.package} onChange={(e) => onForm({ ...form, package: e.target.value, launchFile: '' })} data-testid="import-package">
          <option value="">{t('import.choose')}</option>
          {packages.map((p) => <option key={p.name} value={p.name}>{p.name}{p.origin === 'workspace' ? ` (${t('launcher.origin.workspace')})` : ''}</option>)}
        </select>
      </label>
      <label>
        {t('import.launchFile')}
        <select value={form.launchFile} onChange={(e) => onForm({ ...form, launchFile: e.target.value })} disabled={!form.package} data-testid="import-file">
          <option value="">{t('import.choose')}</option>
          {files.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      </label>
    </div>
  );
}

function ArgFields({ args, values, missing, onValue }: Pick<Props, 'args' | 'values' | 'missing' | 'onValue'>) {
  if (args.length === 0) return null;
  return (
    <fieldset className="import-args" data-testid="import-args">
      <legend>{t('import.args')}</legend>
      {args.map((a) => (
        <label key={a.name} className={missing.includes(a.name) ? 'field-missing' : undefined}>
          <span className="mono">{a.name}</span>
          {a.choices ? (
            <select value={values[a.name] ?? ''} onChange={(e) => onValue(a.name, e.target.value)}>
              {a.choices.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          ) : (
            <input value={values[a.name] ?? ''} onChange={(e) => onValue(a.name, e.target.value)} placeholder={a.default ?? t('import.required')} data-testid={`import-arg-${a.name}`} />
          )}
          {a.description && <span className="muted small">{a.description}</span>}
        </label>
      ))}
    </fieldset>
  );
}

export function ImportSourceForm(props: Props) {
  const { form, onForm } = props;
  return (
    <div className="import-source">
      <div role="radiogroup" aria-label={t('import.sourceKind')}>
        <label className="radio">
          <input type="radio" checked={form.kind === 'package'} onChange={() => onForm({ ...form, kind: 'package' })} />
          {t('import.fromPackage')}
        </label>
        <label className="radio">
          <input type="radio" checked={form.kind === 'path'} onChange={() => onForm({ ...form, kind: 'path' })} data-testid="import-kind-path" />
          {t('import.fromPath')}
        </label>
        <Term term="launch" />
      </div>
      {form.kind === 'package' ? (
        <PackagePick form={form} onForm={onForm} packages={props.packages} />
      ) : (
        <label>
          {t('import.path')}
          <input value={form.path} onChange={(e) => onForm({ ...form, path: e.target.value })} placeholder="src/my_pkg/launch/robot.launch.py" data-testid="import-path" />
        </label>
      )}
      <p className="muted small">{t('import.trust')}</p>
      <ArgFields args={props.args} values={props.values} missing={props.missing} onValue={props.onValue} />
    </div>
  );
}
