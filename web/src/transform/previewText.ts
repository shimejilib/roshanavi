// Plain-Japanese text for dry-run errors (codes from the server's evaluator, DESIGN §4.5).

import type { PreviewError } from '../api/transformTypes';
import { tDynamic } from '../i18n';

const CONDITION_PATH = '(condition)';

/** `{path: "data", code: "no_field", params: {field: "x"}}` -> 「フィールド x はありません…」. */
export function previewErrorText(err: PreviewError): string {
  const params = { ...err.params, detail: err.params.detail ?? err.message, message: err.message };
  return tDynamic(`transform.err.${err.code}`, 'transform.err.unknown', params);
}

/** Where an error belongs in the editor: the condition, one output field, or the whole node. */
export function errorPlace(err: PreviewError): 'condition' | 'field' | 'general' {
  if (err.path === CONDITION_PATH) return 'condition';
  if (err.code === 'spec_invalid' || err.code === 'bad_sample' || err.path.startsWith('inputs')) return 'general';
  return 'field';
}

/** Errors grouped by output field path (`linear.x`), for display next to the YAML. */
export function fieldErrors(errors: readonly PreviewError[]): { path: string; text: string }[] {
  return errors.filter((err) => errorPlace(err) === 'field').map((err) => ({ path: err.path, text: previewErrorText(err) }));
}
