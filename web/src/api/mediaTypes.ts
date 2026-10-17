// Shapes of the media / capture / recording API (docs/DESIGN.md §4.11-§4.12).

export type MediaKind = 'image' | 'audio';

export interface SupportedType {
  type: string;
  kind: MediaKind;
}

export interface MediaTypeInfo {
  supported: SupportedType[];
  topic?: string;
  endpoints?: { subscribers: string[]; publishers: string[] };
  detected?: string | null;
  detected_supported?: boolean;
}

/** `media` field of POST /api/inject (mode "media"); omitted keys use server defaults. */
export interface MediaOptions {
  kind?: 'auto' | 'image' | 'video' | 'audio';
  encoding?: 'rgb8' | 'bgr8' | 'mono8';
  format?: 'jpeg' | 'png';
  frame_id?: string;
  width?: number;
  height?: number;
  camera_info?: boolean;
  camera_info_topic?: string;
  calibration?: string;
  start_sec?: number;
  end_sec?: number;
  sample_rate?: number;
  channels?: number;
  chunk_samples?: number;
  jitter_ms?: number;
  drop_ratio?: number;
  audio_info?: boolean;
  audio_info_topic?: string;
}

/** First message on /ws/capture. */
export interface CaptureStartMessage {
  kind: 'audio' | 'camera';
  topic: string;
  type?: string;
  frame_id?: string;
  sample_rate?: number;
  channels?: number;
  chunk_samples?: number;
  fps?: number;
  encoding?: 'rgb8' | 'bgr8' | 'mono8';
  camera_info?: boolean;
  audio_info?: boolean;
}

export type CaptureEvent =
  | { event: 'ready'; job_id: string; topic: string; type: string; companions: string[] }
  | { event: 'stats'; sent: number; dropped: number }
  | { event: 'stopped' }
  | { error: { code: string; message: string } };

export interface DiskState {
  level: 'ok' | 'warn' | 'stop';
  free_bytes: number;
  total_bytes: number;
  free_pct: number;
}

export interface RecordingStatus {
  name: string;
  path: string;
  topics: string[];
  started_at: number;
  elapsed_sec?: number;
  size?: number;
  warning?: boolean;
  disk?: DiskState;
  stop_reason?: 'user' | 'disk_full' | 'exited' | 'shutdown';
  error?: string;
}

export interface RecordingTopic {
  name: string;
  type: string;
  count: number;
}

export interface Recording {
  name: string;
  path: string;
  size: number;
  active: boolean;
  finalized: boolean;
  duration_sec: number | null;
  started_at: number | null;
  message_count: number | null;
  topics: RecordingTopic[];
}

export interface RecordingsResponse {
  recordings: Recording[];
  active: RecordingStatus | null;
  last: RecordingStatus | null;
  thresholds: { warn_mb: number; warn_pct: number; stop_mb: number; stop_pct: number };
}
