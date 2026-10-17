import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, describeError } from '../api/client';
import type { TargetSpec, WorkspaceInfo } from '../api/types';
import { t } from '../i18n';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { BuildPanel } from './BuildPanel';
import { buildTargetSpec, EMPTY_FORM, formFromSpec, type TargetForm } from './form';
import { LogViewer } from './LogViewer';
import { PackagePicker, type Pick } from './PackagePicker';
import { ProjectBar } from './ProjectBar';
import { TargetFormView } from './TargetFormView';
import { TargetList } from './TargetList';

const BUILD_LOG_ID = '_build';
type Notice = { kind: 'ok' | 'error'; text: string } | null;

function useWorkspace(): { info: WorkspaceInfo | null; error: string | null; reload: (refresh: boolean) => void } {
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback((refresh: boolean) => {
    (refresh ? api.refreshWorkspace() : api.workspace())
      .then((ws) => {
        setInfo(ws);
        setError(null);
      })
      .catch((err: unknown) => setError(describeError(err)));
  }, []);
  useEffect(() => reload(false), [reload]);
  return { info, error, reload };
}

export function LauncherTab() {
  const { live } = useLive();
  const { logTarget, openLogs } = useAppState();
  const workspace = useWorkspace();
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

  const pick = (p: Pick) => {
    setForm({ ...EMPTY_FORM, kind: p.kind, package: p.pkg.name, executable: p.kind === 'run' ? p.file : '', launchFile: p.kind === 'launch' ? p.file : '' });
    setEditing(false);
    setNotice(null);
  };

  const edit = (spec: TargetSpec) => {
    setForm(formFromSpec(spec));
    setEditing(true);
    setNotice(null);
  };

  const submit = async (startAfter: boolean) => {
    if (!form) return;
    const built = buildTargetSpec(form, targetIds);
    if (!built.ok) {
      setNotice({ kind: 'error', text: built.error });
      return;
    }
    setBusy(true);
    try {
      const spec = built.value;
      await (editing ? api.updateTarget(spec) : api.addTarget(spec));
      if (startAfter) await api.targetAction(spec.id, 'start');
      openLogs(spec.id, false);
      setNotice({ kind: 'ok', text: t('launcher.form.added', { id: spec.id }) });
      setForm(null);
    } catch (err) {
      setNotice({ kind: 'error', text: describeError(err) });
    } finally {
      setBusy(false);
    }
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

  return (
    <div className="launcher-tab">
      <ProjectBar version={projectVersion} />
      <div className="launcher-body">
        <PackagePicker
          packages={workspace.info?.packages ?? []}
          onPick={pick}
          onBuild={(pkg) => void build(pkg)}
          onRefresh={() => workspace.reload(true)}
          buildBusy={buildState === 'running'}
        />
        <div className="launcher-main">
          {workspace.error && <p className="error-box" role="alert">{workspace.error}</p>}
          {notice && <p className={notice.kind === 'ok' ? 'ok-box' : 'error-box'} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</p>}
          {form ? (
            <TargetFormView form={form} editing={editing} busy={busy} onChange={(patch) => setForm({ ...form, ...patch })} onSubmit={(s) => void submit(s)} onCancel={() => setForm(null)} />
          ) : (
            <p className="muted small">{t('launcher.pick')}</p>
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
