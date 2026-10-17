// Class mode of the "＋ 関数・クラスノードを作る" dialog: __init__ arguments (start values of the
// ROS parameters) and what each method does (unused / bound to topics / action button).

import type { ClassInfo, ClassMethodInfo } from '../api/classTypes';
import type { CallMode } from '../api/functionTypes';
import { t, tDynamic, type MessageKey } from '../i18n';
import { Term } from '../lib/Term';
import { MAX_OUTPUT_ROWS, parameterArgs, setDict, setMethodCall, setMethodUse, updateMethod, type ClassForm, type MethodForm, type MethodUse, type OutputRow } from './classForm';
import { InputRows, PortRow, TopicDatalist } from './FunctionPortsFields';

const CALLS: CallMode[] = ['on_message', 'periodic', 'multi_input'];
const DATALIST = 'class-topics';

interface Props {
  form: ClassForm;
  info: ClassInfo;
  topicTypes: ReadonlyMap<string, string[]>;
  onChange: (form: ClassForm) => void;
}

function ParamsFields({ form, info, onChange }: Props) {
  const args = parameterArgs(info);
  const skipped = info.init_params.filter((p) => p.kind === null);
  return (
    <fieldset className="class-params" data-testid="class-params">
      <legend>{t('class.params')} <Term term="parameter" /></legend>
      <p className="muted small">{t('class.paramsHelp')}</p>
      {args.length === 0 && <p className="muted small">{t('class.noParams')}</p>}
      {args.map((p) => (
        <label key={p.name}>
          <span>
            <code className="mono">{p.name}</code>
            {p.annotation && <span className="muted small"> : {p.annotation}</span>}
            <span className="muted small"> ({tDynamic(`class.paramKind.${p.kind ?? 'string'}`, 'class.paramKind.string')})</span>
            {!p.has_default && <span className="badge"> {t('class.required')}</span>}
          </span>
          <input className="mono" value={form.params[p.name] ?? ''} placeholder={p.has_default ? (p.default_text ?? '') : ''}
            onChange={(e) => onChange({ ...form, params: { ...form.params, [p.name]: e.target.value } })} data-testid={`class-param-${p.name}`} />
        </label>
      ))}
      {skipped.length > 0 && <p className="muted small">{t('class.paramsSkipped', { names: skipped.map((p) => p.name).join(', ') })}</p>}
      <p className="muted small">{info.hooks.on_param_change ? t('class.paramChange.hook') : t('class.paramChange.recreate')}</p>
    </fieldset>
  );
}

function OutputRows({ m, node, topicTypes, onChange }: { m: MethodForm; node: string; topicTypes: ReadonlyMap<string, string[]>; onChange: (m: MethodForm) => void }) {
  const set = (index: number, row: OutputRow) => onChange({ ...m, outputs: m.outputs.map((r, i) => (i === index ? row : r)) });
  const id = `class-method-${m.method}-output`;
  return (
    <fieldset className="function-ports">
      <legend>{t('class.outputs')}</legend>
      <label className="check">
        <input type="checkbox" checked={m.dict} onChange={(e) => onChange(setDict(m, e.target.checked, node))} data-testid={`${id}-dict`} />
        {t('class.dict')}
      </label>
      {m.outputs.map((row, index) => (
        <div key={index} className="class-output-row">
          {m.dict && (
            <label>
              <span>{t('class.dictKey')}</span>
              <input className="mono" value={row.key} placeholder="mean" onChange={(e) => set(index, { ...row, key: e.target.value })} data-testid={`${id}-${index}-key`} />
            </label>
          )}
          <PortRow row={row} testId={`${id}-${index}`} label={t('function.outputTopic')} topicTypes={topicTypes} datalist={DATALIST}
            onChange={(r) => set(index, { ...r, key: row.key })} />
          {m.dict && m.outputs.length > 1 && (
            <button type="button" onClick={() => onChange({ ...m, outputs: m.outputs.filter((_, i) => i !== index) })}>{t('function.removeInput')}</button>
          )}
        </div>
      ))}
      {m.dict && m.outputs.length < MAX_OUTPUT_ROWS && (
        <button type="button" onClick={() => onChange({ ...m, outputs: [...m.outputs, { topic: '', kind: '', type: '', key: '' }] })} data-testid={`${id}-add`}>{t('class.addOutput')}</button>
      )}
      <span className="muted small">{m.dict ? t('class.dictHelp') : t('class.outputOptional')}</span>
    </fieldset>
  );
}

