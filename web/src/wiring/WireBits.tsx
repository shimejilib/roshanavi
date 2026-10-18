// Small pieces of map wiring: the toolbar of a selected wire (take it off / rewire) and the name
// prompt of a new channel (an output port dropped on a blank part of the map).

import { useEffect, useRef, useState } from 'react';
import { t } from '../i18n';
import { termPair } from '../i18n/glossary';
import { TOPIC_RE } from '../function/functionForm';
import { findPort, type NodePorts } from './ports';

/** A wire (map edge that ends at a port) the user tapped. */
export interface SelectedWire {
  port: string;
  topic: string;
  x: number;
  y: number;
}

export function WireToolbar({ selected, nodes, onClose, onDisconnect, onRewire }: {
  selected: SelectedWire;
  nodes: readonly NodePorts[];
  onClose: () => void;
  onDisconnect: (port: string) => void;
  onRewire: (port: string) => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const found = findPort(nodes, selected.port);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>('button')?.focus();
  }, [selected.port]);
  if (!found) return null;
  const { node, port } = found;
  return (
    <div ref={ref} className="wire-toolbar" role="toolbar" aria-label={t('wiring.toolbar.aria', { topic: selected.topic, name: node.name, port: port.label })}
      style={{ left: selected.x + 8, top: selected.y + 8 }} data-testid="wire-toolbar"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          onClose();
        } else if ((e.key === 'Delete' || e.key === 'Backspace') && port.canUnwire) {
          e.preventDefault();
          onDisconnect(port.key);
        }
      }}>
      <span className="small">{t('wiring.toolbar.wire', { topic: selected.topic, name: node.name, port: port.label })}</span>
      {port.canUnwire ? (
        <button type="button" className="small" onClick={() => onDisconnect(port.key)} data-testid="wire-disconnect">{t('wiring.toolbar.disconnect')}</button>
      ) : (
        <span className="muted small">{t(node.owner === 'transform' ? 'wiring.refuse.unwireTransform' : 'wiring.refuse.unwireDummy')}</span>
      )}
      <button type="button" className="small" onClick={() => onRewire(port.key)} data-testid="wire-rewire">{t('wiring.toolbar.rewire')}</button>
      <button type="button" className="small" onClick={onClose} aria-label={t('common.close')}>×</button>
    </div>
  );
}

export function NewChannelPrompt({ x, y, suggestion, onCreate, onCancel }: {
  x: number;
  y: number;
  suggestion: string;
  onCreate: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(suggestion);
  const ref = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  const valid = TOPIC_RE.test(name.trim());
  return (
    <form className="wire-prompt" style={{ left: x + 8, top: y + 8 }} data-testid="wire-prompt" role="dialog" aria-label={t('wiring.prompt.title', { channel: termPair('topic') })}
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) onCreate(name.trim());
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          onCancel();
        }
      }}>
      <label className="small">
        {t('wiring.prompt.title', { channel: termPair('topic') })}
        <input ref={ref} value={name} onChange={(e) => setName(e.target.value)} spellCheck={false} data-testid="wire-prompt-name" aria-invalid={!valid} />
      </label>
      {!valid && <span className="error-text small" role="alert">{t('wiring.refuse.name', { name: name || '—' })}</span>}
      <div className="row end">
        <button type="button" className="small" onClick={onCancel}>{t('common.cancel')}</button>
        <button type="submit" className="small primary" disabled={!valid} data-testid="wire-prompt-ok">{t('wiring.prompt.create')}</button>
      </div>
    </form>
  );
}
