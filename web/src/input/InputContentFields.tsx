// Content section of the create-input dialog: text / expression / media file / data file.

import type { DataFile } from '../api/types';
import { t, type MessageKey } from '../i18n';
import { Term } from '../lib/Term';
import { contentKindsFor, filesFor, isValueKind, textForKind, type ContentKind, type InputForm } from './inputForm';

interface Props {
  form: InputForm;
  files: DataFile[];
  onChange: (patch: Partial<InputForm>) => void;
}

const VALUE_LABELS: Partial<Record<string, MessageKey>> = {
  bool: 'input.valueBool', numbers: 'input.valueList', bytes: 'input.valueBytes', json: 'input.valueJson',
};

function valueLabel(form: InputForm): MessageKey {
  if (form.content === 'expression') return 'input.expression';
  if (form.kind === 'string') return 'input.text';
  return VALUE_LABELS[form.kind] ?? 'input.value';
}

function MessageFields({ form, onChange }: Pick<Props, 'form' | 'onChange'>) {
  if (isValueKind(form.kind)) {
    const multiline = form.kind === 'json' && form.content !== 'expression';
    return (
      <label>
        {t(valueLabel(form))}
        {form.kind === 'bool' && form.content !== 'expression' ? (
          <select value={['true', 'on', '1'].includes(form.text.toLowerCase()) ? 'true' : 'false'} onChange={(e) => onChange({ text: e.target.value })} data-testid="input-text" data-tour="input-text">
            <option value="true">ON (true)</option>
            <option value="false">OFF (false)</option>
          </select>
        ) : multiline ? (
          <textarea className="yaml" rows={4} spellCheck={false} value={form.text} onChange={(e) => onChange({ text: e.target.value })} data-testid="input-text" data-tour="input-text" />
        ) : (
          <input value={form.text} onChange={(e) => onChange({ text: e.target.value })} data-testid="input-text" data-tour="input-text" />
        )}
        {form.content === 'expression' && <code className="hint small">{t('inject.exprExamples')}</code>}
      </label>
    );
  }
  return (
    <label>
      {t('input.yaml')}
      <textarea className="yaml" rows={8} spellCheck={false} value={form.yaml} onChange={(e) => onChange({ yaml: e.target.value })} data-testid="input-yaml" />
      <span className="muted small">{t('inject.payloadHelp')}</span>
    </label>
  );
}

function FileFields({ form, files, onChange }: Props) {
  const choices = filesFor(form.content, files);
  return (
    <>
      <label>
        {t(form.content === 'media' ? 'input.mediaFile' : 'input.dataFile')}
        <select value={form.source} onChange={(e) => onChange({ source: e.target.value })} data-testid="input-source">
          <option value="">{t('input.chooseFile')}</option>
          {choices.map((f) => (
            <option key={f.path} value={f.path}>{f.path}</option>
          ))}
        </select>
        {choices.length === 0 && <span className="muted small">{t('input.noFiles')}</span>}
      </label>
      <label className="check">
        <input type="checkbox" checked={form.loop} onChange={(e) => onChange({ loop: e.target.checked })} />
        {t('input.loop')}
      </label>
    </>
  );
}

export function InputContentFields({ form, files, onChange }: Props) {
  const pick = (content: ContentKind) => {
    onChange({ content, text: textForKind(form.kind, form.text, content) });
  };
  return (
    <fieldset className="content-kinds">
      <legend>{t('input.content')}</legend>
      <div className="row wrap">
        {contentKindsFor(form.kind).map((kind) => (
          <label key={kind} className="check">
            <input type="radio" name="input-content" checked={form.content === kind} onChange={() => pick(kind)} data-testid={`input-content-${kind}`} />
            {t(kind === 'text' && form.kind !== 'string' && isValueKind(form.kind) ? 'input.content.value' : (`input.content.${kind}` as MessageKey))}
          </label>
        ))}
      </div>
      {form.content === 'text' || form.content === 'expression' ? (
        <MessageFields form={form} onChange={onChange} />
      ) : (
        <FileFields form={form} files={files} onChange={onChange} />
      )}
      <label>
        <span>
          {t('input.rate')} <Term term="rate" />
        </span>
        <input value={form.rateHz} inputMode="decimal" placeholder={form.content === 'media' ? t('input.ratePlaceholderMedia') : ''} onChange={(e) => onChange({ rateHz: e.target.value })} data-testid="input-rate" />
      </label>
    </fieldset>
  );
}
