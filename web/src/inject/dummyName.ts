// Default node name when turning an inject job into a persistent dummy (pure).

/** Suggested node name for a job: `dummy_<last topic segment>`. */
export function suggestDummyName(topic: string | null): string {
  const last = (topic ?? '').split('/').filter(Boolean).pop() ?? 'input';
  const safe = last.replace(/[^A-Za-z0-9_]/g, '_').replace(/^(\d)/, '_$1');
  return `dummy_${safe}`;
}
