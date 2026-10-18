import type { Diagnostic } from '../api/types';
import { t } from '../i18n';
import { TourHelp } from '../tour/TourHelp';
import { diagnosticText, warningDiagnostics } from './diagnosticsText';

interface DiagnosticsPanelProps {
  diagnostics: Diagnostic[];
  onFocus: (d: Diagnostic) => void;
}

const SEVERITY_ICON: Record<Diagnostic['severity'], string> = { error: '⛔', warning: '⚠', info: 'ℹ' };

export function DiagnosticsPanel({ diagnostics: all, onFocus }: DiagnosticsPanelProps) {
  // `info` entries (no subscriber / no publisher yet) are not problems: map and detail panes only.
  const diagnostics = warningDiagnostics(all);
  return (
    <section className="diag-panel" aria-labelledby="diag-title" data-tour="diagnostics">
      <h3 id="diag-title">
        {t('diag.title')} <span className="badge">{t('diag.count', { n: diagnostics.length })}</span>
      </h3>
      {diagnostics.length === 0 ? (
        <p className="muted">{t('diag.none')} <TourHelp id="qosFix" /></p>
      ) : (
        <ul className="diag-list">
          {diagnostics.map((d, i) => (
            <li key={`${d.code}:${d.topic}:${d.nodes.join(',')}:${i}`}>
              <button type="button" className={`diag-item sev-${d.severity}`} onClick={() => onFocus(d)} data-tour="diag-item" data-tour-topic={d.topic}>
                <span aria-hidden="true">{SEVERITY_ICON[d.severity]}</span> {diagnosticText(d)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
