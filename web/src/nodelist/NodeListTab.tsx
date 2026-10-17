// ノード一覧 tab: every node (running or registered), bulk ON / OFF with checkboxes (DESIGN §6.6).

import { useEffect, useMemo, useState } from 'react';
import { t } from '../i18n';
import { ConfirmDialog } from '../lib/ConfirmDialog';
import { useAppState } from '../state/AppState';
import { allState, DEFAULT_FILTER, externalCount, filterRows, pruneSelection, sectionRows, toggleAll, toggleGroup, toggleKey, type RowFilter } from './model';
import { NodeListToolbar } from './NodeListToolbar';
import { NodeTable } from './NodeTable';
import { useBulkAction } from './useBulkAction';
import { useNodeList } from './useNodeList';

export function NodeListTab({ active }: { active: boolean }) {
  const { openDialog } = useAppState();
  const { data, error, reload } = useNodeList(active);
  const [filter, setFilter] = useState<RowFilter>(DEFAULT_FILTER);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const bulk = useBulkAction(reload);
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const visible = useMemo(() => filterRows(rows, filter), [rows, filter]);
  const sections = useMemo(() => sectionRows(visible, data?.groups ?? []), [visible, data]);
  useEffect(() => setSelected((prev) => pruneSelection(prev, rows)), [rows]);
  const chosen = rows.filter((r) => selected.has(r.key));
  const externals = externalCount(rows);
  const openImport = () => openDialog({ kind: 'launchImport' });

  return (
    <div className="node-list-tab">
      <NodeListToolbar
        filter={filter}
        onFilter={setFilter}
        selectedCount={chosen.length}
        busy={bulk.busy}
        onAction={(action) => bulk.request(action, chosen)}
        onClear={() => setSelected(new Set())}
        onImport={openImport}
      />
      <p className="muted small node-list-intro">{t('nodes.intro')}</p>
      {externals > 0 && (
        <div className="notice-box node-list-hint" data-testid="nodes-import-hint">
          {t('nodes.importHint', { n: externals })}{' '}
          <button type="button" className="link" onClick={openImport}>{t('nodes.importOpen')}</button>
        </div>
      )}
      {error && <p className="error-box" role="alert">{error}</p>}
      {bulk.message && (
        <p className={bulk.message.kind === 'ok' ? 'ok-box' : 'error-box'} role="status" data-testid="nodes-bulk-message">
          {bulk.message.text}
        </p>
      )}
      <div className="table-wrap">
        {!data && !error && <p className="muted">{t('common.loading')}</p>}
        {data && visible.length === 0 && <p className="muted">{t('nodes.empty')}</p>}
        {visible.length > 0 && (
          <NodeTable
            sections={sections}
            selected={selected}
            all={allState(visible, selected)}
            onToggle={(key) => setSelected((prev) => toggleKey(prev, key))}
            onToggleAll={() => setSelected((prev) => toggleAll(visible, prev))}
            onToggleGroup={(id) => setSelected((prev) => toggleGroup(visible, id, prev))}
            onLifecycle={(node) => openDialog({ kind: 'lifecycle', nodeId: node })}
          />
        )}
      </div>
      {bulk.pending && (
        <ConfirmDialog
          title={t(`nodes.confirm.${bulk.pending.plan.action}`)}
          text={bulk.pending.text}
          okLabel={t(`nodes.confirmOk.${bulk.pending.plan.action}`)}
          onOk={bulk.confirm}
          onCancel={bulk.cancel}
        />
      )}
    </div>
  );
}
