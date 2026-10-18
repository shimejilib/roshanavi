// pub/sub の 1 枚絵 (docs/design/wiring.md §5): processing boxes (nodes) send to and subscribe to a
// named channel (topic). Three points only. Inline SVG, no external assets; colours follow the
// theme. Shown at the start of the first tour and from the map legend.

import { useEffect, useRef } from 'react';
import { t } from '../i18n';

const W = 560;
const H = 230;

function Box({ x, y, label, sub }: { x: number; y: number; label: string; sub: string }) {
  return (
    <g>
      <rect className="primer-node" x={x} y={y} width={120} height={46} rx={10} />
      <text className="primer-node-text" x={x + 60} y={y + 20} textAnchor="middle">{label}</text>
      <text className="primer-node-sub" x={x + 60} y={y + 36} textAnchor="middle">{sub}</text>
    </g>
  );
}

function Arrow({ d, id }: { d: string; id: string }) {
  return <path className="primer-arrow" d={d} markerEnd={`url(#${id})`} />;
}

export function PubSubFigure() {
  const id = 'primer-arrowhead';
  const cx = W / 2;
  const cy = H / 2;
  return (
    <svg className="primer-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="primer-fig-title">
      <title id="primer-fig-title">{t('primer.figure')}</title>
      <defs>
        <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 L10 5 L0 10 z" className="primer-arrowhead" />
        </marker>
      </defs>
      <Box x={14} y={34} label={t('primer.sender', { n: 'A' })} sub={t('primer.node')} />
      <Box x={14} y={150} label={t('primer.sender', { n: 'B' })} sub={t('primer.node')} />
      <Box x={W - 134} y={34} label={t('primer.receiver', { n: 'C' })} sub={t('primer.node')} />
      <Box x={W - 134} y={150} label={t('primer.receiver', { n: 'D' })} sub={t('primer.node')} />
      <ellipse className="primer-topic" cx={cx} cy={cy} rx={78} ry={34} />
      <text className="primer-topic-name" x={cx} y={cy - 2} textAnchor="middle">/chatter</text>
      <text className="primer-topic-sub" x={cx} y={cy + 16} textAnchor="middle">{t('primer.channel')}</text>
      <Arrow id={id} d={`M134 57 C180 57, 180 ${cy - 10}, ${cx - 80} ${cy - 8}`} />
      <Arrow id={id} d={`M134 173 C180 173, 180 ${cy + 10}, ${cx - 80} ${cy + 8}`} />
      <Arrow id={id} d={`M${cx + 80} ${cy - 8} C${W - 180} ${cy - 10}, ${W - 180} 57, ${W - 136} 57`} />
      <Arrow id={id} d={`M${cx + 80} ${cy + 8} C${W - 180} ${cy + 10}, ${W - 180} 173, ${W - 136} 173`} />
      <text className="primer-verb" x={150} y={cy + 4}>{t('primer.send')}</text>
      <text className="primer-verb" x={W - 150} y={cy + 4} textAnchor="end">{t('primer.subscribe')}</text>
    </svg>
  );
}

const POINTS = ['primer.point1', 'primer.point2', 'primer.point3'] as const;

export function PubSubPrimer({ onClose, inTour = false }: { onClose: () => void; inTour?: boolean }) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!inTour) ref.current?.querySelector<HTMLButtonElement>('button')?.focus();
  }, [inTour]);
  return (
    <section ref={ref} className="primer-card" aria-labelledby="primer-title" data-tour="primer" data-testid="primer"
      onKeyDown={(e) => {
        if (e.key === 'Escape' && !inTour) {
          e.stopPropagation();
          onClose();
        }
      }}>
      <div className="primer-head">
        <h3 id="primer-title">{t('primer.title')}</h3>
        {!inTour && <button type="button" className="modal-x" onClick={onClose} aria-label={t('common.close')}>×</button>}
      </div>
      <PubSubFigure />
      <ol className="primer-points">
        {POINTS.map((key) => <li key={key}>{t(key)}</li>)}
      </ol>
      <p className="muted small">{t('primer.more')}</p>
    </section>
  );
}
