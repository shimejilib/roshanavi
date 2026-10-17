import { useEffect, useState } from 'react';
import { ReconnectingSocket, wsUrl, type SocketStatus } from '../api/reconnect';
import type { EchoMessage } from '../api/types';
import { t, tDynamic } from '../i18n';
import { topicPath } from '../lib/topics';

const POLICY_VIOLATION = 1008;
const MAX_CHARS = 20000;

function isEcho(value: unknown): value is EchoMessage {
  return typeof value === 'object' && value !== null && 'msg' in value && 'seq' in value;
}

function errorOf(value: unknown): string | null {
  if (typeof value !== 'object' || value === null || !('error' in value)) return null;
  const err = (value as { error: { code?: string; message?: string } }).error;
  return `${tDynamic(`error.${err.code ?? 'unknown'}`, 'error.unknown')} (${err.message ?? ''})`;
}

/** Live echo of one topic over /ws/echo (server throttles to <= 10 Hz). */
export function EchoView({ topic, autoStart }: { topic: string; autoStart: boolean }) {
  const [running, setRunning] = useState(autoStart);
  const [message, setMessage] = useState<EchoMessage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<SocketStatus>('closed');

  useEffect(() => {
    if (!running) return undefined;
    setMessage(null);
    setError(null);
    const socket = new ReconnectingSocket({
      url: wsUrl(topicPath('/ws/echo', topic)),
      fatalCodes: [POLICY_VIOLATION],
      onStatus: setStatus,
      onMessage: (data) => {
        const err = errorOf(data);
        if (err) setError(err);
        else if (isEcho(data)) setMessage(data);
      },
    });
    return () => socket.close();
  }, [topic, running]);

  const text = message ? JSON.stringify(message.msg, null, 2) : '';
  return (
    <section className="echo" aria-labelledby="echo-title">
      <h4 id="echo-title">
        {t('detail.echo')}{' '}
        <button type="button" onClick={() => setRunning(!running)} data-testid="echo-toggle">
          {running ? t('detail.echoStop') : t('detail.echoStart')}
        </button>
      </h4>
      {error && <p className="error-box">{error}</p>}
      {running && !message && !error && <p className="muted">{status === 'open' ? t('detail.echoWaiting') : t('ws.connecting')}</p>}
      {message && (
        <>
          <div className="muted small">#{message.seq} · {message.type}</div>
          <pre className="echo-body" data-testid="echo-body">{text.length > MAX_CHARS ? `${text.slice(0, MAX_CHARS)}…` : text}</pre>
        </>
      )}
    </section>
  );
}
