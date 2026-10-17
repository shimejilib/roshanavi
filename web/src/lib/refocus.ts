// Calls `refresh` whenever the user comes back to this page (window focus / tab becomes visible),
// so lists of things that change outside the page (files in the data directory) are not stale.

export interface VisibilitySource extends EventTarget {
  visibilityState?: string;
}

/** Returns an unsubscribe function. */
export function onRefocus(win: EventTarget, doc: VisibilitySource, refresh: () => void): () => void {
  const onFocus = () => refresh();
  const onVisibility = () => {
    if (doc.visibilityState === 'visible') refresh();
  };
  win.addEventListener('focus', onFocus);
  doc.addEventListener('visibilitychange', onVisibility);
  return () => {
    win.removeEventListener('focus', onFocus);
    doc.removeEventListener('visibilitychange', onVisibility);
  };
}
