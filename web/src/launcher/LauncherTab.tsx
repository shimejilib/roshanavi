import { useEffect, useMemo, useState } from 'react';
import { api, describeError } from '../api/client';
import type { TargetSpec } from '../api/types';
import { t } from '../i18n';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { BuildPanel } from './BuildPanel';
import { FirstRunGuide } from './FirstRunGuide';
import { buildTargetSpec, EMPTY_FORM, formFromSpec, type TargetForm } from './form';
import { canTryTalker, needsGuide, tryTalkerSpec } from './guide';
import { LogViewer } from './LogViewer';
import { PackagePicker, type Pick } from './PackagePicker';
import { workspaceConfigured } from './packages';
import { ProjectBar } from './ProjectBar';
import { TargetFormView } from './TargetFormView';
import { TargetList } from './TargetList';
import { useWorkspace } from './useWorkspace';
import { WorkspaceHelp } from './WorkspaceHelp';

const BUILD_LOG_ID = '_build';
type Notice = { kind: 'ok' | 'error'; text: string } | null;

export function LauncherTab() {
  const { live } = useLive();
  const { logTarget, openLogs, launcherRequest, clearLauncherRequest } = useAppState();
  const workspace = useWorkspace();
  const packages = workspace.info?.packages ?? [];
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState<TargetForm | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [restartRunning, setRestartRunning] = useState(true);
  const targetIds = useMemo(() => live.targets.map((tg) => tg.id), [live.targets]);
  const projectVersion = useMemo(() => JSON.stringify(live.targets.map((tg) => tg.spec)), [live.targets]);
  const buildState = live.build?.state;

  useEffect(() => {
    if (buildState === 'succeeded') workspace.reload(false);
  }, [buildState, workspace.reload]);

  const edit = (spec: TargetSpec) => {
    setForm(formFromSpec(spec));
    setEditing(true);
    setAdding(false);
    setNotice(null);
  };

  useEffect(() => {
    if (!launcherRequest) return;
    if (launcherRequest.kind === 'add') {
      setAdding(true);
      setForm(null);
    } else {
      const target = live.targets.find((tg) => tg.id === launcherRequest.targetId);
      if (target && (target.kind === 'run' || target.kind === 'launch')) edit(target.spec as TargetSpec);
    }
    clearLauncherRequest();
    // Handle each request once.
  }, [launcherRequest]);

  const pick = (p: Pick) => {
    setForm({ ...EMPTY_FORM, kind: p.kind, package: p.pkg.name, executable: p.kind === 'run' ? p.file : '', launchFile: p.kind === 'launch' ? p.file : '' });
    setEditing(false);
    setNotice(null);
  };

  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    setNotice(null);
    try {
      const id = await action();
      openLogs(id, false);
      setNotice({ kind: 'ok', text: t('launcher.form.added', { id }) });
      setForm(null);
      setAdding(false);
    } catch (err) {
      setNotice({ kind: 'error', text: describeError(err) });
    } finally {
      setBusy(false);
    }
  };

  const submit = (startAfter: boolean) => {
    if (!form) return;
    const built = buildTargetSpec(form, targetIds);
    if (!built.ok) {
      setNotice({ kind: 'error', text: built.error });
      return;
    }
    const spec = built.value;
    void run(async () => {
      if (editing) await api.updateTarget(spec);
      else await api.addTarget(spec, startAfter);
      return spec.id;
    });
  };

  const tryTalker = () => {
    const spec = tryTalkerSpec(live.targets);
    void run(async () => (await api.addTarget(spec, true)).id);
  };

  const build = async (pkg: string) => {
    setNotice(null);
    try {
      await api.build(pkg, restartRunning);
      openLogs(BUILD_LOG_ID, false);
    } catch (err) {
      setNotice({ kind: 'error', text: describeError(err) });
    }
  };

  const showPicker = adding || (form !== null && !editing);
  return (
    <div className="launcher-tab">
      <ProjectBar version={projectVersion} />
      <div className={showPicker ? 'launcher-body' : 'launcher-body no-picker'}>
        {showPicker && (
          <PackagePicker packages={packages} onPick={pick} onBuild={(pkg) => void build(pkg)} onRefresh={() => workspace.reload(true)} buildBusy={buildState === 'running'} />
        )}
        <div className="launcher-main">
          <div className="row">
            <button type="button" className="primary" onClick={() => { setAdding(!showPicker); setForm(null); }} aria-expanded={showPicker} data-testid="launcher-add">
              {showPicker ? t('launcher.closeAdd') : t('launcher.add')}
            </button>
          </div>
          {workspace.error && <p className="error-box" role="alert">{workspace.error}</p>}
          {workspace.info && showPicker && !workspaceConfigured(packages) && <WorkspaceHelp root={workspace.info.root} />}
          {notice && <p className={notice.kind === 'ok' ? 'ok-box' : 'error-box'} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</p>}
          {form && <TargetFormView form={form} editing={editing} busy={busy} onChange={(patch) => setForm({ ...form, ...patch })} onSubmit={submit} onCancel={() => setForm(null)} />}
          {showPicker && !form && <p className="muted small">{t('launcher.pick')}</p>}
          {needsGuide(live.targets) && !showPicker && (
            <FirstRunGuide canTry={canTryTalker(packages)} busy={busy} onTry={tryTalker} onAdd={() => setAdding(true)} />
          )}
          <BuildPanel
            build={live.build}
            restartRunning={restartRunning}
            onRestartRunning={setRestartRunning}
            onCancel={() => void api.cancelBuild().catch((err: unknown) => setNotice({ kind: 'error', text: describeError(err) }))}
            onShowLog={() => openLogs(BUILD_LOG_ID, false)}
          />
          <TargetList targets={live.targets} selectedLog={logTarget} onLogs={(id) => openLogs(id, false)} onEdit={edit} />
        </div>
        <LogViewer logId={logTarget} />
      </div>
    </div>
  );
}
