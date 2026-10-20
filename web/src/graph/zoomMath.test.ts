import { describe, expect, it } from 'vitest';
import { ACTUAL_ZOOM, MAX_ZOOM, MIN_ZOOM, ZOOM_STEP, canZoomIn, canZoomOut, clampZoom, stepZoom, zoomPercent } from './zoomMath';

describe('zoomMath', () => {
  it('steps by a fixed factor', () => {
    expect(stepZoom(1, 'in')).toBeCloseTo(ZOOM_STEP);
    expect(stepZoom(1, 'out')).toBeCloseTo(1 / ZOOM_STEP);
    expect(stepZoom(stepZoom(0.8, 'in'), 'out')).toBeCloseTo(0.8);
  });

  it('clamps to the limits', () => {
    expect(stepZoom(3.5, 'in')).toBe(MAX_ZOOM);
    expect(stepZoom(MAX_ZOOM, 'in')).toBe(MAX_ZOOM);
    expect(stepZoom(0.11, 'out')).toBe(MIN_ZOOM);
    expect(stepZoom(MIN_ZOOM, 'out')).toBe(MIN_ZOOM);
    expect(clampZoom(100)).toBe(MAX_ZOOM);
    expect(clampZoom(0)).toBe(MIN_ZOOM);
  });

  it('falls back to 100% for a value that is not a number', () => {
    expect(clampZoom(Number.NaN)).toBe(ACTUAL_ZOOM);
    expect(clampZoom(Number.POSITIVE_INFINITY)).toBe(ACTUAL_ZOOM);
  });

  it('disables ＋ at the maximum and − at the minimum only', () => {
    expect(canZoomIn(MAX_ZOOM)).toBe(false);
    expect(canZoomIn(MAX_ZOOM - 1e-9)).toBe(false);
    expect(canZoomIn(3)).toBe(true);
    expect(canZoomOut(MIN_ZOOM)).toBe(false);
    expect(canZoomOut(MIN_ZOOM + 1e-9)).toBe(false);
    expect(canZoomOut(0.5)).toBe(true);
    expect(canZoomIn(MIN_ZOOM) && canZoomOut(MAX_ZOOM)).toBe(true);
  });

  it('shows a whole-number percentage', () => {
    expect(zoomPercent(1)).toBe('100%');
    expect(zoomPercent(0.8)).toBe('80%');
    expect(zoomPercent(1.25)).toBe('125%');
    expect(zoomPercent(0.1234)).toBe('12%');
    expect(zoomPercent(MAX_ZOOM)).toBe('400%');
  });
});
