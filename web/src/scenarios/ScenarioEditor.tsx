// Edit a scenario: steps as a form; the raw YAML only in 詳細設定モード.

import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { Condition, Op, ScenarioFile, ScenarioSpec, SchemaError, StepRaw } from '../api/scenarioTypes';
import { useAdvancedMode } from '../datakind/advancedMode';
import { t, tDynamic } from '../i18n';
import {
  conditions,
  displayValue,
  move,
  NUMBER_FIELDS,
  OPS,
  parseLike,
  parseNumber,
  parsePayload,
  payloadText,
  removeAt,
  setConditions,
  setField,
  stepBody,
  stepKind,
  TOPIC_FIELDS,
  updateCondition,
  WHERE_KINDS,
} from './editSteps';

function ConditionRow({ cond, onChange, onRemove, testId }: {
  cond: Condition;
  onChange: (patch: Partial<Condition>) => void;
  onRemove: () => void;
  testId: string;
}) {
  const ranged = cond.op === 'range' || cond.op === 'len_range';
  return (
    <div className="scn-cond" data-testid={testId}>
      <input className="mono" value={cond.field} aria-label={t('scn.edit.field')} onChange={(e) => onChange({ field: e.target.value })} />
      <select value={cond.op} aria-label={t('scn.edit.op')} onChange={(e) => onChange({ op: e.target.value as Op })}>
        {OPS.map((op) => <option key={op} value={op}>{tDynamic(`scn.op.${op}`, 'scn.op.eq')}</option>)}
      </select>
      {ranged ? (
        <>
          <input className="num" value={displayValue(cond.min)} placeholder="min" aria-label="min" onChange={(e) => onChange({ min: parseNumber(e.target.value) })} />
          <input className="num" value={displayValue(cond.max)} placeholder="max" aria-label="max" onChange={(e) => onChange({ max: parseNumber(e.target.value) })} />
        </>
      ) : cond.op !== 'exists' && (
        <input className="mono" value={displayValue(cond.value)} aria-label={t('scn.edit.value')} data-testid={`${testId}-value`}
          onChange={(e) => onChange({ value: parseLike(e.target.value, cond.value) })} />
      )}
      {cond.op === 'approx' && (
        <input className="num" value={displayValue(cond.tol)} placeholder="±" aria-label={t('scn.edit.tol')} onChange={(e) => onChange({ tol: parseNumber(e.target.value) })} />
      )}
      <button type="button" className="link" onClick={onRemove} aria-label={t('scn.edit.removeCond')}>✕</button>
    </div>
  );
}

function PayloadField({ step, onChange }: { step: StepRaw; onChange: (s: StepRaw) => void }) {
  const initial = payloadText(step);
  const [text, setText] = useState(initial.text);
  const [bad, setBad] = useState(false);
  return (
    <label className="scn-field wide">
      {initial.key === 'value' ? t('scn.edit.value') : t('scn.edit.data')}
      <input className={`mono${bad ? ' invalid' : ''}`} value={text} onChange={(e) => {
        setText(e.target.value);
        const parsed = parsePayload(initial.key, e.target.value);
        setBad(!parsed.ok);
        if (parsed.ok) onChange(setField(step, initial.key, parsed.value));
      }} />
    </label>
  );
}

