import { Component, type ErrorInfo, type ReactNode } from 'react';
import { t } from '../i18n';

interface Props {
  children: ReactNode;
  /** Where it sits in the screen: only used for the test id and the heading. */
  scope: 'app' | 'map' | 'detail' | 'tab' | 'dialog';
  /** The boundary clears itself when this value changes (e.g. another node was selected). */
  resetKey?: string | number | null;
}

interface State {
  error: Error | null;
}

/** Plain-Japanese message for anything thrown while rendering. */
export function errorText(error: unknown): string {
  if (error instanceof Error) return error.message || error.name;
  return String(error);
}

/**
 * A render error in one part of the screen must never blank the whole app: it is replaced by
 * a short explanation, the error message, and a reload button.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error : new Error(errorText(error)) };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Kept in the console so the report can include the component stack.
    console.error(`[${this.props.scope}] render error:`, error, info.componentStack);
  }

  override componentDidUpdate(prev: Props): void {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  private retry = () => this.setState({ error: null });

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    const { scope } = this.props;
    return (
      <div className={`error-panel error-panel-${scope}`} role="alert" data-testid={`error-boundary-${scope}`}>
        <h3>{t(scope === 'app' ? 'errorBoundary.titleApp' : 'errorBoundary.title')}</h3>
        <p>{t('errorBoundary.lead')}</p>
        <p className="small muted">{t('errorBoundary.detail')}:</p>
        <pre className="error-message mono" data-testid="error-boundary-message">{errorText(error)}</pre>
        <div className="row">
          <button type="button" className="primary" onClick={() => window.location.reload()} data-testid="error-boundary-reload">
            {t('errorBoundary.reload')}
          </button>
          {scope !== 'app' && (
            <button type="button" onClick={this.retry} data-testid="error-boundary-retry">{t('errorBoundary.retry')}</button>
          )}
        </div>
        <p className="small muted">{t('errorBoundary.report')}</p>
      </div>
    );
  }
}
