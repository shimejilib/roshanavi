// Zoom arithmetic for the map's on-screen zoom control (pure; the cytoscape calls live in the component).

export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 4;
/** One press of ＋ / − multiplies / divides the zoom by this. */
export const ZOOM_STEP = 1.25;
/** Zoom of the "100%" button. */
export const ACTUAL_ZOOM = 1;
// Floating-point slack when comparing a zoom with the limits (cytoscape stores the clamped value as is).
const EPSILON = 1e-6;

export type ZoomDirection = 'in' | 'out';

export function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return ACTUAL_ZOOM;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

/** The zoom after one ＋ / − press, kept inside the limits. */
export function stepZoom(zoom: number, direction: ZoomDirection): number {
  return clampZoom(direction === 'in' ? zoom * ZOOM_STEP : zoom / ZOOM_STEP);
}

export function canZoomIn(zoom: number): boolean {
  return zoom < MAX_ZOOM - EPSILON;
}

export function canZoomOut(zoom: number): boolean {
  return zoom > MIN_ZOOM + EPSILON;
}

/** Whole-number percentage text, e.g. 0.8 -> "80%". */
export function zoomPercent(zoom: number): string {
  return `${Math.round(clampZoom(zoom) * 100)}%`;
}
