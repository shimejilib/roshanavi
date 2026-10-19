import { useState } from 'react';
import { describeError } from '../api/client';
import type { GraphSnapshot, TrafficEntry } from '../api/types';
import { diagnosticText } from '../graph/diagnosticsText';
import { t } from '../i18n';
import { formatBytes, formatMs, formatPercent, formatRate } from '../lib/format';
import { hzBasisHelp, rateText, windowLabel } from '../timing/timing';
import { isHiddenNode } from '../lib/topics';
import { NotMeasured, setTopicMonitor } from '../traffic/NotMeasured';
import { isNotMeasured, notMeasuredBandwidth, notMeasuredHz, tracedTopicHz } from '../traffic/notMeasured';
import { useAppState } from '../state/AppState';
import { AudioViewer } from './AudioViewer';
import { EchoView } from './EchoView';
import { ImageViewer } from './ImageViewer';
import { useMediaTypes } from '../media/useMediaTypes';
import { NodeLinks } from './NodeLinks';
import { Term } from '../lib/Term';

interface TopicDetailProps {
  topic: string;
  graph: GraphSnapshot | null;
  entry: TrafficEntry | undefined;
}

function Stats({ entry }: { entry: TrafficEntry }) {
  const rows: [string, string][] = [
    [t('traffic.hz'), rateText(entry)],
    [t('traffic.bandwidth'), formatRate(entry.bytes_per_sec)],
    [t('traffic.avgSize'), formatBytes(entry.avg_size)],
    [t('traffic.jitter'), formatMs(entry.jitter_ms)],
    [t('traffic.dropped'), entry.dropped == null ? '—' : `${entry.dropped} (${formatPercent(entry.drop_ratio)})`],
    [t('traffic.latency'), formatMs(entry.latency_ms)],
  ];
  return (
    <>
      <div className="muted small" title={hzBasisHelp(entry.hz_basis)}>
        {windowLabel(entry.window_sec ?? 5)} <span className="info-tip" tabIndex={0}>ⓘ</span>
      </div>
      <dl className="stats">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

/** A topic nobody subscribes to: say so (with 計測する), plus the traced Hz in 詳細計測モード. */
function NotMeasuredStats({ entry }: { entry: TrafficEntry }) {
  return (
    <div data-testid="detail-not-measured">
      <NotMeasured entry={entry} />
      {tracedTopicHz(entry) != null && (
        <dl className="stats">
          <div><dt>{t('traffic.hz')}</dt><dd>{notMeasuredHz(entry)} <span className="muted small">{t('monitor.traced')}</span></dd></div>
          <div><dt>{t('traffic.bandwidth')}</dt><dd>{notMeasuredBandwidth(entry)}</dd></div>
        </dl>
      )}
    </div>
  );
}

function MonitorToggle({ topic, entry }: { topic: string; entry: TrafficEntry }) {
  const [error, setError] = useState<string | null>(null);
  const toggle = async (enabled: boolean) => {
    setError(null);
    try {
      await setTopicMonitor(topic, enabled);
    } catch (err) {
      setError(describeError(err));
    }
  };
  return (
    <div>
      <label className="check" title={t('detail.monitorHelp')}>
        <input type="checkbox" checked={entry.monitored} onChange={(e) => void toggle(e.target.checked)} />
        {t('detail.monitor')}
      </label>
      {error && <p className="error-box">{error}</p>}
    </div>
  );
}

export function TopicDetail({ topic, graph, entry }: TopicDetailProps) {
  const { openInject } = useAppState();
  const info = graph?.topics.find((tp) => tp.name === topic);
  // `ros2 topic echo` and the CLI daemon (_ros2cli_*) are not users of the topic.
  const edges = graph?.edges.filter((e) => e.topic === topic && !isHiddenNode(e.node)) ?? [];
  const diags = graph?.diagnostics.filter((d) => d.topic === topic || d.detail.subscribed === topic) ?? [];
  const { info: media } = useMediaTypes('', true);
  const types = info?.types ?? (entry ? [entry.type] : []);
  const viewKind = types.length === 1 ? media?.supported.find((s) => s.type === types[0])?.kind : undefined;
  return (
    <div className="detail-body">
      <div className="eyebrow">{t('detail.topic')} <Term term="topic" /></div>
      <h3 className="mono" data-testid="detail-title">{topic}</h3>
      <div className="muted small">{t('detail.types')} <Term term="msgType" />: {info?.types.join(', ') ?? entry?.type ?? t('common.unknown')}</div>
      <button type="button" className="primary" onClick={() => openInject(topic)} data-testid="detail-inject">
        {t('detail.inject')}
      </button>
      {diags.length > 0 && (
        <section>
          <h4>{t('detail.diagnostics')}</h4>
          <ul className="diag-list compact">
            {diags.map((d, i) => (
              <li key={i} className={`sev-${d.severity}`}>{diagnosticText(d)}</li>
            ))}
          </ul>
        </section>
      )}
      <NodeLinks title={t('detail.publishers')} edges={edges.filter((e) => e.dir === 'pub')} term="publisher" />
      <NodeLinks title={t('detail.subscribers')} edges={edges.filter((e) => e.dir === 'sub')} term="subscriber" />
      {entry && (
        <section>
          <h4>{t('detail.stats')}</h4>
          <MonitorToggle topic={topic} entry={entry} />
          {entry.monitored && <Stats entry={entry} />}
          {isNotMeasured(entry) && <NotMeasuredStats entry={entry} />}
        </section>
      )}
      {viewKind === 'image' && <ImageViewer key={`img-${topic}`} topic={topic} />}
      {viewKind === 'audio' && <AudioViewer key={`aud-${topic}`} topic={topic} needsRate={!types[0]?.startsWith('audio_common_msgs/')} />}
      {/* Echo only once the topic is on the graph (a just-created input node needs ~1 s). */}
      {info ? (
        <EchoView key={topic} topic={topic} autoStart={(entry?.monitored ?? true) && viewKind !== 'audio'} />
      ) : (
        <p className="muted small">{t('detail.waitingTopic')}</p>
      )}
    </div>
  );
}
