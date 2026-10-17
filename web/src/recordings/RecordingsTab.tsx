import { useCallback, useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { Recording } from '../api/mediaTypes';
import { useLive } from '../state/LiveProvider';
import { RecordingsList } from './RecordingsList';
import { RecordPanel } from './RecordPanel';

export function RecordingsTab() {
  const { live } = useLive();
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    api
      .recordings()
      .then((body) => {
        setRecordings(body.recordings);
        setError(null);
      })
      .catch((err: unknown) => setError(describeError(err)));
  }, []);
  const activeName = live.recording?.name ?? null;
  // Refresh when a recording starts or stops (also auto-stops on low disk space).
  useEffect(reload, [reload, activeName]);
  return (
    <div className="recordings-tab">
      <RecordPanel onChanged={reload} />
      <div>
        {error && <p className="error-box">{error}</p>}
        <RecordingsList recordings={recordings} onChanged={reload} />
      </div>
    </div>
  );
}
