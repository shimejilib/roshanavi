// Inputs (arguments) and output (return value) of the function-node dialog, with data kinds.

import type { FunctionInfo } from '../api/functionTypes';
import { DataKindField } from '../datakind/DataKindField';
import type { PortValue } from '../datakind/kinds';
import { t } from '../i18n';
import { normalizeTopic } from '../input/inputForm';
import { Term } from '../lib/Term';
import { MAX_FUNCTION_INPUTS, type FnPortRow, type FunctionForm } from './functionForm';

interface Props {
  form: FunctionForm;
  info: FunctionInfo | undefined;
  topicTypes: ReadonlyMap<string, string[]>;
  onChange: (form: FunctionForm) => void;
}

function PortRow({ row, testId, label, topicTypes, onChange }: { row: FnPortRow; testId: string; label: string; topicTypes: ReadonlyMap<string, string[]>; onChange: (row: FnPortRow) => void }) {
  return (
    <div className="function-port-row">
      <label>
        <span>{label}</span>
        <input list="function-topics" value={row.topic} placeholder="/topic" onChange={(e) => onChange({ ...row, topic: e.target.value })} data-testid={`${testId}-topic`} />
      </label>
      <DataKindField testId={`${testId}-type`} label={t('kind.label')} topicTypes={topicTypes.get(normalizeTopic(row.topic)) ?? []}
        value={{ kind: row.kind, type: row.type }} onChange={(port: PortValue) => onChange({ ...row, kind: port.kind, type: port.type })} />
    </div>
  );
}

export function FunctionPortsFields({ form, info, topicTypes, onChange }: Props) {
  const setInput = (index: number, row: FnPortRow) => onChange({ ...form, inputs: form.inputs.map((r, i) => (i === index ? row : r)) });
  const argName = (index: number) => info?.params[index]?.name ?? `#${index + 1}`;
  return (
    <>
      <datalist id="function-topics">
        {[...topicTypes.keys()].map((name) => <option key={name} value={name} />)}
      </datalist>
      {form.call !== 'periodic' && (
        <fieldset className="function-ports">
          <legend>{t('function.inputs')} <Term term="topic" /></legend>
          {form.inputs.map((row, index) => (
            <div key={index} className="function-input">
              <PortRow row={row} testId={`function-input-${index}`} label={t('function.inputArg', { name: argName(index) })} topicTypes={topicTypes} onChange={(r) => setInput(index, r)} />
              {form.call === 'multi_input' && form.inputs.length > 2 && (
                <button type="button" onClick={() => onChange({ ...form, inputs: form.inputs.filter((_, i) => i !== index) })}>{t('function.removeInput')}</button>
              )}
            </div>
          ))}
          {form.call === 'multi_input' && form.inputs.length < MAX_FUNCTION_INPUTS && (
            <button type="button" onClick={() => onChange({ ...form, inputs: [...form.inputs, { topic: '', kind: '', type: '' }] })}>{t('function.addInput')}</button>
          )}
          {form.call === 'multi_input' && (
            <label>
              {t('function.trigger')}
              <select value={form.trigger} onChange={(e) => onChange({ ...form, trigger: e.target.value })} data-testid="function-trigger">
                <option value="any">{t('function.trigger.any')}</option>
                {form.inputs.filter((r) => r.topic).map((r) => (
                  <option key={r.topic} value={normalizeTopic(r.topic)}>{t('function.trigger.one', { topic: normalizeTopic(r.topic) })}</option>
                ))}
              </select>
            </label>
          )}
        </fieldset>
      )}
      <fieldset className="function-ports">
        <legend>{t('function.output')}</legend>
        <PortRow row={form.output} testId="function-output" label={t('function.outputTopic')} topicTypes={topicTypes} onChange={(output) => onChange({ ...form, output })} />
        <span className="muted small">{t('function.noneHelp')}</span>
      </fieldset>
    </>
  );
}
