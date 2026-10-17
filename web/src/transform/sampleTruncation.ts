// The echo view truncates long arrays (`{_truncated, length, head}`) and long strings (`…(+N chars)`).
// A transform computed on such a copy can differ from the running node (#10): detect it.

const TRUNCATED_STRING = /\.\.\.\(\+\d+ chars\)$/;

/** True when `value` (a message as the echo view shows it) has an array or string that was cut short. */
export function hasTruncation(value: unknown): boolean {
  const stack: unknown[] = [value];
  while (stack.length > 0) {
    const current = stack.pop();
    if (typeof current === 'string') {
      if (TRUNCATED_STRING.test(current)) return true;
    } else if (Array.isArray(current)) {
      stack.push(...current);
    } else if (typeof current === 'object' && current !== null) {
      if ((current as { _truncated?: unknown })._truncated === true) return true;
      stack.push(...Object.values(current));
    }
  }
  return false;
}

type Sample = Record<string, unknown>;

/** Per topic the whole message when the server sent one, else what the echo view had. */
export function preferFull(display: Readonly<Record<string, Sample>>, full: Readonly<Record<string, Sample>>): Record<string, Sample> {
  return Object.fromEntries(Object.entries(display).map(([topic, msg]) => [topic, full[topic] ?? msg]));
}
