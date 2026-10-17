// Delay / throttle / drop settings of the transform editor ("意地悪テスト").

import { t } from '../i18n';
import type { TransformForm } from './transformForm';

interface Props {
  form: TransformForm;
  onChange: (patch: Partial<TransformForm>) => void;
}

export function TransformTimingFields({ form, onChange }: Props) {
  return (
    <fieldset className="transform-timing">
      <legend>{t('transform.timing')}</legend>
      <div className="row wrap">
        <label>
          {t('transform.delay')} {t('transform.delayMin')}
          <input type="number" min={0} max={60000} value={form.delayMinMs} onChange={(e) => onChange({ delayMinMs: e.target.value })} data-testid="transform-delay-min" />
        </label>
        <label>
          {t('transform.delayMax')}
          <input type="number" min={0} max={60000} value={form.delayMaxMs} onChange={(e) => onChange({ delayMaxMs: e.target.value })} />
        </label>
        <label>
          {t('transform.throttle')}
          <input type="number" min={0} max={1000} step="any" value={form.throttleHz} onChange={(e) => onChange({ throttleHz: e.target.value })} data-testid="transform-throttle" />
        </label>
        <label>
          {t('transform.drop')}
          <input type="number" min={0} max={100} value={form.dropPercent} onChange={(e) => onChange({ dropPercent: e.target.value })} data-testid="transform-drop" />
        </label>
      </div>
    </fieldset>
  );
}
