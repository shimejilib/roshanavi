import type { DataFile, InjectMode } from '../api/types';
import { t, type MessageKey } from '../i18n';
import type { InjectForm } from './buildRequest';

export const MODES: InjectMode[] = ['once', 'periodic', 'stream', 'bag'];

interface ModeFieldsProps {
  form: InjectForm;
  files: DataFile[];
  onChange: (patch: Partial<InjectForm>) => void;
}

function FilePicker({ form, files, onChange }: ModeFieldsProps) {
  const wanted = form.mode === 'bag' ? ['bag'] : ['jsonl', 'csv'];
  const usable = files.filter((f) => wanted.includes(f.kind));
  if (usable.length === 0) return <p className="muted">{t('inject.sourceNone')}</p>;
  return (
    <label>
      {t('inject.source')}
      <select value={form.source} onChange={(e) => onChange({ source: e.target.value })}>
        <option value="">—</option>
        {usable.map((f) => (
          <option key={f.path} value={f.path}>
            {f.path}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ModeSelector({ form, onChange }: Omit<ModeFieldsProps, 'files'>) {
  return (
    <fieldset className="mode-select">
      <legend>{t('inject.mode')}</legend>
      {MODES.map((mode) => (
        <label key={mode} className="radio">
          <input type="radio" name="inject-mode" value={mode} checked={form.mode === mode} onChange={() => onChange({ mode })} />
          {t(`inject.mode.${mode}` as MessageKey)}
        </label>
      ))}
    </fieldset>
  );
}

export function ModeFields(props: ModeFieldsProps) {
  const { form, onChange } = props;
  return (
    <div className="mode-fields">
      {(form.mode === 'periodic' || form.mode === 'stream') && (
        <label>
          {t('inject.rate')}
          <input type="number" min="0.001" step="any" value={form.rateHz} onChange={(e) => onChange({ rateHz: e.target.value })} />
        </label>
      )}
      {form.mode === 'periodic' && (
        <label>
          {t('inject.count')}
          <input type="number" min="1" step="1" value={form.count} onChange={(e) => onChange({ count: e.target.value })} />
        </label>
      )}
      {(form.mode === 'stream' || form.mode === 'bag') && (
        <>
          <FilePicker {...props} />
          <label className="check">
            <input type="checkbox" checked={form.loop} onChange={(e) => onChange({ loop: e.target.checked })} />
            {t('inject.loop')}
          </label>
        </>
      )}
      {form.mode === 'bag' && (
        <>
          <label>
            {t('inject.bagRate')}
            <input type="number" min="0.01" step="any" value={form.bagRate} onChange={(e) => onChange({ bagRate: e.target.value })} />
          </label>
          <label>
            {t('inject.bagTopics')}
            <input type="text" value={form.bagTopics} onChange={(e) => onChange({ bagTopics: e.target.value })} />
          </label>
        </>
      )}
    </div>
  );
}

export function QosFields({ form, onChange }: Omit<ModeFieldsProps, 'files'>) {
  return (
    <details className="qos-fields">
      <summary>{t('inject.qos')}</summary>
      <label>
        {t('inject.reliability')}
        <select value={form.reliability} onChange={(e) => onChange({ reliability: e.target.value as InjectForm['reliability'] })}>
          <option value="reliable">RELIABLE</option>
          <option value="best_effort">BEST_EFFORT</option>
        </select>
      </label>
      <label>
        {t('inject.durability')}
        <select value={form.durability} onChange={(e) => onChange({ durability: e.target.value as InjectForm['durability'] })}>
          <option value="volatile">VOLATILE</option>
          <option value="transient_local">TRANSIENT_LOCAL</option>
        </select>
      </label>
      <label>
        {t('inject.depth')}
        <input type="number" min="1" max="1000" value={form.depth} onChange={(e) => onChange({ depth: e.target.value })} />
      </label>
    </details>
  );
}
