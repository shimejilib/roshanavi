// Top-bar ⚙ 設定: app-wide settings remembered by this browser (詳細設定モード).

import { t } from '../i18n';
import { useAdvancedMode } from './advancedMode';

export function SettingsMenu() {
  const [advanced, setAdvanced] = useAdvancedMode();
  return (
    <details className="settings-menu app-settings">
      <summary data-testid="app-settings">⚙ {t('settings.title')}</summary>
      <div className="settings-items">
        <label className="check">
          <input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} data-testid="advanced-mode" />
          {t('settings.advanced')}
        </label>
        <span className="muted small">{t('settings.advancedHelp')}</span>
      </div>
    </details>
  );
}
