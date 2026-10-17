import { t } from '../i18n';
import type { KeyValueRow } from './form';

interface Props {
  label: string;
  rows: KeyValueRow[];
  onChange: (rows: KeyValueRow[]) => void;
  keyLabel?: string;
  valueLabel?: string;
  help?: string;
  testId: string;
}

/** Editable name/value rows (params, remaps, launch args). */
export function KeyValueRows({ label, rows, onChange, keyLabel, valueLabel, help, testId }: Props) {
  const set = (index: number, patch: Partial<KeyValueRow>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  return (
    <fieldset className="kv-rows" data-testid={testId}>
      <legend>{label}</legend>
      {help && <p className="muted small">{help}</p>}
      {rows.map((row, index) => (
        <div className="kv-row" key={index}>
          <input aria-label={keyLabel ?? t('launcher.form.key')} placeholder={keyLabel ?? t('launcher.form.key')} value={row.key} onChange={(e) => set(index, { key: e.target.value })} />
          <input aria-label={valueLabel ?? t('launcher.form.value')} placeholder={valueLabel ?? t('launcher.form.value')} value={row.value} onChange={(e) => set(index, { value: e.target.value })} />
          <button type="button" aria-label={t('common.remove')} onClick={() => onChange(rows.filter((_, i) => i !== index))}>×</button>
        </div>
      ))}
      <button type="button" className="link small" onClick={() => onChange([...rows, { key: '', value: '' }])}>
        {t('launcher.form.addRow')}
      </button>
    </fieldset>
  );
}
