// Zoom control in the bottom-right corner of the map: ＋ / − / 全体を表示 / 100% and the current zoom.
// The wheel, pinch and "fit" all end in cytoscape's `zoom` event, so the percentage listens to that.

import type { Core } from 'cytoscape';
import { useEffect, useState } from 'react';
import { t } from '../i18n';
import { ACTUAL_ZOOM, canZoomIn, canZoomOut, stepZoom, zoomPercent, type ZoomDirection } from './zoomMath';

interface Props {
  cy: Core;
  /** The same function as the top bar's 全体を表示. */
  onFit: (cy: Core) => void;
}

/** Zoom to `level` around the centre of the visible map (the view stays centred on what it shows now). */
function zoomAroundCentre(cy: Core, level: number): void {
  cy.zoom({ level, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
}

export function MapZoomControl({ cy, onFit }: Props) {
  const [zoom, setZoom] = useState(() => cy.zoom());
  useEffect(() => {
    const sync = () => setZoom(cy.zoom());
    sync();
    cy.on('zoom', sync);
    return () => {
      cy.off('zoom', sync);
    };
  }, [cy]);

  const step = (direction: ZoomDirection) => zoomAroundCentre(cy, stepZoom(cy.zoom(), direction));

  return (
    <div className="map-zoom" role="group" aria-label={t('zoom.group')} data-testid="map-zoom">
      <div className="map-zoom-row">
        <button type="button" onClick={() => step('out')} disabled={!canZoomOut(zoom)} aria-label={t('zoom.out')} title={t('zoom.outTitle')} data-testid="map-zoom-out">−</button>
        <span className="map-zoom-percent" title={t('zoom.current')} data-testid="map-zoom-percent">{zoomPercent(zoom)}</span>
        <button type="button" onClick={() => step('in')} disabled={!canZoomIn(zoom)} aria-label={t('zoom.in')} title={t('zoom.inTitle')} data-testid="map-zoom-in">＋</button>
      </div>
      <div className="map-zoom-row">
        <button type="button" onClick={() => zoomAroundCentre(cy, ACTUAL_ZOOM)} aria-label={t('zoom.actualAria')} title={t('zoom.actualTitle')} data-testid="map-zoom-actual">{t('zoom.actual')}</button>
        <button type="button" onClick={() => onFit(cy)} aria-label={t('zoom.fit')} title={t('zoom.fitTitle')} data-testid="map-zoom-fit">{t('zoom.fit')}</button>
      </div>
    </div>
  );
}
