// Step 2 of the import: nodes to be created, parts that cannot be decomposed, and the mode.

import type { ImportEntity, ImportPlan } from '../api/nodeListTypes';
import { t } from '../i18n';
import { nodeFacts, nodeTitle, problemText, reasonText, warningText, type ImportMode } from './importModel';

interface Props {
  plan: ImportPlan;
  mode: ImportMode;
  onMode: (mode: ImportMode) => void;
  selection: ReadonlySet<number>;
  onToggle: (index: number) => void;
  role: 'mine' | 'dependency';
  onRole: (role: 'mine' | 'dependency') => void;
}

function EntityList({ title, items, testId }: { title: string; items: ImportEntity[]; testId: string }) {
  if (items.length === 0) return null;
  return (
    <section data-testid={testId}>
      <h4>{title}</h4>
      <ul className="import-entities">
        {items.map((item, i) => (
          <li key={i}>
            <span className="mono small">{item.detail || item.kind}</span>
            <div className="small">{reasonText(item.code)}</div>
            {item.composable_nodes && item.composable_nodes.length > 0 && (
              <div className="muted small">{t('import.composableNodes', { list: item.composable_nodes.join(', ') })}</div>
            )}
            {item.message && <div className="muted small mono">{item.message}</div>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function NodeList({ plan, selection, onToggle, disabled }: Pick<Props, 'plan' | 'selection' | 'onToggle'> & { disabled: boolean }) {
  return (
    <ul className="import-nodes" data-testid="import-nodes">
      {plan.nodes.map((node) => {
        const problem = problemText(node);
        return (
          <li key={node.index} className={node.importable ? '' : 'not-importable'} data-testid={`import-node-${node.index}`}>
            <label className="check">
              <input type="checkbox" checked={selection.has(node.index)} disabled={disabled || !node.importable} onChange={() => onToggle(node.index)} />
              <span className="mono">{nodeTitle(node)}</span>
              <span className="muted small">→ {t('import.targetId', { id: node.spec.id })}</span>
            </label>
            <div className="muted small">{nodeFacts(node).join(' · ')}</div>
            {node.warnings.map((w, i) => <div key={i} className="small warn-text">{warningText(w.code)}{w.detail ? ` (${w.detail})` : ''}</div>)}
            {problem && <div className="small error-text">{problem}</div>}
          </li>
        );
      })}
      {plan.nodes.length === 0 && <li className="muted">{t('import.noNodes')}</li>}
    </ul>
  );
}

export function ImportPreview({ plan, mode, onMode, selection, onToggle, role, onRole }: Props) {
  return (
    <div className="import-preview" data-testid="import-preview">
      <p className="small">{t('import.previewOf', { file: plan.origin, n: plan.nodes.length })}</p>
      <div role="radiogroup" aria-label={t('import.mode')} className="row wrap">
        <label className="radio">
          <input type="radio" checked={mode === 'nodes'} onChange={() => onMode('nodes')} data-testid="import-mode-nodes" />
          {t('import.mode.nodes', { n: plan.nodes.filter((n) => n.importable).length })}
        </label>
        <label className="radio" title={plan.whole ? undefined : reasonText(plan.whole_reason ?? 'not_in_package')}>
          <input type="radio" checked={mode === 'whole'} disabled={!plan.whole} onChange={() => onMode('whole')} data-testid="import-mode-whole" />
          {t('import.mode.whole')}
        </label>
        <label>
          {t('import.role')}
          <select value={role} onChange={(e) => onRole(e.target.value as 'mine' | 'dependency')} data-testid="import-role">
            <option value="dependency">{t('detail.role.dependency')}</option>
            <option value="mine">{t('detail.role.mine')}</option>
          </select>
        </label>
      </div>
      {mode === 'whole' && <p className="notice-box small">{t('import.wholeNote')}</p>}
      <NodeList plan={plan} selection={selection} onToggle={onToggle} disabled={mode === 'whole'} />
      {mode === 'nodes' && plan.blocked.length > 0 && <p className="notice-box small">{t('import.blockedNote', { n: plan.blocked.length })}</p>}
      <EntityList title={t('import.blocked')} items={plan.blocked} testId="import-blocked" />
      <EntityList title={t('import.skipped')} items={plan.skipped} testId="import-skipped" />
      {plan.warnings.length > 0 && (
        <ul className="small warn-text">{plan.warnings.map((w, i) => <li key={i}>{warningText(w.code)}</li>)}</ul>
      )}
      <p className="muted small">{t('import.afterNote')}</p>
    </div>
  );
}
