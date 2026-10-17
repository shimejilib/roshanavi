import { useEffect, useMemo, useRef, useState } from 'react';
import { t } from '../i18n';
import { filterLines, lineLevel } from './logs';
import { useLogStream } from './useLogStream';

const BUILD_LOG_ID = '_build';

export function LogViewer({ logId }: { logId: string | null }) {
  const { lines, error, clear } = useLogStream(logId);
  const [query, setQuery] = useState('');
  const [problemsOnly, setProblemsOnly] = useState(false);
  const [follow, setFollow] = useState(true);
  const bodyRef = useRef<HTMLPreElement | null>(null);
  const shown = useMemo(() => filterLines(lines, { query, problemsOnly }), [lines, query, problemsOnly]);

  useEffect(() => {
    const body = bodyRef.current;
    if (follow && body) body.scrollTop = body.scrollHeight;
  }, [shown, follow]);

  if (!logId) return <section className="log-viewer empty"><p className="muted">{t('launcher.log.pick')}</p></section>;
  const title = logId === BUILD_LOG_ID ? t('launcher.log.buildTitle') : t('launcher.log.title', { id: logId });
  return (
    <section className="log-viewer" aria-label={title} data-testid="log-viewer">
      <div className="log-toolbar">
        <h3>{title}</h3>
        <input type="search" placeholder={t('launcher.log.filter')} value={query} onChange={(e) => setQuery(e.target.value)} />
        <label className="check small">
          <input type="checkbox" checked={problemsOnly} onChange={(e) => setProblemsOnly(e.target.checked)} />
          {t('launcher.log.problems')}
        </label>
        <label className="check small">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          {t('launcher.log.follow')}
        </label>
        <button type="button" onClick={clear}>{t('launcher.log.clear')}</button>
        <span className="muted small">{t('launcher.log.count', { shown: shown.length, total: lines.length })}</span>
      </div>
      {error && <p className="error-box" role="alert">{error}</p>}
      <pre className="log-body" ref={bodyRef} data-testid="log-body">
        {shown.length === 0 && <span className="muted">{t('launcher.log.empty')}</span>}
        {shown.map((line) => (
          <div key={line.seq} className={`log-line lvl-${lineLevel(line)} stream-${line.stream}`}>
            {line.text}
          </div>
        ))}
      </pre>
    </section>
  );
}
