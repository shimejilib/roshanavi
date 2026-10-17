import { useEffect, useRef } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';

const WIDTH = 120;
const HEIGHT = 26;

/** Tiny hz history plot (last 60 s, one point per second). */
export function Sparkline({ values, color }: { values: readonly number[]; color: string }) {
  const host = useRef<HTMLDivElement | null>(null);
  const plot = useRef<uPlot | null>(null);

  useEffect(() => {
    if (!host.current) return undefined;
    const opts: uPlot.Options = {
      width: WIDTH,
      height: HEIGHT,
      pxAlign: false,
      cursor: { show: false },
      legend: { show: false },
      select: { show: false, left: 0, top: 0, width: 0, height: 0 },
      scales: { x: { time: false }, y: { range: (_u, _min, max) => [0, Math.max(1, max * 1.1)] } },
      axes: [{ show: false }, { show: false }],
      series: [{}, { stroke: color, width: 1.5, fill: `${color}22`, points: { show: false } }],
    };
    plot.current = new uPlot(opts, [[], []], host.current);
    return () => {
      plot.current?.destroy();
      plot.current = null;
    };
  }, [color]);

  useEffect(() => {
    const xs = values.map((_, i) => i);
    plot.current?.setData([xs, [...values]]);
  }, [values]);

  return <div ref={host} className="sparkline" aria-hidden="true" />;
}
