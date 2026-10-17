import { SettingsMenu } from './datakind/SettingsMenu';
import { DetailPane } from './detail/DetailPane';
import { DialogHost } from './dialogs/DialogHost';
import { t } from './i18n';
import { ErrorBoundary } from './lib/ErrorBoundary';
import { AppStateProvider, useAppState } from './state/AppState';
import { LiveProvider, useLive } from './state/LiveProvider';
import { RecordingBadge } from './scenarios/ScenariosTab';
import { ScenarioLiveProvider } from './scenarios/ScenarioLive';
import { DEFAULT_TAB, TABS } from './tabs/registry';

function ConnectionStatus() {
  const { status, url } = useLive();
  return (
    <span className={`ws-status ws-${status}`} title={t('ws.tooltip', { url })} data-testid="ws-status" data-status={status}>
      <span className="dot" aria-hidden="true" />
      {t(`ws.${status}`)}
    </span>
  );
}

function Shell() {
  const { tab, setTab } = useAppState();
  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">{t('app.title')}</h1>
        <nav className="tabs" role="tablist">
          {TABS.map((def) => (
            <button
              key={def.id}
              type="button"
              role="tab"
              aria-selected={tab === def.id}
              className={tab === def.id ? 'tab active' : 'tab'}
              onClick={() => setTab(def.id)}
              data-testid={`tab-${def.id}`}
            >
              {t(def.label)}
            </button>
          ))}
        </nav>
        <RecordingBadge onOpen={() => setTab('scenarios')} />
        <SettingsMenu />
        <ConnectionStatus />
      </header>
      <div className={TABS.find((d) => d.id === tab)?.fullWidth ? 'workspace full-width' : 'workspace'}>
        <main className="tab-panels">
          {TABS.map((def) => {
            const active = tab === def.id;
            if (!active && !def.keepMounted) return null;
            return (
              <section key={def.id} role="tabpanel" className="tab-panel" hidden={!active}>
                <ErrorBoundary scope="tab">{def.render(active)}</ErrorBoundary>
              </section>
            );
          })}
        </main>
        {!TABS.find((d) => d.id === tab)?.fullWidth && <DetailPane />}
      </div>
      <ErrorBoundary scope="dialog">
        <DialogHost />
      </ErrorBoundary>
    </div>
  );
}

export function App() {
  return (
    <LiveProvider>
      <ScenarioLiveProvider>
        <AppStateProvider initialTab={DEFAULT_TAB}>
          <Shell />
        </AppStateProvider>
      </ScenarioLiveProvider>
    </LiveProvider>
  );
}
