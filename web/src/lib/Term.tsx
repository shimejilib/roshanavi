// Plain-language explanation of a ROS term as a tooltip (DESIGN §0: no ROS knowledge assumed).
// With children: the words get a dotted underline; without: a small ⓘ.

import type { ReactNode } from 'react';
import { t, type MessageKey } from '../i18n';

export type TermName =
  | 'launch' | 'remap' | 'namespace' | 'parameter' | 'paramsFile' | 'node' | 'topic'
  | 'msgType' | 'workspace' | 'rate' | 'qos' | 'package' | 'executable';

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
