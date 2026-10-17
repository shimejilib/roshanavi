// 詳細設定モード (advanced mode): show raw ROS message types. Remembered per browser.
// Storage can be missing or throw (private windows, blocked site data): every access is guarded
// and the mode is simply off then.

import { useEffect, useState } from 'react';

export const ADVANCED_KEY = 'roshanavi.advancedMode';
const EVENT = 'roshanavi:advanced-mode';

export function readAdvanced(storage: Pick<Storage, 'getItem'> | null = safeStorage()): boolean {
  try {
    return storage?.getItem(ADVANCED_KEY) === '1';
  } catch {
    return false;
  }
}

export function writeAdvanced(on: boolean, storage: Pick<Storage, 'setItem'> | null = safeStorage()): void {
  try {
    storage?.setItem(ADVANCED_KEY, on ? '1' : '0');
  } catch {
    // Not remembered; the mode still applies until the page is reloaded.
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

let current: boolean | null = null;

export function useAdvancedMode(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState<boolean>(() => (current ??= readAdvanced()));
  useEffect(() => {
    const sync = () => setOn(current ?? false);
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, []);
  const set = (value: boolean) => {
    current = value;
    writeAdvanced(value);
    window.dispatchEvent(new Event(EVENT));
  };
  return [on, set];
}
