// 「これが来るはず」: choose which fields of the clicked message the expectation checks.

import { useState } from 'react';
import type { Condition } from '../api/scenarioTypes';
import { t, tDynamic } from '../i18n';
import { displayValue, parseLike } from './editSteps';
import { conditionsFrom, type FieldChoice, withinFor } from './record';

export function FieldPicker({ choices, response, onAdd, onCancel }: {
  choices: FieldChoice[];
  /** Seconds from the operation before the message to the message. */
  response: number;
  onAdd: (where: Condition[], within: number) => void;
  onCancel: () => void;
}) {
  const [items, setItems] = useState(choices);
  const [within, setWithin] = useState(withinFor(response));
  const update = (index: number, patch: Partial<FieldChoice>) =>
    setItems((cur) => cur.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  return (
    <div className="scn-picker" data-testid="scn-picker">
      <p className="small">{t('scn.pick.intro')}</p>
      <ul className="scn-pick-list">
        {items.map((c, i) => (
          <li key={c.path}>
            <label className="check">
              <input type="checkbox" checked={c.checked} onChange={() => update(i, { checked: !c.checked })} data-testid={`scn-pick-${c.path}`} />
              <span className="mono">{c.path}</span>
            </label>
            <span className="muted small">{tDynamic(`scn.op.${c.op}`, 'scn.op.eq')}</span>
            <input className="mono" value={displayValue(c.value)} aria-label={t('scn.edit.value')} data-testid={`scn-pick-value-${c.path}`}
              onChange={(e) => update(i, { value: parseLike(e.target.value, c.value) })} />
            {c.reason && <span className="muted small">{tDynamic(`scn.pick.reason.${c.reason}`, 'scn.pick.reason.volatile')}</span>}
          </li>
        ))}
        {items.length === 0 && <li className="muted small">{t('scn.pick.noFields')}</li>}
      </ul>
      <label className="scn-field">
        {t('scn.field.within')}
        <input className="num" value={within} onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n) && n > 0) setWithin(n);
        }} data-testid="scn-pick-within" />
      </label>
      <p className="muted small">{t('scn.pick.withinHelp', { ms: Math.round(Math.max(response, 0) * 1000) })}</p>
      <div className="row end">
        <button type="button" onClick={onCancel}>{t('common.cancel')}</button>
        <button type="button" className="primary" onClick={() => onAdd(conditionsFrom(items), within)} data-testid="scn-pick-add" data-tour="scn-pick-add">{t('scn.pick.add')}</button>
      </div>
    </div>
  );
}
