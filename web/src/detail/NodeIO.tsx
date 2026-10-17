// Right pane for a node: "受信しているデータ" and "送信しているデータ" per topic.

import { useMemo, useState } from 'react';
import type { GraphSnapshot, TrafficEntry } from '../api/types';
import { t } from '../i18n';
import { useMediaTypes } from '../media/useMediaTypes';
import { initialOpen, nodeIo, type IoItem } from './nodeIO';
import { TopicIOItem } from './TopicIOItem';

interface Props {
  nodeId: string;
  graph: GraphSnapshot | null;
  traffic: Map<string, TrafficEntry>;
}

function Section({ title, items, open, toggle, kindOf, testId }: {
  title: string;
  items: IoItem[];
  open: Set<string>;
  toggle: (key: string) => void;
  kindOf: (item: IoItem) => 'image' | 'audio' | undefined;
  testId: string;
}) {
  return (
    <section data-testid={testId}>
      <h4>{title}</h4>
      {items.length === 0 ? (
        <p className="muted small">{t('common.none')}</p>
      ) : (
        <ul className="io-list">
          {items.map((item) => (
            <TopicIOItem key={item.key} item={item} open={open.has(item.key)} viewKind={kindOf(item)} onToggle={() => toggle(item.key)} />
          ))}
        </ul>
      )}
    </section>
  );
}

export function NodeIO({ nodeId, graph, traffic }: Props) {
  const io = useMemo(() => nodeIo(graph, nodeId, traffic), [graph, nodeId, traffic]);
  const topicKey = [...io.inputs, ...io.outputs].map((i) => i.key).join('|');
  // Opened set is chosen once per node / topology so later traffic updates never collapse anything.
  const [state, setState] = useState<{ key: string; open: Set<string> }>({ key: '', open: new Set() });
  const open = state.key === `${nodeId}#${topicKey}` ? state.open : initialOpen(io);
  const { info: media } = useMediaTypes('', true);
  const kindOf = (item: IoItem) => (item.types.length === 1 ? media?.supported.find((s) => s.type === item.types[0])?.kind : undefined);
  const toggle = (key: string) => {
    const next = new Set(open);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setState({ key: `${nodeId}#${topicKey}`, open: next });
  };
  return (
    <div className="node-io">
      <p className="muted small">{t('io.note')}</p>
      <Section title={t('io.inputs')} items={io.inputs} open={open} toggle={toggle} kindOf={kindOf} testId="io-inputs" />
      <Section title={t('io.outputs')} items={io.outputs} open={open} toggle={toggle} kindOf={kindOf} testId="io-outputs" />
    </div>
  );
}
