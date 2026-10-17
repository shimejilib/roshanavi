// Scenarios tab: list (project + examples), run with per-step results, edit, delete, record.

import { useCallback, useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { RunResult, ScenarioFile, ScenarioItem } from '../api/scenarioTypes';
import { t, tDynamic } from '../i18n';
import { ConfirmDialog } from '../lib/ConfirmDialog';
import { RecordView } from './RecordView';
import { RunResultView } from './RunResultView';
import { ScenarioEditor } from './ScenarioEditor';
import { useScenarioLive } from './ScenarioLive';
import { TourHelp } from '../tour/TourHelp';

type View = { kind: 'result'; id: string } | { kind: 'edit'; file: ScenarioFile } | { kind: 'record' } | { kind: 'none' };

function ItemRow({ item, active, running, onSelect, onRun, onEdit, onDelete }: {
  item: ScenarioItem;
  active: boolean;
  running: boolean;
  onSelect: () => void;
  onRun: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const last = item.last_result;
  return (
    <li className={active ? 'scn-item active' : 'scn-item'} data-testid={`scn-item-${item.id}`} data-tour="scn-item" data-scn-id={item.id} data-scn-source={item.source}>
      <button type="button" className="scn-item-main" onClick={onSelect}>
        <span className="scn-item-name">{item.name}</span>
        {last && <span className={`scn-badge scn-${last.status}`} data-testid="scn-item-status">{tDynamic(`scn.status.${last.status}`, 'scn.status.pending')}</span>}
        <span className="muted small mono">{item.file}</span>
        {item.description && <span className="muted small">{item.description}</span>}
        {item.error && <span className="error-text small">{t('scn.list.invalid')}</span>}
      </button>
      <div className="row">
        <button type="button" className="primary" disabled={running || Boolean(item.error)} onClick={onRun} data-testid={`scn-run-${item.id}`} data-tour="scn-run" data-scn-id={item.id}>{t('scn.run')}</button>
        <button type="button" onClick={onEdit} data-testid={`scn-edit-${item.id}`}>{item.read_only ? t('scn.list.copyEdit') : t('scn.edit.open')}</button>
        {!item.read_only && <button type="button" className="danger" onClick={onDelete} data-testid={`scn-delete-${item.id}`}>{t('scn.delete')}</button>}
      </div>
    </li>
  );
}

export function ScenariosTab() {
  const live = useScenarioLive();
  const [items, setItems] = useState<ScenarioItem[]>([]);
  const [projectDir, setProjectDir] = useState('');
  const [view, setView] = useState<View>({ kind: 'none' });
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ScenarioItem | null>(null);

  const reload = useCallback(() => {
    api.scenarios()
      .then((body) => {
        setItems(body.items);
        setProjectDir(body.project_dir);
        setError(null);
      })
      .catch((err: unknown) => setError(describeError(err)));
  }, []);
  useEffect(reload, [reload]);
  // A run finished: refresh the list badges.
  const finishedRun = live.run && !live.running ? live.run.run_id : null;
  useEffect(() => {
    if (finishedRun) reload();
  }, [finishedRun, reload]);

  const selectedId = view.kind === 'result' ? view.id : null;
  const liveRun = live.run && live.run.scenario_id === selectedId ? live.run : null;
  const shown = liveRun ?? (result && result.scenario_id === selectedId ? result : null);

  const select = async (item: ScenarioItem) => {
    setView({ kind: 'result', id: item.id });
    setResult(null);
    if (item.last_result) {
      try {
        setResult(await api.scenarioRun(item.last_result.run_id));
      } catch (err) {
        setError(describeError(err));
      }
    }
  };
  const run = async (item: ScenarioItem) => {
    setView({ kind: 'result', id: item.id });
    try {
      setResult(await api.runScenario(item.id));
      setError(null);
    } catch (err) {
      setError(describeError(err));
    }
  };
  const edit = async (item: ScenarioItem) => {
    try {
      setView({ kind: 'edit', file: await api.scenario(item.id) });
    } catch (err) {
      setError(describeError(err));
    }
  };
  const remove = async (item: ScenarioItem) => {
    setConfirm(null);
    try {
      await api.deleteScenario(item.id);
      if (selectedId === item.id) setView({ kind: 'none' });
      reload();
    } catch (err) {
      setError(describeError(err));
    }
  };
  const cancel = async () => {
    if (!live.run) return;
    try {
      await api.cancelScenarioRun(live.run.run_id);
    } catch (err) {
      setError(describeError(err));
    }
  };

  const project = items.filter((i) => i.source === 'project');
  const examples = items.filter((i) => i.source === 'example');
  const row = (item: ScenarioItem) => (
    <ItemRow key={item.id} item={item} active={selectedId === item.id} running={live.running}
      onSelect={() => void select(item)} onRun={() => void run(item)} onEdit={() => void edit(item)} onDelete={() => setConfirm(item)} />
  );
  return (
    <div className="scenarios-tab">
      <aside className="scn-list" aria-labelledby="scn-list-title">
        <div className="scn-list-head">
          <h3 id="scn-list-title">{t('scn.title')}</h3>
          <button type="button" className="primary" onClick={() => setView({ kind: 'record' })} data-testid="scn-record-open" data-tour="scn-record-open">
            {live.record.active ? t('scn.rec.openActive') : t('scn.rec.open')}
          </button>
        </div>
        <p className="muted small">{t('scn.intro')}</p>
        {error && <p className="error-box" role="alert">{error}</p>}
        <h4>{t('scn.list.project')}</h4>
        <p className="muted small mono">{projectDir}</p>
        <ul className="scn-items">{project.map(row)}</ul>
        {project.length === 0 && <p className="muted small">{t('scn.list.empty')} <TourHelp id="scenario" /></p>}
        {examples.length > 0 && (
          <>
            <h4>{t('scn.list.examples')}</h4>
            <ul className="scn-items">{examples.map(row)}</ul>
          </>
        )}
      </aside>
      <main className="scn-main">
        {view.kind === 'record' && (
          <RecordView onSaved={(file) => {
            reload();
            setView({ kind: 'result', id: file.id });
            setResult(null);
          }} />
        )}
        {view.kind === 'edit' && (
          <ScenarioEditor key={view.file.id} file={view.file} onClose={() => setView({ kind: 'none' })}
            onSaved={(saved) => {
              reload();
              setView({ kind: 'result', id: saved.id });
              setResult(null);
            }} />
        )}
        {view.kind === 'result' && (shown ? <RunResultView result={shown} onCancel={() => void cancel()} />
          : <p className="muted">{t('scn.noResult')}</p>)}
        {view.kind === 'none' && <p className="muted">{t('scn.pick')}</p>}
      </main>
      {confirm && (
        <ConfirmDialog title={t('scn.deleteTitle')} text={t('scn.deleteText', { name: confirm.name, file: confirm.file })}
          okLabel={t('scn.delete')} onOk={() => void remove(confirm)} onCancel={() => setConfirm(null)} />
      )}
    </div>
  );
}

export function RecordingBadge({ onOpen }: { onOpen: () => void }) {
  const { record } = useScenarioLive();
  if (!record.active) return null;
  return (
    <button type="button" className="scn-rec-pill" onClick={onOpen} data-testid="scn-rec-badge" title={t('scn.rec.badgeHelp')}>
      ● {t('scn.rec.badge')}
    </button>
  );
}
