// One parameter: value (editable when allowed), type, description and constraints.

import { useState } from 'react';
import { describeError } from '../api/client';
import type { ParamInfo } from '../api/nodeTypes';
import { t, type MessageKey } from '../i18n';
import { editState, paramText, parseParamInput } from './paramValue';

interface Props {
  param: ParamInfo;
  external: boolean;
  unlocked: boolean;
  onSave: (param: ParamInfo, value: ParamInfo['value']) => Promise<void>;
}

export function ParamRow({ param, external, unlocked, onSave }: Props) {
  const [text, setText] = useState(paramText(param.value, param.type));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const state = editState(param, external, unlocked);
  const changed = text !== paramText(param.value, param.type);

  const submit = async () => {
    const parsed = parseParamInput(text, param.type);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSave(param, parsed.value);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr data-param={param.name}>
      <td className="mono">
        {param.name}
        {param.description && <div className="muted small">{param.description}</div>}
        {param.range && <div className="muted small">{t('params.range', { min: param.range.min, max: param.range.max })}</div>}
      </td>
      <td className="small">{t(`params.typeName.${param.type}` as MessageKey)}</td>
      <td>
        {state === 'editable' ? (
          <form className="row" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} aria-label={param.name} data-testid={`param-input-${param.name}`} />
            <button type="submit" disabled={busy || !changed} data-testid={`param-set-${param.name}`}>{t('params.set')}</button>
          </form>
        ) : (
          <span className="mono" data-testid={`param-value-${param.name}`} title={t(`params.state.${state}` as MessageKey)}>
            {paramText(param.value, param.type) || '—'}
            {state !== 'locked' && <span className="muted small"> ({t(`params.state.${state}` as MessageKey)})</span>}
          </span>
        )}
        {error && <div className="error-text small" role="alert">{error}</div>}
      </td>
    </tr>
  );
}