function BoundMethod({ m, info, node, topicTypes, onChange }: { m: MethodForm; info: ClassMethodInfo; node: string; topicTypes: ReadonlyMap<string, string[]>; onChange: (m: MethodForm) => void }) {
  const id = `class-method-${m.method}`;
  const argName = (index: number) => info.params[index]?.name ?? `#${index + 1}`;
  return (
    <div className="class-method-body">
      <div className="row wrap">
        {CALLS.map((call) => (
          <label key={call} className="check">
            <input type="radio" name={`${id}-call`} checked={m.call === call} onChange={() => onChange(setMethodCall(m, call, info.params.length))} data-testid={`${id}-call-${call}`} />
            {t(`function.call.${call}` as MessageKey)}
          </label>
        ))}
      </div>
      {m.call === 'periodic' && (
        <label>
          {t('function.rate')}
          <input value={m.rateHz} inputMode="decimal" onChange={(e) => onChange({ ...m, rateHz: e.target.value })} data-testid={`${id}-rate`} />
        </label>
      )}
      {m.call !== 'periodic' && (
        <fieldset className="function-ports">
          <legend>{t('function.inputs')} <Term term="topic" /></legend>
          <InputRows call={m.call} inputs={m.inputs} trigger={m.trigger} argName={argName} idPrefix={`${id}-input`} triggerTestId={`${id}-trigger`} datalist={DATALIST}
            topicTypes={topicTypes} onChange={(inputs, trigger) => onChange({ ...m, inputs, trigger })} />
        </fieldset>
      )}
      <OutputRows m={m} node={node} topicTypes={topicTypes} onChange={onChange} />
    </div>
  );
}

function MethodRow({ m, info, classInfo, form, topicTypes, onChange }: { m: MethodForm; info: ClassMethodInfo; classInfo: ClassInfo; form: ClassForm; topicTypes: ReadonlyMap<string, string[]>; onChange: (form: ClassForm) => void }) {
  const id = `class-method-${m.method}`;
  const uses: MethodUse[] = info.action_candidate ? ['none', 'topic', 'action'] : ['none', 'topic'];
  return (
    <li className="class-method" data-testid={id} data-use={m.use}>
      <div className="row wrap">
        <code className="mono">{info.signature}</code>
        {info.doc && <span className="muted small"> — {info.doc}</span>}
      </div>
      <div className="row wrap">
        {uses.map((use) => (
          <label key={use} className="check">
            <input type="radio" name={`${id}-use`} checked={m.use === use} onChange={() => onChange(setMethodUse(form, m.method, use, classInfo))} data-testid={`${id}-use-${use}`} />
            {t(`class.use.${use}` as MessageKey)}
          </label>
        ))}
      </div>
      {m.use === 'action' && <p className="muted small">{t('class.actionHelp', { method: m.method })}</p>}
      {m.use === 'topic' && (
        <BoundMethod m={m} info={info} node={form.name} topicTypes={topicTypes} onChange={(next) => onChange(updateMethod(form, m.method, next))} />
      )}
    </li>
  );
}

export function ClassNodeFields({ form, info, topicTypes, onChange }: Props) {
  return (
    <>
      <TopicDatalist id={DATALIST} topicTypes={topicTypes} />
      {info.doc && <p className="muted small">{info.doc}</p>}
      <ParamsFields form={form} info={info} topicTypes={topicTypes} onChange={onChange} />
      <fieldset className="class-methods" data-testid="class-methods">
        <legend>{t('class.methods')}</legend>
        <p className="muted small">{t('class.methodsHelp')}</p>
        {info.methods.length === 0 && <p className="muted small">{t('class.noMethods')}</p>}
        <ul className="plain-list">
          {form.methods.map((m) => {
            const methodInfo = info.methods.find((x) => x.name === m.method);
            return methodInfo ? <MethodRow key={m.method} m={m} info={methodInfo} classInfo={info} form={form} topicTypes={topicTypes} onChange={onChange} /> : null;
          })}
        </ul>
        <p className="muted small">{t('class.single')}</p>
      </fieldset>
    </>
  );
}
