// /ws/view/{topic}: JSON meta frames, each followed by one binary frame (JPEG or PCM).

import { wsUrl } from '../api/reconnect';
import { topicPath } from '../lib/topics';

export interface ViewerMeta {
  event: 'ready' | 'image' | 'audio';
  kind?: 'image' | 'audio';
  type?: string;
  width?: number;
  height?: number;
  sample_rate?: number;
  samples?: number;
}

export interface ViewerHandlers {
  onMeta: (meta: ViewerMeta) => void;
  onData: (meta: ViewerMeta, data: ArrayBuffer) => void;
  onError: (code: string, message: string) => void;
}

export function openViewer(topic: string, query: string, handlers: ViewerHandlers): () => void {
  const ws = new WebSocket(wsUrl(`${topicPath('/ws/view', topic)}${query}`));
  ws.binaryType = 'arraybuffer';
  let pending: ViewerMeta | null = null;
  ws.onmessage = (msg: MessageEvent<string | ArrayBuffer>) => {
    if (typeof msg.data !== 'string') {
      if (pending) handlers.onData(pending, msg.data);
      pending = null;
      return;
    }
    let body: unknown;
    try {
      body = JSON.parse(msg.data);
    } catch {
      return;
    }
    if (typeof body === 'object' && body !== null && 'error' in body) {
      const err = (body as { error: { code: string; message: string } }).error;
      handlers.onError(err.code, err.message);
      return;
    }
    const meta = body as ViewerMeta;
    if (meta.event === 'ready') handlers.onMeta(meta);
    else pending = meta;
  };
  return () => ws.close();
}
