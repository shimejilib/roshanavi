// Search, role / status filters and the bulk start / stop / restart buttons.

import type { ControlAction } from '../graph/nodeControl';
import { t } from '../i18n';
import type { RoleFilter, RowFilter, StatusFilter } from './model';

const ROLES: RoleFilter[] = ['all', 'mine', 'dependency', 'dummy', 'other'];
const STATUSES: StatusFilter[] = ['all', 'running', 'stopped', 'problem'];
const ACTIONS: ControlAction[] = ['start', 'stop', 'restart'];

interface Props {
  filter: RowFilter;
  onFilter: (filter: RowFilter) => void;
  selectedCount: number;
  busy: boolean;
  onAction: (action: ControlAction) => void;
  onClear: () => void;
  onImport: () => void;
}

export function NodeListToolbar({ filter, onFilter, selectedCount, busy, onAction, onClear, onImport }: Props) {
  return (
    <div className="toolbar" role="toolbar" aria-label={t('nodes.toolbar')}>
      <input
        type="search"
        placeholder={t('nodes.search')}
        aria-label={t('nodes.search')}
        value={filter.query}
        onChange={(e) => onFilter({ ...filter, query: e.target.value })}
        data-testid="nodes-search"
      />
      <label className="check">
        {t('nodes.filter.role')}
        <select value={filter.role} onChange={(e) => onFilter({ ...filter, role: e.target.value as RoleFilter })} data-testid="nodes-role">
          {ROLES.map((r) => <option key={r} value={r}>{t(`nodes.roleFilter.${r}`)}</option>)}
        </select>
      </label>
      <label className="check">
        {t('nodes.filter.status')}
        <select value={filter.status} onChange={(e) => onFilter({ ...filter, status: e.target.value as StatusFilter })} data-testid="nodes-status">
          {STATUSES.map((s) => <option key={s} value={s}>{t(`nodes.statusFilter.${s}`)}</option>)}
        </select>
      </label>
      <span className="muted small" role="status" data-testid="nodes-selected">{t('nodes.selected', { n: selectedCount })}</span>
      {ACTIONS.map((action) => (
        <button
          key={action}
          type="button"
          className={action === 'stop' ? 'danger' : undefined}
          disabled={selectedCount === 0 || busy}
          onClick={() => onAction(action)}
          data-testid={`nodes-bulk-${action}`}
        >
          {t(`nodes.action.${action}`)}
        </button>
      ))}
      <button type="button" disabled={selectedCount === 0} onClick={onClear}>{t('nodes.clear')}</button>
      <button type="button" className="primary push-right" onClick={onImport} data-testid="nodes-import">
        {t('nodes.importOpen')}
      </button>
    </div>
  );
}
