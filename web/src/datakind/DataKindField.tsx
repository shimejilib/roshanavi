// "データの種類" picker (docs/design/nodes.md). A topic that already exists has its type fixed by the
// other side, so nothing is chosen: the detected type is shown as 「文字列 (std_msgs/String)」 or
// 「専用の型: geometry_msgs/Twist」. For a new topic the user picks a kind; ROS types are listed
// only in 詳細設定モード (common types -> workspace types -> others by package, with search).

import { useEffect, useMemo, useState } from 'react';
import { t } from '../i18n';
import { useAdvancedMode } from './advancedMode';
import { describeType, filterGroups, groupLabel, kindLabel, normalizeType, portFromKind, portFromType, type KindCatalog, type KindId, type PortKind, type PortValue } from './kinds';
import { useDataKinds, useTypeGroups } from './useDataKinds';

interface Props {
  testId: string;
  label: string;
  /** Types the topic has on the graph now; empty for a new topic. */
  topicTypes: readonly string[];
  value: PortValue;
  onChange: (value: PortValue) => void;
  disabled?: boolean;
  /** Kinds offered for a new topic (default: all). */
  kinds?: readonly KindId[];
}

/** For an existing topic: the port the detected type means (keeps a JSON choice on a String). */
export function detectedPort(topicTypes: readonly string[], value: PortValue, catalog: KindCatalog): PortValue | null {
  if (topicTypes.length === 0) return null;
  const normalized = topicTypes.map(normalizeType);
  const type = normalized.includes(normalizeType(value.type)) ? normalizeType(value.type) : (normalized[0] ?? '');
  const port = portFromType(type, catalog);
  if (value.kind === 'json' && port.kind === 'string') return { kind: 'json', type };
  return port;
}

function RawTypePicker({ testId, value, onChange, disabled }: Pick<Props, 'testId' | 'value' | 'onChange' | 'disabled'>) {
  const [query, setQuery] = useState('');
  const groups = useTypeGroups(true);
  const catalog = useDataKinds();
  const shown = useMemo(() => filterGroups(groups, query), [groups, query]);
  return (
    <div className="raw-type-picker" data-testid={`${testId}-raw`}>
      <span className="muted small">{t('kind.rawType')}</span>
      <div className="row">
        <input type="search" value={query} placeholder={t('kind.rawSearch')} aria-label={t('kind.rawSearch')}
          onChange={(e) => setQuery(e.target.value)} disabled={disabled} data-testid={`${testId}-raw-search`} />
        <select value={value.type ? normalizeType(value.type) : ''} disabled={disabled}
          onChange={(e) => onChange(e.target.value ? portFromType(e.target.value, catalog) : portFromKind('', catalog))}
          data-testid={`${testId}-raw-type`}>
          <option value="">{shown.length === 0 && query ? t('kind.rawNoMatch') : t('kind.rawNone')}</option>
          {shown.map((g) => (
            <optgroup key={`${g.id}:${g.package ?? ''}`} label={groupLabel(g)}>
              {g.types.map((type) => <option key={type} value={type}>{type}</option>)}
            </optgroup>
          ))}
        </select>
      </div>
    </div>
  );
}

export function DataKindField({ testId, label, topicTypes, value, onChange, disabled, kinds }: Props) {
  const catalog = useDataKinds();
  const [advanced] = useAdvancedMode();
  const detected = detectedPort(topicTypes, value, catalog);
  const typesKey = topicTypes.join(',');

  useEffect(() => {
    if (detected && (detected.kind !== value.kind || detected.type !== normalizeType(value.type))) onChange(detected);
    // A type without a kind (an existing node being edited): show it as its kind.
    else if (!detected && value.kind === '' && value.type && catalog.kinds.length > 0) onChange(portFromType(value.type, catalog));
    // Re-evaluate when the topic's types or the catalog change, not on every render.
  }, [typesKey, catalog, detected?.kind, detected?.type]);

  if (detected) {
    return (
      <div className="data-kind-field" data-testid={testId}>
        <span>{label}</span>
        {topicTypes.length > 1 ? (
          <>
            <span className="muted small">{t('kind.existingMany')}</span>
            <select value={detected.type} disabled={disabled} onChange={(e) => onChange(portFromType(e.target.value, catalog))} data-testid={`${testId}-existing`}>
              {topicTypes.map((type) => <option key={type} value={normalizeType(type)}>{describeType(type, catalog)}</option>)}
            </select>
          </>
        ) : (
          <p className="kind-detected" data-testid={`${testId}-detected`}>
            {t('kind.existing', { label: describeType(detected.type, catalog) })}
          </p>
        )}
        {detected.kind === 'message' && <span className="muted small">{t('kind.specialHelp')}</span>}
      </div>
    );
  }

  const offered = catalog.kinds.filter((k) => !kinds || kinds.includes(k.id));
  const pick = (kind: PortKind | '') => onChange(portFromKind(kind, catalog, value.type));
  return (
    <div className="data-kind-field" data-testid={testId}>
      <label>
        <span>{label}</span>
        <select value={value.kind} disabled={disabled} onChange={(e) => pick(e.target.value as PortKind | '')} data-testid={`${testId}-kind`} data-tour={`${testId}-kind`}>
          <option value="">{t('kind.choose')}</option>
          {offered.map((k) => (
            <option key={k.id} value={k.id} disabled={!k.available}>
              {kindLabel(k.id)}{k.available ? '' : ` ${t('kind.unavailable')}`}
            </option>
          ))}
          {(advanced || value.kind === 'message') && <option value="message">{kindLabel('message')}</option>}
        </select>
      </label>
      {advanced ? (
        <RawTypePicker testId={testId} value={value} onChange={onChange} disabled={disabled} />
      ) : (
        <span className="muted small">{value.kind === 'message' ? t('kind.special', { type: value.type }) : t('kind.advancedHint')}</span>
      )}
    </div>
  );
}
