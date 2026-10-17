// Pick -> 「起動」: the command and one button; everything else is folded into 詳細設定.

import { t } from '../i18n';
import { Term } from '../lib/Term';
import type { TargetForm } from './form';
import { KeyValueRows } from './KeyValueRows';

interface Props {
  form: TargetForm;
  editing: boolean;
  busy: boolean;
  onChange: (patch: Partial<TargetForm>) => void;
  onSubmit: (startAfter: boolean) => void;
  onCancel: () => void;
}

function commandPreview(form: TargetForm): string {
  if (form.kind === 'launch') return `ros2 launch ${form.package} ${form.launchFile}`;
  return `ros2 run ${form.package} ${form.executable}`;
}

function RunFields({ form, onChange }: Pick<Props, 'form' | 'onChange'>) {
  return (
    <>
      <label>
        <span>{t('launcher.form.name')} <Term term="node" /></span>
        <input value={form.name} onChange={(e) => onChange({ name: e.target.value })} data-testid="target-form-name" />
        <span className="muted small">{t('launcher.form.nameHelp')}</span>
      </label>
      <label>
        <span>{t('launcher.form.namespace')} <Term term="namespace" /></span>
        <input value={form.namespace} onChange={(e) => onChange({ namespace: e.target.value })} />
      </label>
      <KeyValueRows label={t('launcher.form.params')} help={`${t('launcher.form.paramsHelp')} ${t('term.parameter')}`} rows={form.params} onChange={(params) => onChange({ params })} testId="target-form-params" />
      <KeyValueRows
        label={t('launcher.form.remaps')}
        help={t('term.remap')}
        rows={form.remaps}
        keyLabel={t('launcher.form.from')}
        valueLabel={t('launcher.form.to')}
        onChange={(remaps) => onChange({ remaps })}
        testId="target-form-remaps"
      />
      <label>
        <span>{t('launcher.form.paramsFile')} <Term term="paramsFile" /></span>
        <input value={form.paramsFile} onChange={(e) => onChange({ paramsFile: e.target.value })} />
      </label>
      <label>
        {t('launcher.form.args')}
        <input value={form.args} onChange={(e) => onChange({ args: e.target.value })} />
      </label>
    </>
  );
}

function Advanced({ form, onChange }: Pick<Props, 'form' | 'onChange'>) {
  return (
    <>
      {form.kind === 'run' ? (
        <RunFields form={form} onChange={onChange} />
      ) : (
        <KeyValueRows label={t('launcher.form.launchArgs')} help={t('term.launch')} rows={form.launchArgs} onChange={(launchArgs) => onChange({ launchArgs })} testId="target-form-launch-args" />
      )}
      <label className="check">
        <input type="checkbox" checked={form.mine} onChange={(e) => onChange({ mine: e.target.checked })} data-testid="target-form-mine" />
        {t('launcher.form.mine')}
      </label>
      <span className="muted small">{t('launcher.form.mineHelp')}</span>
      <label className="check">
        <input type="checkbox" checked={form.autostart} onChange={(e) => onChange({ autostart: e.target.checked })} />
        {t('launcher.form.autostart')}
      </label>
      <label className="check">
        <input type="checkbox" checked={form.autoRestart} onChange={(e) => onChange({ autoRestart: e.target.checked })} />
        {t('launcher.form.autoRestart')}
      </label>
    </>
  );
}

export function TargetFormView({ form, editing, busy, onChange, onSubmit, onCancel }: Props) {
  return (
    <form
      className="target-form"
      data-testid="target-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(!editing);
      }}
    >
      <h3>{editing ? t('launcher.form.editTitle', { id: form.id }) : t('launcher.form.title')}</h3>
      <code className="mono command-preview">{commandPreview(form)}</code>
      <details className="advanced" open={editing} data-testid="target-form-advanced">
        <summary>{t('launcher.form.advanced')}</summary>
        <Advanced form={form} onChange={onChange} />
      </details>
      <div className="row">
        <button type="submit" className="primary" disabled={busy} data-testid="target-form-submit">
          {editing ? t('launcher.form.update') : t('launcher.form.launch')}
        </button>
        <button type="button" onClick={onCancel}>{t('common.cancel')}</button>
      </div>
      {!editing && <span className="muted small">{t('launcher.form.autoRegister')}</span>}
    </form>
  );
}
