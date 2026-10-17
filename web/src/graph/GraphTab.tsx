import { useMemo, useState } from 'react';
import type { Diagnostic } from '../api/types';
import { ErrorBoundary } from '../lib/ErrorBoundary';
import { t } from '../i18n';
import { buildablePackages } from '../launcher/packages';
import { useWorkspace } from '../launcher/useWorkspace';
import { useAppState, type Selection } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { LastUpdateBadge } from '../timing/LastUpdate';
import { TourHelp } from '../tour/TourHelp';
import { WindowSelect } from '../timing/WindowSelect';
import { diagnosticTargets } from './diagnosticsText';
import { DiagnosticsPanel } from './DiagnosticsPanel';
import { GraphView } from './GraphView';
import { isolateSnapshot } from './isolate';
import { Legend } from './Legend';
import { MapMenu } from './MapMenu';
import { buildElements, filterSnapshot, nodeElementId, topicElementId } from './model';
import { usePalette } from './usePalette';
import { useProjectKey } from './useProjectKey';

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

function IsolationBanner() {
  const { isolation, setIsolation } = useAppState();
  if (!isolation) return null;
  const name = isolation.elementId.slice(2);
  return (
    <span className="isolation-banner" data-testid="isolation-banner">
      {t(isolation.mode === 'io' ? 'graph.isolatedIo' : 'graph.isolatedFlow', { name })}{' '}
      <button type="button" className="small" onClick={() => setIsolation(null)}>{t('graph.showAll')}</button>
    </span>
  );
}

export function GraphTab({ active }: { active: boolean }) {
  const { live, paused, setPaused } = useLive();
  const { selection, select, openDialog, isolation } = useAppState();
  const palette = usePalette();
  const workspace = useWorkspace();
  const projectKey = useProjectKey();
  const [query, setQuery] = useState('');
  const [hideHidden, setHideHidden] = useState(true);
  const [fitSignal, setFitSignal] = useState(0);
  const [layoutSignal, setLayoutSignal] = useState(0);
  const buildable = useMemo(() => new Set(buildablePackages(workspace.info?.packages ?? []).map((p) => p.name)), [workspace.info]);

  const filtered = useMemo(
    () => (live.graph ? isolateSnapshot(filterSnapshot(live.graph, { query, hideHidden }), isolation) : null),
    [live.graph, query, hideHidden, isolation],
  );
  const elements = useMemo(
    () => (filtered ? buildElements(filtered, live.traffic, live.receivedAt || Date.now()) : []),
    [filtered, live.traffic, live.receivedAt],
  );
  const diagnostics = live.graph?.diagnostics ?? [];
  const commands = useMemo(() => ({ fit: () => setFitSignal((n) => n + 1), relayout: () => setLayoutSignal((n) => n + 1) }), []);

  const focusDiagnostic = (d: Diagnostic) => {
    const { topics, nodes } = diagnosticTargets(d);
    if (topics[0]) select({ kind: 'topic', id: topics[0] });
    else if (nodes[0]) select({ kind: 'node', id: nodes[0] });
  };

  return (
    <div className="graph-tab">
      <div className="toolbar" role="toolbar">
        <button type="button" className="primary" onClick={() => openDialog({ kind: 'createInput' })} data-testid="create-input" data-tour="create-input">
          {t('input.create')}
        </button>
        <button type="button" onClick={() => openDialog({ kind: 'createTransform' })} data-testid="create-transform">
          {t('transform.create')}
        </button>
        <button type="button" onClick={() => openDialog({ kind: 'createFunction' })} data-testid="create-function" data-tour="create-function">
          {t('function.create')}
        </button>
        <input type="search" placeholder={t('graph.filter')} aria-label={t('graph.filter')} value={query} onChange={(e) => setQuery(e.target.value)} />
        <label className="check">
          <input type="checkbox" checked={hideHidden} onChange={(e) => setHideHidden(e.target.checked)} />
          {t('graph.hideHidden')}
        </label>
        <button type="button" onClick={() => setPaused(!paused)} aria-pressed={paused}>
          {paused ? `▶ ${t('graph.resume')}` : `⏸ ${t('graph.pause')}`}
        </button>
        <button type="button" onClick={commands.fit}>{t('graph.fit')}</button>
        <WindowSelect />
        {paused && <span className="paused-banner">{t('graph.paused')}</span>}
        <IsolationBanner />
        <span className="spacer" />
        <LastUpdateBadge />
      </div>
      <div className="graph-body">
        <div className="graph-main" data-tour="map">
          {elements.length === 0 && live.graph && (
            <p className="graph-empty">{t('graph.empty')} <TourHelp id="firstInput" /></p>
          )}
          <ErrorBoundary scope="map">
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
            layoutSignal={layoutSignal}
            projectKey={projectKey}
            renderMenu={(anchor, close) => (
              <MapMenu key={`${anchor.x}:${anchor.y}`} anchor={anchor} buildable={buildable} commands={commands} onClose={close} />
            )}
          />
          </ErrorBoundary>
          <Legend palette={palette} />
        </div>
        <DiagnosticsPanel diagnostics={diagnostics} onFocus={focusDiagnostic} />
      </div>
      <p className="limits muted">{t('graph.limits')}</p>
    </div>
  );
}
