// /ws/capture client: JSON start message, then binary frames (PCM int16 or JPEG).

import { wsUrl } from '../api/reconnect';
import type { CaptureEvent, CaptureStartMessage } from '../api/mediaTypes';

/** Skip frames while this much is still queued (slow link / server busy). */
export const MAX_BUFFERED_BYTES = 2 * 1024 * 1024;

export class CaptureSocket {
  private readonly ws: WebSocket;
  private closed = false;

  constructor(start: CaptureStartMessage, private readonly onEvent: (event: CaptureEvent | { closed: true }) => void) {
    this.ws = new WebSocket(wsUrl('/ws/capture'));
    this.ws.binaryType = 'arraybuffer';
    this.ws.onopen = () => this.ws.send(JSON.stringify(start));
    this.ws.onmessage = (msg: MessageEvent<string>) => {
      try {
        this.onEvent(JSON.parse(msg.data) as CaptureEvent);
      } catch {
        // the server only sends JSON text frames; ignore anything else
      }
    };
    this.ws.onclose = () => {
      this.closed = true;
      this.onEvent({ closed: true });
    };
  }

  /** Returns false when the frame was skipped (socket not ready or backlog). */
  send(data: ArrayBuffer | ArrayBufferView): boolean {
    if (this.closed || this.ws.readyState !== WebSocket.OPEN || this.ws.bufferedAmount > MAX_BUFFERED_BYTES) return false;
    this.ws.send(data);
    return true;
  }

  close(): void {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ cmd: 'stop' }));
    this.ws.close();
  }
}
