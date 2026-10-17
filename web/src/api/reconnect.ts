// Auto-reconnecting JSON WebSocket with exponential backoff.

export type SocketStatus = 'connecting' | 'open' | 'closed';

export const BACKOFF_MIN_MS = 500;
export const BACKOFF_MAX_MS = 5000;

export function nextBackoff(previousMs: number): number {
  if (previousMs <= 0) return BACKOFF_MIN_MS;
  return Math.min(BACKOFF_MAX_MS, previousMs * 2);
}

/** `/ws/live` -> `ws://host/ws/live` relative to the page origin. */
export function wsUrl(path: string, location: { protocol: string; host: string } = window.location): string {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${location.host}${path}`;
}

export interface ReconnectingSocketOptions {
  url: string;
  onMessage: (data: unknown) => void;
  onStatus: (status: SocketStatus) => void;
  /** Stop reconnecting after the server closes with this code (e.g. 1008 policy). */
  fatalCodes?: number[];
}

export class ReconnectingSocket {
  private ws: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private backoff = 0;
  private closed = false;

  constructor(private readonly opts: ReconnectingSocketOptions) {
    this.connect();
  }

  private connect(): void {
    if (this.closed) return;
    this.opts.onStatus('connecting');
    const ws = new WebSocket(this.opts.url);
    this.ws = ws;
    ws.onopen = () => {
      this.backoff = 0;
      this.opts.onStatus('open');
    };
    ws.onmessage = (event: MessageEvent<string>) => {
      let data: unknown;
      try {
        data = JSON.parse(event.data);
      } catch {
        return; // ignore malformed frames; the next tick replaces them
      }
      this.opts.onMessage(data);
    };
    ws.onclose = (event) => {
      this.ws = null;
      this.opts.onStatus('closed');
      if (this.closed || this.opts.fatalCodes?.includes(event.code)) return;
      this.backoff = nextBackoff(this.backoff);
      this.timer = setTimeout(() => this.connect(), this.backoff);
    };
  }

  close(): void {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
  }
}
