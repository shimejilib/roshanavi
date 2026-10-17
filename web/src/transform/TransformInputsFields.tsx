// Input topics of the transform editor: topic + type + expression name per row, and the trigger.

import { t } from '../i18n';
import { DataKindField } from '../datakind/DataKindField';
import { Term } from '../lib/Term';
import { normalizeTopic } from '../input/inputForm';
import { MAX_INPUTS, withInputs, type InputRow, type TransformForm } from './transformForm';

interface Props {
  form: TransformForm;
  topicTypes: ReadonlyMap<string, string[]>;
  disabled: boolean;
  onChange: (form: TransformForm) => void;
}

export function TransformInputsFields({ form, topicTypes, disabled, onChange }: Props) {
  const setRow = (index: number, patch: Partial<InputRow>) => {
    const rows = form.inputs.map((row, i) => (i === index ? { ...row, ...patch } : row));
    onChange({ ...form, inputs: rows });
  };
  const setTopic = (index: number, topic: string) => setRow(index, { topic });
  const add = () => onChange(withInputs(form, [...form.inputs, { topic: '', type: '', alias: `msg${form.inputs.length + 1}` }]));
  const remove = (index: number) => onChange(withInputs(form, form.inputs.filter((_, i) => i !== index)));

  return (
    <fieldset className="transform-inputs">
      <legend>{t('transform.inputs')} <Term term="topic" /></legend>
      <datalist id="transform-topics">
        {[...topicTypes.keys()].map((name) => <option key={name} value={name} />)}
      </datalist>
      {form.inputs.map((row, index) => (
        <div className="transform-input-row" key={index}>
          <input list="transform-topics" value={row.topic} placeholder="/topic" aria-label={t('transform.inputTopic')}
            onChange={(e) => setTopic(index, e.target.value)} disabled={disabled} data-testid={`transform-input-topic-${index}`} />
          <DataKindField testId={`transform-input-type-${index}`} label={t('kind.label')} topicTypes={topicTypes.get(normalizeTopic(row.topic)) ?? []}
            value={{ kind: row.kind ?? '', type: row.type }} onChange={(port) => setRow(index, { kind: port.kind, type: port.type })} disabled={disabled} />
          <input className="alias" value={row.alias} aria-label={t('transform.alias')} title={t('transform.aliasHelp')}
            onChange={(e) => setRow(index, { alias: e.target.value })} disabled={disabled} />
          {form.inputs.length > 1 && (
            <button type="button" onClick={() => remove(index)} disabled={disabled}>{t('transform.removeInput')}</button>
          )}
        </div>
      ))}
      <span className="muted small">{t('transform.aliasHelp')}</span>
      {form.inputs.length < MAX_INPUTS && form.mode === 'map' && (
        <button type="button" onClick={add} disabled={disabled} data-testid="transform-add-input">{t('transform.addInput')}</button>
      )}
      {form.inputs.length > 1 && (
        <label>
          {t('transform.trigger')}
          <select value={form.trigger} onChange={(e) => onChange({ ...form, trigger: e.target.value })}>
            <option value="any">{t('transform.trigger.any')}</option>
            {form.inputs.map((row) => <option key={row.alias} value={row.alias}>{t('transform.trigger.one', { alias: row.alias })}</option>)}
          </select>
          <span className="muted small">{t('transform.joinHelp')}</span>
        </label>
      )}
    </fieldset>
  );
}
