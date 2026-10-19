// Inputs (arguments) and output (return value) of the function-node dialog, with data kinds.

import type { FunctionInfo } from '../api/functionTypes';
import type { CallMode } from '../api/functionTypes';
import { DataKindField } from '../datakind/DataKindField';
import type { PortValue } from '../datakind/kinds';
import { t } from '../i18n';
import { normalizeTopic } from '../input/inputForm';
import { Term } from '../lib/Term';
import { EMPTY_ROW, MAX_FUNCTION_INPUTS, type FnPortRow, type FunctionForm } from './functionForm';

interface Props {
  form: FunctionForm;
  info: FunctionInfo | undefined;
  topicTypes: ReadonlyMap<string, string[]>;
  onChange: (form: FunctionForm) => void;
}

export function PortRow({ row, testId, label, topicTypes, datalist = 'function-topics', onChange }: {
  row: FnPortRow; testId: string; label: string; topicTypes: ReadonlyMap<string, string[]>; datalist?: string; onChange: (row: FnPortRow) => void;
}) {
  return (
    <div className="function-port-row">
      <label>
        <span>{label}</span>
        <input list={datalist} value={row.topic} placeholder="/topic" onChange={(e) => onChange({ ...row, topic: e.target.value })} data-testid={`${testId}-topic`} data-tour={`${testId}-topic`} />
      </label>
      <DataKindField testId={`${testId}-type`} label={t('kind.label')} topicTypes={topicTypes.get(normalizeTopic(row.topic)) ?? []}
        value={{ kind: row.kind, type: row.type }} onChange={(port: PortValue) => onChange({ ...row, kind: port.kind, type: port.type })} />
    </div>
  );
}

export function TopicDatalist({ id, topicTypes }: { id: string; topicTypes: ReadonlyMap<string, string[]> }) {
  return (
    <datalist id={id}>
      {[...topicTypes.keys()].map((name) => <option key={name} value={name} />)}
    </datalist>
  );
}

/** The input rows of a function (or of one bound method of a class): topics, kinds, trigger. */
export function InputRows({ call, inputs, trigger, argName, idPrefix, triggerTestId, datalist, topicTypes, onChange }: {
  call: CallMode;
  inputs: FnPortRow[];
  trigger: string;
  argName: (index: number) => string;
  idPrefix: string;
  triggerTestId: string;
  datalist?: string;
  topicTypes: ReadonlyMap<string, string[]>;
  onChange: (inputs: FnPortRow[], trigger: string) => void;
}) {
  if (call === 'periodic') return null;
  return (
    <>
      {inputs.map((row, index) => (
        <div key={index} className="function-input">
          <PortRow row={row} testId={`${idPrefix}-${index}`} label={t('function.inputArg', { name: argName(index) })} topicTypes={topicTypes} datalist={datalist}
            onChange={(r) => onChange(inputs.map((x, i) => (i === index ? r : x)), trigger)} />
          {call === 'multi_input' && inputs.length > 2 && (
            <button type="button" onClick={() => onChange(inputs.filter((_, i) => i !== index), trigger)}>{t('function.removeInput')}</button>
          )}
        </div>
      ))}
      {call === 'multi_input' && inputs.length < MAX_FUNCTION_INPUTS && (
        <button type="button" onClick={() => onChange([...inputs, { ...EMPTY_ROW }], trigger)}>{t('function.addInput')}</button>
      )}
      {call === 'multi_input' && (
        <label>
          {t('function.trigger')}
          <select value={trigger} onChange={(e) => onChange(inputs, e.target.value)} data-testid={triggerTestId}>
            <option value="any">{t('function.trigger.any')}</option>
            {inputs.filter((r) => r.topic).map((r) => (
              <option key={r.topic} value={normalizeTopic(r.topic)}>{t('function.trigger.one', { topic: normalizeTopic(r.topic) })}</option>
            ))}
          </select>
        </label>
      )}
    </>
  );
}

/** 「トピックは地図で線を引いてつなぐ」: empty every topic (ports that are wired on the map later). */
export function MapLaterButton({ onClick, testId }: { onClick: () => void; testId: string }) {
  return (
    <p className="row wrap small">
      <button type="button" className="small" onClick={onClick} data-testid={testId}>{t('wiring.form.mapLater')}</button>
      <span className="muted">{t('wiring.form.mapLaterHelp')}</span>
    </p>
  );
}

export function FunctionPortsFields({ form, info, topicTypes, onChange }: Props) {
  const argName = (index: number) => info?.params[index]?.name ?? `#${index + 1}`;
  const clearTopics = () => onChange({ ...form, inputs: form.inputs.map((r) => ({ ...r, topic: '', type: '' })), output: { ...form.output, topic: '', type: '' }, trigger: 'any' });
  return (
    <>
      <TopicDatalist id="function-topics" topicTypes={topicTypes} />
      <MapLaterButton onClick={clearTopics} testId="function-map-later" />
      {form.call !== 'periodic' && (
        <fieldset className="function-ports">
          <legend>{t('function.inputs')} <Term term="topic" /></legend>
          <InputRows call={form.call} inputs={form.inputs} trigger={form.trigger} argName={argName} idPrefix="function-input" triggerTestId="function-trigger"
            topicTypes={topicTypes} onChange={(inputs, trigger) => onChange({ ...form, inputs, trigger })} />
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
