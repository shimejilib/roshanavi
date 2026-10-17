// Positions of map vertices the user dragged ("pinned"): the automatic layout leaves them where they are.
//
// Kept per project in localStorage (a different project has different nodes with possibly the same names).
// Everything here is pure or takes the storage as a parameter; storage access is always guarded because it
// can throw or be empty (private window, blocked site data).

export interface Pin {
  x: number;
  y: number;
}

export type Pins = Readonly<Record<string, Pin>>;

export const NO_PINS: Pins = Object.freeze({});
const KEY_PREFIX = 'roshanavi.mapPins.v1:';
/** Old pins of vertices that left the graph are kept (they may come back), up to this many. */
export const MAX_PINS = 500;

type PinStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function defaultStorage(): PinStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

const isPin = (v: unknown): v is Pin =>
  typeof v === 'object' && v !== null
  && Number.isFinite((v as Pin).x) && Number.isFinite((v as Pin).y);

/** Only well-formed `{id: {x, y}}` entries survive; anything else (corrupt JSON, wrong shape) is ignored. */
export function parsePins(raw: string | null): Pins {
  if (!raw) return NO_PINS;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return NO_PINS;
    const entries = Object.entries(parsed).filter(([, v]) => isPin(v)).map(([id, v]) => [id, { x: (v as Pin).x, y: (v as Pin).y }]);
    return Object.fromEntries(entries.slice(-MAX_PINS));
  } catch {
    return NO_PINS;
  }
}

export function loadPins(project: string, storage: PinStorage | null = defaultStorage()): Pins {
  try {
    return parsePins(storage?.getItem(KEY_PREFIX + project) ?? null);
  } catch {
    return NO_PINS;
  }
}

export function savePins(project: string, pins: Pins, storage: PinStorage | null = defaultStorage()): void {
  try {
    if (Object.keys(pins).length === 0) storage?.removeItem(KEY_PREFIX + project);
    else storage?.setItem(KEY_PREFIX + project, JSON.stringify(pins));
  } catch {
    // Not persisted (quota / blocked storage): the pins still work for this page.
  }
}

/** A copy with `id` pinned at `pos`; the newest pin goes last so the oldest are the ones dropped at the cap. */
export function withPin(pins: Pins, id: string, pos: Pin): Pins {
  const { [id]: _old, ...rest } = pins;
  const entries = Object.entries({ ...rest, [id]: { x: pos.x, y: pos.y } });
  return Object.fromEntries(entries.slice(-MAX_PINS));
}
