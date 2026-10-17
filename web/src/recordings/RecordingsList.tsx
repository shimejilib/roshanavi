// Finished recordings: size, duration, topics, play (bag mode) and delete.

import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { Recording } from '../api/mediaTypes';
import { t } from '../i18n';
import { ConfirmDialog } from '../lib/ConfirmDialog';
import { formatBytes, formatDuration } from '../lib/format';

interface Props {
  recordings: Recording[];
  onChanged: () => void;
}

export function RecordingsList({ recordings, onChanged }: Props) {
  const [confirm, setConfirm] = useState<Recording | null>(null);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  const play = async (rec: Recording) => {
    setMessage(null);
    try {
      const job = await api.startInject({ mode: 'bag', source: rec.path });
      setMessage({ kind: 'ok', text: t('rec.playStarted', { id: job.id }) });
    } catch (err) {
      setMessage({ kind: 'error', text: describeError(err) });
    }
  };
  const remove = async (rec: Recording) => {
    setConfirm(null);
    try {
      await api.deleteRecording(rec.name);
      onChanged();
    } catch (err) {
      setMessage({ kind: 'error', text: describeError(err) });
    }
  };

  return (
    <section className="rec-list" aria-labelledby="rec-list-title">
      <h3 id="rec-list-title">{t('rec.list')}</h3>
      {message && <p className={message.kind === 'ok' ? 'ok-box' : 'error-box'} role={message.kind === 'ok' ? 'status' : 'alert'}>{message.text}</p>}
      {recordings.length === 0 ? (
        <p className="muted">{t('rec.empty')}</p>
      ) : (
        <table className="traffic-table" data-testid="recordings">
          <thead>
            <tr>
              <th>{t('rec.col.name')}</th>
              <th>{t('rec.col.size')}</th>
              <th>{t('rec.col.duration')}</th>
              <th>{t('rec.col.count')}</th>
              <th>{t('rec.col.topics')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {recordings.map((rec) => (
              <tr key={rec.name} data-testid={`recording-${rec.name}`}>
                <td className="mono">{rec.name}</td>
                <td>{formatBytes(rec.size)}</td>
                <td>{rec.duration_sec == null ? '—' : formatDuration(rec.duration_sec)}</td>
                <td>{rec.message_count ?? '—'}</td>
                <td className="mono small">
                  {rec.finalized ? rec.topics.map((tp) => `${tp.name} (${tp.count})`).join(', ') : <span className="muted">{t('rec.notFinalized')}</span>}
                </td>
                <td className="row">
                  <button type="button" disabled={!rec.finalized || rec.active} onClick={() => void play(rec)}>{t('rec.play')}</button>
                  <button type="button" className="danger" disabled={rec.active} onClick={() => setConfirm(rec)} data-testid={`rec-delete-${rec.name}`}>{t('rec.delete')}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {confirm && (
        <ConfirmDialog
          title={t('rec.deleteTitle')}
          text={t('rec.deleteConfirm', { name: confirm.name })}
          okLabel={t('rec.delete')}
          onOk={() => void remove(confirm)}
          onCancel={() => setConfirm(null)}
        />
      )}
    </section>
  );
}
