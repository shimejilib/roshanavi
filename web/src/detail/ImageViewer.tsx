import { useEffect, useState } from 'react';
import { ApiError, describeError } from '../api/client';
import { t } from '../i18n';
import { openViewer } from '../media/viewerSocket';

/** Latest image of an Image / CompressedImage topic (server: <= 10 fps, <= 640 px wide). */
export function ImageViewer({ topic }: { topic: string }) {
  const [running, setRunning] = useState(true);
  const [src, setSrc] = useState<string | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!running) return undefined;
    setError(null);
    let current: string | null = null;
    const close = openViewer(topic, '', {
      onMeta: () => undefined,
      onData: (meta, data) => {
        const url = URL.createObjectURL(new Blob([data], { type: 'image/jpeg' }));
        if (current) URL.revokeObjectURL(current);
        current = url;
        setSrc(url);
        setSize({ w: meta.width ?? 0, h: meta.height ?? 0 });
      },
      onError: (code, message) => setError(describeError(new ApiError(code, message, 400))),
    });
    return () => {
      close();
      if (current) URL.revokeObjectURL(current);
      setSrc(null);
    };
  }, [topic, running]);

  return (
    <section className="viewer" aria-labelledby="image-viewer-title">
      <h4 id="image-viewer-title">
        {t('viewer.image')}{' '}
        <button type="button" onClick={() => setRunning(!running)}>{running ? t('viewer.stop') : t('viewer.start')}</button>
      </h4>
      {error && <p className="error-box">{error}</p>}
      {running && !src && !error && <p className="muted">{t('viewer.waiting')}</p>}
      {src && (
        <>
          <img src={src} alt={topic} className="viewer-image" data-testid="image-viewer" />
          {size && <div className="muted small">{t('viewer.imageInfo', { w: size.w, h: size.h })}</div>}
        </>
      )}
    </section>
  );
}
