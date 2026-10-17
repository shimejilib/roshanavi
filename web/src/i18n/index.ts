import { ja, locales, type MessageKey } from './messages';

export type { MessageKey } from './messages';

export type Params = Record<string, string | number>;

let current = 'ja';

export function setLocale(locale: string): void {
  current = locale in locales ? locale : 'ja';
}

/** Interpolate `{name}` placeholders; unknown placeholders are left as-is. */
export function format(template: string, params: Params = {}): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

export function t(key: MessageKey, params?: Params): string {
  const table = locales[current] ?? ja;
  return format(table[key] ?? ja[key], params);
}

/** Lookup for keys built at runtime (e.g. `error.${code}`); falls back to `fallback`. */
export function tDynamic(key: string, fallback: MessageKey, params?: Params): string {
  const known = key in ja ? (key as MessageKey) : fallback;
  return t(known, params);
}
