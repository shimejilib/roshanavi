// Record button with topic selection and presets (DESIGN §4.12).

import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { RecordingStatus } from '../api/mediaTypes';
import { t } from '../i18n';
import { formatBytes, formatDuration } from '../lib/format';
import { isHiddenTopic } from '../lib/topics';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { addAll, inputTopics, myNodeOutputs, toggle } from './presets';

function ActiveRecording({ rec, onStop, busy }: { rec: RecordingStatus; onStop: () => void; busy: boolean }) {
  const disk = rec.disk;
  return (
    <div className="rec-active" data-testid="rec-active">
      <p className="rec-badge">● {t('rec.recording', { time: formatDuration(rec.elapsed_sec ?? 0), path: rec.path })}</p>
      <p className="muted small mono">{rec.topics.join(' ')}</p>
      {rec.warning && disk && (
        <p className="error-box small" role="alert">{t('rec.diskWarn', { free: formatBytes(disk.free_bytes), pct: disk.free_pct })}</p>
      )}
      <button type="button" className="danger" disabled={busy} onClick={onStop} data-testid="rec-stop">{t('rec.stop')}</button>
    </div>
  );
}

export function RecordPanel({ onChanged }: { onChanged: () => void }) {
  const { live } = useLive();
  const { recordTopic } = useAppState();
  const [selected, setSelected] = useState<string[]>(() => (recordTopic ? [recordTopic] : []));
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  // /ws/live reports the stop up to 1 s later; hide the stopped recording right away.
  const [stopped, setStopped] = useState<string | null>(null);
  const active = live.recording && live.recording.name !== stopped ? live.recording : null;
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const topics = (live.graph?.topics ?? []).map((tp) => tp.name).filter((n) => !isHiddenTopic(n));
  const presets: [string, string[]][] = [
    [t('rec.presetInputs'), inputTopics(live.jobs)],
    [t('rec.presetMine'), myNodeOutputs(live.graph)],
  ];

  const run = async (action: () => Promise<RecordingStatus>, ok: (r: RecordingStatus) => string) => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await action();
      setMessage(result.error ? { kind: 'error', text: result.error } : { kind: 'ok', text: ok(result) });
      onChanged();
    } catch (err) {
      setMessage({ kind: 'error', text: describeError(err) });
    } finally {
      setBusy(false);
    }
  };
  const start = () => {
    if (selected.length === 0) {
      setMessage({ kind: 'error', text: t('rec.needTopics') });
      return;
    }
    void run(() => api.startRecording(selected, name.trim()), () => '');
  };
  const stop = () =>
    void run(
      () => api.stopRecording(),
      (r) => {
        setStopped(r.name);
        return t('rec.saved', { path: r.path });
      },
    );

  return (
    <section className="rec-panel" aria-labelledby="rec-title">
      <h3 id="rec-title">{t('rec.title')}</h3>
      {active ? (
        <ActiveRecording rec={active} onStop={stop} busy={busy} />
      ) : (
        <>
          <div className="row">
            {presets.map(([label, list]) => (
              <button key={label} type="button" disabled={list.length === 0} title={list.length ? list.join('\n') : t('rec.presetNone')} onClick={() => setSelected(addAll(selected, list))}>
                + {label} ({list.length})
              </button>
            ))}
          </div>
          <fieldset className="rec-topics">
            <legend>{t('rec.topics')}</legend>
            {[...new Set([...topics, ...selected])].sort().map((topic) => (
              <label key={topic} className="check mono">
                <input type="checkbox" checked={selected.includes(topic)} onChange={() => setSelected(toggle(selected, topic))} data-testid={`rec-topic-${topic}`} />
                {topic}
              </label>
            ))}
          </fieldset>
          <label>
            {t('rec.name')}
            <input value={name} maxLength={40} pattern="[A-Za-z0-9_\-]*" onChange={(e) => setName(e.target.value)} data-testid="rec-name" />
          </label>
          <button type="button" className="primary rec-button" disabled={busy} onClick={start} data-testid="rec-start">{t('rec.start')}</button>
        </>
      )}
      {message && message.text && <p className={message.kind === 'ok' ? 'ok-box' : 'error-box'} role={message.kind === 'ok' ? 'status' : 'alert'}>{message.text}</p>}
      <p className="muted small">{t('rec.help')}</p>
    </section>
  );
}
