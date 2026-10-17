import type { GraphNode } from '../api/types';
import { NodeControlButtons, NodeControlFeedback } from '../graph/NodeControlButtons';
import { useNodeControl } from '../graph/useNodeControl';
import { t } from '../i18n';

/** Right-pane start / stop / restart for the selected map node. */
export function NodeControls({ node }: { node: GraphNode | undefined }) {
  const state = useNodeControl(node);
  return (
    <section data-testid="node-controls">
      <h4>{t('control.title')}</h4>
      <div className="row">
        <NodeControlButtons node={node} state={state} />
      </div>
      <NodeControlFeedback state={state} />
    </section>
  );
}
