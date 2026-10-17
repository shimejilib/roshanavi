import { useMemo, useState } from 'react';
import type { Diagnostic } from '../api/types';
import { t } from '../i18n';
import { useAppState, type Selection } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { diagnosticTargets } from './diagnosticsText';
import { DiagnosticsPanel } from './DiagnosticsPanel';
import { GraphView } from './GraphView';
import { Legend } from './Legend';
import { buildElements, filterSnapshot, nodeElementId, topicElementId } from './model';
import { usePalette } from './usePalette';

export function selectionToElementId(sel: Selection): string | null {
  if (!sel) return null;
  return sel.kind === 'topic' ? topicElementId(sel.id) : nodeElementId(sel.id);
}

export function elementIdToSelection(id: string | null): Selection {
  if (!id) return null;
  if (id.startsWith('t:')) return { kind: 'topic', id: id.slice(2) };
  if (id.startsWith('n:')) return { kind: 'node', id: id.slice(2) };
  return null;
}

export function GraphTab({ active }: { active: boolean }) {
  const { live, paused, setPaused } = useLive();
  const { selection, select } = useAppState();
  const palette = usePalette();
  const [query, setQuery] = useState('');
  const [hideHidden, setHideHidden] = useState(true);
  const [fitSignal, setFitSignal] = useState(0);

  const filtered = useMemo(
    () => (live.graph ? filterSnapshot(live.graph, { query, hideHidden }) : null),
    [live.graph, query, hideHidden],
  );
  const elements = useMemo(
    () => (filtered ? buildElements(filtered, live.traffic, live.receivedAt || Date.now()) : []),
    [filtered, live.traffic, live.receivedAt],
  );
  const diagnostics = live.graph?.diagnostics ?? [];

  const focusDiagnostic = (d: Diagnostic) => {
    const { topics, nodes } = diagnosticTargets(d);
    if (topics[0]) select({ kind: 'topic', id: topics[0] });
    else if (nodes[0]) select({ kind: 'node', id: nodes[0] });
  };

  return (
    <div className="graph-tab">
      <div className="toolbar" role="toolbar">
        <input
          type="search"
          placeholder={t('graph.filter')}
          aria-label={t('graph.filter')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="check">
          <input type="checkbox" checked={hideHidden} onChange={(e) => setHideHidden(e.target.checked)} />
          {t('graph.hideHidden')}
        </label>
        <button type="button" onClick={() => setPaused(!paused)} aria-pressed={paused}>
          {paused ? `▶ ${t('graph.resume')}` : `⏸ ${t('graph.pause')}`}
        </button>
        <button type="button" onClick={() => setFitSignal((n) => n + 1)}>
          {t('graph.fit')}
        </button>
        {paused && <span className="paused-banner">{t('graph.paused')}</span>}
      </div>
      <div className="graph-body">
        <div className="graph-main">
          {elements.length === 0 && live.graph && <p className="graph-empty">{t('graph.empty')}</p>}
          <GraphView
            elements={elements}
            traffic={live.traffic}
            tick={live.tick}
            palette={palette}
            paused={paused}
            active={active}
            selectedId={selectionToElementId(selection)}
            onSelect={(id) => select(elementIdToSelection(id))}
            fitSignal={fitSignal}
          />
          <Legend palette={palette} />
        </div>
        <DiagnosticsPanel diagnostics={diagnostics} onFocus={focusDiagnostic} />
      </div>
      <p className="limits muted">{t('graph.limits')}</p>
    </div>
  );
}
