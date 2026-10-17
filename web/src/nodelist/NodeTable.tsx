// The node-list table: group headers, checkboxes, keyboard navigation (↑ / ↓ between rows).

import { useEffect, useRef, type KeyboardEvent } from 'react';
import type { NodeRow } from '../api/nodeListTypes';
import type { Target } from '../api/types';
import { t } from '../i18n';
import { statusClass } from '../launcher/status';
import type { AllState, RowSection } from './model';
import { confidenceText, disabledReason, groupTitle, lifecycleStateText, originText, roleText, statusText } from './rowText';

interface Props {
  sections: RowSection[];
  selected: ReadonlySet<string>;
  all: AllState;
  onToggle: (key: string) => void;
  onToggleAll: () => void;
  onToggleGroup: (groupId: string) => void;
  onLifecycle: (node: string) => void;
}

/** ↑ / ↓ move focus between the rows' focusable checkboxes and buttons (same column first). */
function moveFocus(e: KeyboardEvent<HTMLTableSectionElement>) {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
  const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[data-nav]:not(:disabled)'));
  const current = items.indexOf(document.activeElement as HTMLElement);
  const column = items[current]?.dataset.nav;
  if (current < 0 || column === undefined) return;
  const step = e.key === 'ArrowDown' ? 1 : -1;
  for (let i = current + step; i >= 0 && i < items.length; i += step) {
    const item = items[i];
    if (item?.dataset.nav === column) {
      e.preventDefault();
      item.focus();
      return;
    }
  }
}

function HeaderCheckbox({ all, onToggleAll }: Pick<Props, 'all' | 'onToggleAll'>) {
  const ref = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = all === 'some';
  }, [all]);
  return (
    <input ref={ref} type="checkbox" checked={all === 'all'} onChange={onToggleAll} aria-label={t('nodes.selectAll')} data-testid="nodes-select-all" />
  );
}

function RowView({ row, checked, onToggle, onLifecycle }: { row: NodeRow; checked: boolean } & Pick<Props, 'onToggle' | 'onLifecycle'>) {
  const reason = disabledReason(row);
  return (
    <tr className={row.running ? '' : 'row-stopped'} data-testid={`node-row-${row.key}`} data-status={row.status} data-control={row.control}>
      <td>
        <span title={reason ?? undefined}>
          <input
            type="checkbox"
            checked={checked}
            disabled={reason !== null}
            onChange={() => onToggle(row.key)}
            aria-label={t('nodes.selectRow', { name: row.name })}
            aria-describedby={reason ? `why-${row.key}` : undefined}
            data-nav="check"
            data-testid={`node-check-${row.key}`}
          />
        </span>
      </td>
      <th scope="row" className="mono">
        {row.name}
        {reason && <div id={`why-${row.key}`} className="muted small">{reason}</div>}
      </th>
      <td><span className={`badge role-${row.role === 'other' ? 'other' : row.role}`}>{roleText(row)}</span></td>
      <td>
        <span className={`status-chip ${row.target_id ? statusClass(row.status as Target['status']) : 'st-running'}`}>{statusText(row)}</span>
        {row.lifecycle && (
          <div className="lifecycle-cell">
            <span className={`badge lc-${row.lifecycle.state ?? 'unknown'}`} data-testid={`lc-state-${row.key}`}>{lifecycleStateText(row.lifecycle.state)}</span>
            {row.node && (
              <button type="button" className="link small" onClick={() => onLifecycle(row.node as string)} data-nav="lifecycle" data-testid={`lc-open-${row.key}`}>
                {t('lifecycle.open')}
              </button>
            )}
          </div>
        )}
      </td>
      <td className="small">{originText(row)}</td>
      <td className="mono small">{row.pid ?? '—'}</td>
      <td className="small">{confidenceText(row)}</td>
    </tr>
  );
}

export function NodeTable({ sections, selected, all, onToggle, onToggleAll, onToggleGroup, onLifecycle }: Props) {
  return (
    <table className="traffic-table node-table" data-testid="node-table">
      <caption className="sr-only">{t('nodes.caption')}</caption>
      <thead>
        <tr>
          <th scope="col"><HeaderCheckbox all={all} onToggleAll={onToggleAll} /></th>
          <th scope="col">{t('nodes.col.name')}</th>
          <th scope="col">{t('nodes.col.role')}</th>
          <th scope="col">{t('nodes.col.status')}</th>
          <th scope="col">{t('nodes.col.origin')}</th>
          <th scope="col">{t('nodes.col.pid')}</th>
          <th scope="col">{t('nodes.col.mapping')}</th>
        </tr>
      </thead>
      <tbody onKeyDown={moveFocus}>
        {sections.flatMap((section, i) => [
          ...(section.group
            ? [
                <tr key={`g-${section.group.id}`} className="group-row" data-testid={`node-group-${section.group.id}`}>
                  <td>
                    <input
                      type="checkbox"
                      checked={section.rows.every((r) => selected.has(r.key))}
                      onChange={() => onToggleGroup(section.group!.id)}
                      aria-label={t('nodes.selectGroup', { name: section.group.label })}
                      data-nav="check"
                    />
                  </td>
                  <td colSpan={6}>{groupTitle(section.group)}</td>
                </tr>,
              ]
            : []),
          ...section.rows.map((row) => (
            <RowView key={`${i}-${row.key}`} row={row} checked={selected.has(row.key)} onToggle={onToggle} onLifecycle={onLifecycle} />
          )),
        ])}
      </tbody>
    </table>
  );
}
