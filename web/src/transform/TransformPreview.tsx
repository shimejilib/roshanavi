// Live preview: latest input message (left) and the server-computed output (right).

import { t } from '../i18n';
import { previewErrorText, errorPlace } from './previewText';
import type { PreviewState } from './useTransformPreview';

const MAX_CHARS = 6000;

interface Props {
  samples: Record<string, Record<string, unknown>>;
  aliases: readonly string[];
  preview: PreviewState;
}

function json(value: unknown): string {
  const text = JSON.stringify(value, null, 2) ?? '';
  return text.length > MAX_CHARS ? `${text.slice(0, MAX_CHARS)}…` : text;
}

function OutputPane({ preview }: { preview: PreviewState }) {
  const { result, formError, requestError, busy } = preview;
  if (formError) return <p className="muted small">{t('transform.previewCannot', { message: formError })}</p>;
  if (requestError) return <p className="error-box">{requestError}</p>;
  if (!result) return <p className="muted small">{busy ? t('transform.previewBusy') : ''}</p>;
  const general = result.errors.filter((err) => errorPlace(err) !== 'field');
  const fields = result.errors.filter((err) => errorPlace(err) === 'field');
  return (
    <>
      {general.map((err) => <p className="error-box" key={`${err.path}-${err.code}`} data-testid="transform-preview-error">{previewErrorText(err)}</p>)}
      {fields.length > 0 && (
        <ul className="field-errors" data-testid="transform-field-errors">
          {fields.map((err) => (
            <li key={`${err.path}-${err.code}`} className="error-text small">
              {t('transform.fieldError', { path: err.path, text: previewErrorText(err) })}
            </li>
          ))}
        </ul>
      )}
      {result.ok && !result.passed && <p className="warn-text small">{t('transform.previewFiltered')}</p>}
      {result.relay && <p className="muted small">{t('transform.previewRelay')}</p>}
      {result.output && <pre className="echo-body" data-testid="transform-preview-output">{json(result.output)}</pre>}
    </>
  );
}

export function TransformPreview({ samples, aliases, preview }: Props) {
  return (
    <section className="transform-preview" aria-label={t('transform.preview')}>
      <div>
        <h4>{t('transform.previewInput')}</h4>
        {aliases.map((alias) => (
          <div key={alias}>
            {aliases.length > 1 && <div className="mono small">{alias}</div>}
            {samples[alias] ? (
              <pre className="echo-body" data-testid={`transform-preview-input-${alias}`}>{json(samples[alias])}</pre>
            ) : (
              <p className="muted small">{t('transform.previewWaiting')}</p>
            )}
          </div>
        ))}
      </div>
      <div>
        <h4>{t('transform.previewOutput')}</h4>
        <OutputPane preview={preview} />
      </div>
    </section>
  );
}
