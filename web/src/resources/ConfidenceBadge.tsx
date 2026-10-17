// 「推定」 / shared-process / whole-target badges next to resource figures.

import type { Confidence } from '../api/resourceTypes';
import { t } from '../i18n';

interface Props {
  confidence: Confidence;
  shared?: readonly string[];
  scope?: 'process' | 'target';
  target?: string | null;
}

export function ConfidenceBadge({ confidence, shared = [], scope = 'process', target = null }: Props) {
  return (
    <>
      {confidence !== 'exact' && (
        <span className="badge res-estimated" title={t('res.estimatedHelp')} data-testid="res-estimated">
          {t('res.estimated')}
        </span>
      )}
      {shared.length > 0 && (
        <span className="badge" title={t('res.sharedHelp', { nodes: shared.join(', ') })}>
          {t('res.shared', { n: shared.length + 1 })}
        </span>
      )}
      {scope === 'target' && (
        <span className="badge" title={t('res.targetScopeHelp', { target: target ?? '?' })}>
          {t('res.targetScope')}
        </span>
      )}
    </>
  );
}
