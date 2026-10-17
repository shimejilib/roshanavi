// Guidance when the workspace has none of the user's own packages yet.

import { t } from '../i18n';
import { Term } from '../lib/Term';

export function WorkspaceHelp({ root }: { root: string | undefined }) {
  return (
    <div className="notice-box small" data-testid="workspace-help">
      <strong>{t('wsHelp.title')}</strong> <Term term="workspace" />
      <p>{t('wsHelp.body', { root: root ?? '?' })}</p>
      <ul>
        <li>{t('wsHelp.native')}</li>
        <li>{t('wsHelp.docker')}</li>
        <li>{t('wsHelp.build')}</li>
      </ul>
    </div>
  );
}
