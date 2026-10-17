import { t, type MessageKey } from '../i18n';
import type { Palette } from './style';

interface Swatch {
  key: MessageKey;
  className: string;
  color: string;
}

export function Legend({ palette }: { palette: Palette }) {
  const items: Swatch[] = [
    { key: 'graph.legend.mine', className: 'sw-node', color: palette.roles.mine },
    { key: 'graph.legend.dependency', className: 'sw-node', color: palette.roles.dependency },
    { key: 'graph.legend.dummy', className: 'sw-node', color: palette.roles.dummy },
    { key: 'graph.legend.transform', className: 'sw-node', color: palette.roles.transform },
    { key: 'graph.legend.function', className: 'sw-node', color: palette.roles.function },
    { key: 'graph.legend.other', className: 'sw-node', color: palette.roles.other },
    { key: 'graph.legend.topic', className: 'sw-topic', color: palette.topicBorder },
    { key: 'graph.legend.stale', className: 'sw-line dashed', color: palette.stale },
    { key: 'graph.legend.drops', className: 'sw-line', color: palette.drops },
    { key: 'graph.legend.notMonitored', className: 'sw-line dotted', color: palette.stale },
    { key: 'graph.legend.qosBad', className: 'sw-line dashed', color: palette.qosBad },
    { key: 'res.load.mid', className: 'sw-glow', color: palette.loadMid },
    { key: 'res.load.high', className: 'sw-glow', color: palette.loadHigh },
  ];
  return (
    <ul className="legend" aria-label="legend" data-tour="legend">
      {items.map((item) => (
        <li key={item.key}>
          <span className={`swatch ${item.className}`} style={{ color: item.color }} />
          {t(item.key)}
        </li>
      ))}
    </ul>
  );
}
