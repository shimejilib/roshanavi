import type { GraphEdge } from '../api/types';
import { t } from '../i18n';
import { Term, type TermName } from '../lib/Term';
import { useAppState } from '../state/AppState';

function qosText(e: GraphEdge): string {
  const base = `${e.qos.reliability.toUpperCase()} / ${e.qos.durability.toUpperCase()}`;
  // Discovery often reports depth 0 (unknown); only show a real value.
  return e.qos.depth ? `${base} / depth ${e.qos.depth}` : base;
}

/** List of endpoints; clicking one selects that node or topic. */
export function NodeLinks({ title, edges, showTopic = false, term }: { title: string; edges: GraphEdge[]; showTopic?: boolean; term?: TermName }) {
  const { select } = useAppState();
  return (
    <section>
      <h4>{title}{term && <> <Term term={term} /></>}</h4>
      {edges.length === 0 ? (
        <p className="muted small">{t('common.none')}</p>
      ) : (
        <ul className="link-list">
          {edges.map((e) => (
            <li key={`${e.dir}:${e.node}:${e.topic}`}>
              <button
                type="button"
                className="link mono"
                onClick={() => select(showTopic ? { kind: 'topic', id: e.topic } : { kind: 'node', id: e.node })}
              >
                {showTopic ? e.topic : e.node}
              </button>
              <div className="muted small" title={t('detail.qos')}>{qosText(e)}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
