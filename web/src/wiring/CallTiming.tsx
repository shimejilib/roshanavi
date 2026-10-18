// 呼ばれ方の図 (docs/design/wiring.md §2): when the function / method runs, as one sentence and a
// small diagram (inputs -> the code; solid = its arrival calls, dashed = only its latest value is
// used; a clock for periodic calls). Several inputs: the join rule can be switched right here.

import { t } from '../i18n';
import type { Timing } from './ports';
import { timingDetail, timingRows, timingText } from './timing';

export interface TriggerChoice {
  /** The spec's trigger value: 'any' or an input topic. */
  value: string;
  label: string;
  disabled?: boolean;
}

interface Props {
  timing: Timing;
  /** Several inputs: the choices of what calls the code (the trigger), and the current one. */
  triggers?: TriggerChoice[];
  trigger?: string;
  onTrigger?: (value: string) => void;
  testId?: string;
}

const ROW = 24;
const W = 300;

function Diagram({ timing, id }: { timing: Timing; id: string }) {
  const rows = timingRows(timing);
  const periodic = timing.mode === 'periodic';
  const n = Math.max(1, rows.length);
  const h = n * ROW + 12;
  const boxY = h / 2 - 14;
  const code = t('wiring.timing.code');
  return (
    <svg className="timing-svg" width={W} height={h} viewBox={`0 0 ${W} ${h}`} role="img" aria-label={timingText(timing)}>
      {periodic ? (
        <g>
          <circle className="clock" cx={40} cy={h / 2} r={11} />
          <path className="clock" d={`M40 ${h / 2 - 7} V${h / 2} H46`} />
          <text x={58} y={h / 2 + 4}>{t('wiring.timing.every', { hz: timing.rateHz ?? '?' })}</text>
          <path className="calls" d={`M120 ${h / 2} H196`} markerEnd={`url(#${id}-arrow)`} />
        </g>
      ) : rows.map((row, i) => {
        const y = 6 + i * ROW + ROW / 2;
        return (
          <g key={row.name}>
            <circle className="in" cx={14} cy={y} r={6} />
            <text x={26} y={y + 4}>{row.name}</text>
            <path className={row.triggers ? 'calls' : 'waits'} d={`M96 ${y} C150 ${y}, 150 ${h / 2}, 196 ${h / 2}`} markerEnd={row.triggers ? `url(#${id}-arrow)` : undefined} />
            <text x={104} y={y - 4} style={{ fontSize: 9 }}>{row.triggers ? t('wiring.timing.calls') : t('wiring.timing.waits')}</text>
          </g>
        );
      })}
      <rect className="fn" x={200} y={boxY} width={92} height={28} rx={6} />
      <text x={246} y={boxY + 18} textAnchor="middle">{code}</text>
      <defs>
        <marker id={`${id}-arrow`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 L10 5 L0 10 z" fill="var(--wire-ok)" />
        </marker>
      </defs>
    </svg>
  );
}

export function CallTiming({ timing, triggers, trigger, onTrigger, testId = 'call-timing' }: Props) {
  const detail = timingDetail(timing);
  return (
    <div className="timing-box" data-testid={testId}>
      <span className="muted small">{t('wiring.timing.title')}</span>
      <span className="timing-sentence" data-testid={`${testId}-text`}>{timingText(timing)}</span>
      {detail && <span className="muted small">{detail}</span>}
      <Diagram timing={timing} id={testId} />
      {timing.mode === 'multi_input' && triggers && onTrigger && (
        <fieldset className="timing-switch">
          <legend className="small">{t('wiring.timing.switch')}</legend>
          {triggers.map((choice) => (
            <label key={choice.value} className="check small">
              <input type="radio" name={`${testId}-trigger`} checked={trigger === choice.value} disabled={choice.disabled}
                onChange={() => onTrigger(choice.value)} data-testid={`${testId}-trigger-${choice.value === 'any' ? 'any' : choice.label}`} />
              {choice.label}
            </label>
          ))}
        </fieldset>
      )}
    </div>
  );
}
