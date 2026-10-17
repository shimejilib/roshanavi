// Generic modal shell: backdrop click and Escape close it, focus moves inside.

import { useEffect, useRef, type ReactNode } from 'react';
import { t } from '../i18n';

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  testId?: string;
}

export function Modal({ title, onClose, children, wide, testId }: ModalProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const first = ref.current?.querySelector<HTMLElement>('input, select, textarea, button:not(.modal-x)');
    (first ?? ref.current)?.focus();
  }, []);
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        ref={ref}
        className={wide ? 'modal wide' : 'modal'}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        data-testid={testId}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            onClose();
          }
        }}
      >
        <div className="modal-head">
          <h3>{title}</h3>
          <button type="button" className="modal-x" onClick={onClose} aria-label={t('common.close')}>×</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
