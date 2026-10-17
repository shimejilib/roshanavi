import { useEffect, useRef } from 'react';
import { t } from '../i18n';

interface ConfirmDialogProps {
  title: string;
  text: string;
  okLabel: string;
  onOk: () => void;
  onCancel: () => void;
}

/** Small modal confirmation: focus starts on Cancel, Escape cancels. */
export function ConfirmDialog({ title, text, okLabel, onOk, onCancel }: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    cancelRef.current?.focus();
  }, []);
  return (
    <div className="modal-backdrop" onMouseDown={onCancel}>
      <div
        className="modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-text"
        data-testid="confirm-dialog"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === 'Escape' && onCancel()}
      >
        <h3 id="confirm-title">{title}</h3>
        <p id="confirm-text" className="pre-line">{text}</p>
        <div className="row end">
          <button type="button" ref={cancelRef} onClick={onCancel}>{t('common.cancel')}</button>
          <button type="button" className="danger" onClick={onOk} data-testid="confirm-ok">{okLabel}</button>
        </div>
      </div>
    </div>
  );
}
