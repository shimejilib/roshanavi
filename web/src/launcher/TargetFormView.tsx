import { t } from '../i18n';
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
        {t('launcher.form.name')}
        <input value={form.name} onChange={(e) => onChange({ name: e.target.value })} data-testid="target-form-name" />
        <span className="muted small">{t('launcher.form.nameHelp')}</span>
      </label>
      <label>
        {t('launcher.form.namespace')}
        <input value={form.namespace} onChange={(e) => onChange({ namespace: e.target.value })} />
      </label>
      <KeyValueRows label={t('launcher.form.params')} help={t('launcher.form.paramsHelp')} rows={form.params} onChange={(params) => onChange({ params })} testId="target-form-params" />
      <KeyValueRows
        label={t('launcher.form.remaps')}
        rows={form.remaps}
        keyLabel={t('launcher.form.from')}
        valueLabel={t('launcher.form.to')}
        onChange={(remaps) => onChange({ remaps })}
        testId="target-form-remaps"
      />
      <label>
        {t('launcher.form.paramsFile')}
        <input value={form.paramsFile} onChange={(e) => onChange({ paramsFile: e.target.value })} />
      </label>
      <label>
        {t('launcher.form.args')}
        <input value={form.args} onChange={(e) => onChange({ args: e.target.value })} />
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
      <div>
        <div className="muted small">{t('launcher.form.command')}</div>
        <code className="mono command-preview">{commandPreview(form)}</code>
      </div>
      {form.kind === 'run' ? (
        <RunFields form={form} onChange={onChange} />
      ) : (
        <KeyValueRows label={t('launcher.form.launchArgs')} rows={form.launchArgs} onChange={(launchArgs) => onChange({ launchArgs })} testId="target-form-launch-args" />
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
      <div className="row">
        {editing ? (
          <button type="submit" className="primary" disabled={busy}>{t('launcher.form.update')}</button>
        ) : (
          <>
            <button type="submit" className="primary" disabled={busy} data-testid="target-form-submit">{t('launcher.form.addAndStart')}</button>
            <button type="button" disabled={busy} onClick={() => onSubmit(false)}>{t('launcher.form.add')}</button>
          </>
        )}
        <button type="button" onClick={onCancel}>{t('common.cancel')}</button>
      </div>
    </form>
  );
}