function StepForm({ step, index, count, onChange, onMove, onRemove }: {
  step: StepRaw;
  index: number;
  count: number;
  onChange: (s: StepRaw) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  const kind = stepKind(step);
  const body = stepBody(step);
  const where = conditions(step);
  return (
    <li className="scn-edit-step" data-testid={`scn-edit-step-${index}`}>
      <div className="scn-edit-head">
        <span className="scn-step-label">{index + 1}</span>
        <strong>{tDynamic(`scn.kind.${kind}`, 'scn.kind.wait')}</strong>
        <span className="spacer" />
        <button type="button" className="link" disabled={index === 0} onClick={() => onMove(-1)} aria-label={t('scn.edit.up')}>↑</button>
        <button type="button" className="link" disabled={index === count - 1} onClick={() => onMove(1)} aria-label={t('scn.edit.down')}>↓</button>
        <button type="button" className="link danger-text" onClick={onRemove} aria-label={t('scn.edit.removeStep')}>✕</button>
      </div>
      <div className="scn-edit-fields">
        {(TOPIC_FIELDS[kind] ?? []).map((key) => (
          <label key={key} className="scn-field wide">
            {tDynamic(`scn.field.${key}`, 'scn.field.topic')}
            <input className="mono" value={displayValue(body[key])} onChange={(e) => onChange(setField(step, key, e.target.value))} />
          </label>
        ))}
        {kind === 'wait' && (
          <label className="scn-field">
            {t('scn.field.seconds')}
            <input className="num" value={displayValue(body.seconds)} onChange={(e) => onChange(setField(step, 'seconds', parseNumber(e.target.value) ?? e.target.value))} />
          </label>
        )}
        {(NUMBER_FIELDS[kind] ?? []).map((key) => (
          <label key={key} className="scn-field">
            {tDynamic(`scn.field.${key}`, 'scn.field.for')}
            <input className="num" value={displayValue(body[key])} data-testid={`scn-edit-${index}-${key}`}
              onChange={(e) => onChange(setField(step, key, parseNumber(e.target.value)))} />
          </label>
        ))}
        {kind === 'latency' && (
          <label className="scn-field">
            {t('scn.field.match')}
            <select value={String(body.match ?? 'header.stamp')} onChange={(e) => onChange(setField(step, 'match', e.target.value))}>
              <option value="header.stamp">{t('scn.match.stamp')}</option>
              <option value="order">{t('scn.match.order')}</option>
            </select>
          </label>
        )}
        {kind === 'send' && <PayloadField step={step} onChange={onChange} />}
        {['start', 'stop', 'play'].includes(kind) && (
          <p className="muted small mono scn-raw-body">{JSON.stringify(body)}</p>
        )}
      </div>
      {WHERE_KINDS.includes(kind) && (
        <div className="scn-where">
          <span className="muted small">{t('scn.edit.where')}</span>
          {where.map((cond, i) => (
            <ConditionRow key={i} cond={cond} testId={`scn-cond-${index}-${i}`}
              onChange={(patch) => onChange(updateCondition(step, i, patch))}
              onRemove={() => onChange(setConditions(step, removeAt(where, i)))} />
          ))}
          <button type="button" className="link" onClick={() => onChange(setConditions(step, [...where, { field: 'data', op: 'exists' }]))}>
            {t('scn.edit.addCond')}
          </button>
        </div>
      )}
    </li>
  );
}

function ErrorList({ errors, message }: { errors: SchemaError[]; message?: string }) {
  if (!errors.length && !message) return null;
  return (
    <div className="error-box" role="alert" data-testid="scn-edit-errors">
      {errors.length
        ? errors.map((e, i) => <div key={i}>{e.line ? t('scn.errorLine', { path: e.path || '-', line: e.line, message: e.message }) : `${e.path}: ${e.message}`}</div>)
        : message}
    </div>
  );
}

export function ScenarioEditor({ file, onSaved, onClose }: {
  file: ScenarioFile;
  onSaved: (saved: ScenarioFile) => void;
  onClose: () => void;
}) {
  const [advanced] = useAdvancedMode();
  const [spec, setSpec] = useState<ScenarioSpec | null>(file.spec);
  const [yaml, setYaml] = useState(file.yaml);
  const [mode, setMode] = useState<'form' | 'yaml'>(file.spec ? 'form' : 'yaml');
  const [errors, setErrors] = useState<SchemaError[]>(file.errors);
  const [message, setMessage] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setMessage(undefined);
    try {
      const body = mode === 'yaml' || !spec ? { yaml } : { spec };
      const check = await api.validateScenario(body);
      if (!check.ok) {
        setErrors(check.errors);
        setMessage(check.message);
        return;
      }
      const saved = file.read_only
        ? await api.createScenario(check.spec as ScenarioSpec, file.file)
        : await api.saveScenario(file.id, body);
      setErrors([]);
      onSaved(saved);
    } catch (err) {
      setMessage(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const switchToYaml = async () => {
    if (spec) {
      try {
        const check = await api.validateScenario({ spec });
        if (check.ok && check.yaml) setYaml(check.yaml);
      } catch (err) {
        setMessage(describeError(err));
      }
    }
    setMode('yaml');
  };

  const steps = spec?.steps ?? [];
  const setSteps = (next: StepRaw[]) => spec && setSpec({ ...spec, steps: next });
  return (
    <section className="scn-editor" aria-labelledby="scn-edit-title" data-testid="scn-editor">
      <header className="scn-editor-head">
        <h3 id="scn-edit-title">{t('scn.edit.title', { name: file.name })}</h3>
        {file.read_only && <p className="muted small">{t('scn.edit.copyNote')}</p>}
        {advanced && (
          <div className="row">
            <button type="button" className={mode === 'form' ? 'primary' : ''} disabled={!spec} onClick={() => setMode('form')}>{t('scn.edit.form')}</button>
            <button type="button" className={mode === 'yaml' ? 'primary' : ''} onClick={() => void switchToYaml()} data-testid="scn-edit-yaml-mode">{t('scn.edit.yaml')}</button>
          </div>
        )}
      </header>
      {mode === 'form' && spec ? (
        <>
          <label className="scn-field wide">
            {t('scn.edit.name')}
            <input value={spec.name} onChange={(e) => setSpec({ ...spec, name: e.target.value })} data-testid="scn-edit-name" />
          </label>
          <label className="scn-field wide">
            {t('scn.edit.description')}
            <input value={spec.description ?? ''} onChange={(e) => setSpec({ ...spec, description: e.target.value || undefined })} />
          </label>
          {(spec.setup?.length ?? 0) + (spec.guards?.length ?? 0) > 0 && (
            <p className="muted small">{t('scn.edit.setupNote', { setup: spec.setup?.length ?? 0, guards: spec.guards?.length ?? 0 })}</p>
          )}
          <ol className="scn-edit-steps">
            {steps.map((step, i) => (
              <StepForm key={`${i}-${stepKind(step)}`} step={step} index={i} count={steps.length}
                onChange={(next) => setSteps(steps.map((s, j) => (j === i ? next : s)))}
                onMove={(delta) => setSteps(move(steps, i, delta))}
                onRemove={() => setSteps(removeAt(steps, i))} />
            ))}
          </ol>
          <div className="row">
            <button type="button" onClick={() => setSteps([...steps, { wait: 1 }])}>{t('scn.edit.addWait')}</button>
            <button type="button" onClick={() => setSteps([...steps, { expect: { topic: '/', within: 1 } }])}>{t('scn.edit.addExpect')}</button>
          </div>
        </>
      ) : (
        <label className="scn-field wide">
          {t('scn.edit.yamlLabel')}
          <textarea className="mono scn-yaml" value={yaml} rows={24} spellCheck={false} onChange={(e) => setYaml(e.target.value)} data-testid="scn-edit-yaml" />
        </label>
      )}
      <ErrorList errors={errors} message={message} />
      <div className="row end">
        <button type="button" onClick={onClose}>{t('common.cancel')}</button>
        <button type="button" className="primary" disabled={busy} onClick={() => void save()} data-testid="scn-edit-save">
          {file.read_only ? t('scn.edit.saveCopy') : t('scn.edit.save')}
        </button>
      </div>
    </section>
  );
}
