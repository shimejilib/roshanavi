import { DetailPane } from './detail/DetailPane';
import { t } from './i18n';
import { AppStateProvider, useAppState } from './state/AppState';
import { LiveProvider, useLive } from './state/LiveProvider';
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
        <ConnectionStatus />
      </header>
      <div className="workspace">
        <main className="tab-panels">
          {TABS.map((def) => {
            const active = tab === def.id;
            if (!active && !def.keepMounted) return null;
            return (
              <section key={def.id} role="tabpanel" className="tab-panel" hidden={!active}>
                {def.render(active)}
              </section>
            );
          })}
        </main>
        <DetailPane />
      </div>
    </div>
  );
}

export function App() {
  return (
    <LiveProvider>
      <AppStateProvider initialTab={DEFAULT_TAB}>
        <Shell />
      </AppStateProvider>
    </LiveProvider>
  );
}
