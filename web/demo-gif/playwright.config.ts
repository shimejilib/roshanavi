import { defineConfig, devices } from '@playwright/test';

// Records the README demo GIF's source video (webm) against the isolated lab-e2e stack.
// Not part of the regular E2E run (`web/playwright.config.ts` only looks in `web/e2e`).
// Use scripts/record_demo_gif.sh.
const BASE_URL = process.env.ROSHANAVI_URL ?? 'http://localhost:6871';
const SIZE = { width: 1280, height: 720 };

// Skip the first-launch tutorial card so the map is what the viewer sees.
const TOUR_DISMISSED = { cookies: [], origins: [{ origin: new URL(BASE_URL).origin, localStorage: [{ name: 'roshanavi.tour.v1', value: JSON.stringify({ completed: [], welcomeSeen: true, run: null }) }] }] };

export default defineConfig({
  testDir: '.',
  testMatch: 'record.spec.ts',
  outputDir: process.env.DEMO_GIF_OUT ?? './out',
  timeout: 90_000,
  retries: 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: BASE_URL,
    storageState: TOUR_DISMISSED,
    viewport: SIZE,
    video: { mode: 'on', size: SIZE },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: SIZE } }],
});
