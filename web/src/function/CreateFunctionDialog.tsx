// "＋ 関数・クラスノードを作る": a function (stateless) or a class (keeps state, has parameters and
// action buttons) of a workspace Python package, run as a node (docs/design/nodes.md).

import { useState } from 'react';
import { t } from '../i18n';
import { Modal } from '../lib/Modal';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { ClassMode } from './ClassMode';
import { FunctionMode } from './FunctionMode';

interface Props {
  topic?: string;
  /** Id of the function or class node to edit (create when absent). */
  functionId?: string;
}

type Mode = 'function' | 'class';

export function CreateFunctionDialog({ topic, functionId }: Props) {
  const { closeDialog } = useAppState();
  const { live } = useLive();
  const editing = live.targets.find((tg) => tg.id === functionId && (tg.kind === 'function' || tg.kind === 'class'));
  const [mode, setMode] = useState<Mode>(editing?.kind === 'class' ? 'class' : 'function');
  const title = !editing ? t('function.title') : t(mode === 'class' ? 'class.editTitle' : 'function.editTitle', { name: (editing.spec as { name: string }).name });
  return (
    <Modal title={title} onClose={closeDialog} wide testId="create-function-dialog">
      {!editing && (
        <fieldset className="node-mode" data-tour="node-mode">
          <legend>{t('node.mode')}</legend>
          <div className="row wrap">
            {(['function', 'class'] as const).map((m) => (
              <label key={m} className="check">
                <input type="radio" name="node-mode" checked={mode === m} onChange={() => setMode(m)} data-testid={`node-mode-${m}`} />
                {t(`node.mode.${m}`)}
              </label>
            ))}
          </div>
          <span className="muted small">{t(`node.modeHelp.${mode}`)}</span>
        </fieldset>
      )}
      {mode === 'class' ? <ClassMode editing={editing} /> : <FunctionMode topic={topic} editing={editing} />}
    </Modal>
  );
}
