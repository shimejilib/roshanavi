// "＋ 関数・クラスノードを作る": a function (stateless) or a class (keeps state, has parameters and
// action buttons) of the user's Python code, run as a node (docs/design/nodes.md). The
// 「コードの場所」 panel (docs/design/user-code.md) shows where code is found and why not, edits
// scope B / C and makes a starter package; after 「ひな形を作る」 its function / class is chosen.

import { useState } from 'react';
import type { ScaffoldResult } from '../api/codeTypes';
import { t } from '../i18n';
import { Modal } from '../lib/Modal';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { ClassMode } from './ClassMode';
import { CodeLocationsPanel } from './CodeLocationsPanel';
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
  const [refreshKey, setRefreshKey] = useState(0);
  // A new key remounts the mode form so it starts from the generated package.
  const [scaffolded, setScaffolded] = useState<{ result: ScaffoldResult; nonce: number } | null>(null);
  const title = !editing ? t('function.title') : t(mode === 'class' ? 'class.editTitle' : 'function.editTitle', { name: (editing.spec as { name: string }).name });
  const onScaffolded = (result: ScaffoldResult) => {
    setRefreshKey((k) => k + 1);
    setScaffolded((prev) => ({ result, nonce: (prev?.nonce ?? 0) + 1 }));
  };
  const formKey = `${mode}-${scaffolded?.nonce ?? 0}`;
  const pre = scaffolded?.result;
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
      {!editing && (
        <CodeLocationsPanel onScaffolded={onScaffolded} onChanged={() => setRefreshKey((k) => k + 1)} />
      )}
      {mode === 'class' ? (
        <ClassMode key={formKey} editing={editing} refreshKey={refreshKey} preselect={pre && { module: pre.module, className: pre.class_name }} />
      ) : (
        <FunctionMode key={formKey} topic={topic} editing={editing} refreshKey={refreshKey} preselect={pre && { module: pre.module, fn: pre.function }} />
      )}
    </Modal>
  );
}
