// Plain-language explanation of a ROS term as a tooltip (docs/overview/vision.md: no ROS knowledge assumed).
// With children: the words get a dotted underline; without: a small ⓘ.

import type { ReactNode } from 'react';
import { t, type MessageKey } from '../i18n';
import type { GlossaryId } from '../i18n/glossary';

/** Every glossary term has a tooltip (i18n/glossary.ts is the one source). */
export type TermName = GlossaryId;

export function termHelp(term: TermName): string {
  return t(`term.${term}` as MessageKey);
}

export function Term({ term, children }: { term: TermName; children?: ReactNode }) {
  const help = termHelp(term);
  if (children) {
    return (
      <span className="term" title={help} tabIndex={0} data-term={term}>
        {children}
      </span>
    );
  }
  return (
    <span className="info-tip" title={help} aria-label={help} tabIndex={0} data-term={term}>
      ⓘ
    </span>
  );
}
