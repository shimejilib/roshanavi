import { defineConfig, devices } from '@playwright/test';

// Smoke E2E against a running stack: `docker compose up -d lab demo` (UI on :6871).
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  // One worker: some tests change the shared lab (the first-run guide empties the launch list).
  workers: 1,
  use: {
    baseURL: process.env.ROSHANAVI_URL ?? 'http://localhost:6871',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  // Fake microphone (beep) and camera (test pattern) without permission prompts.
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, permissions: ['microphone', 'camera'], launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] } } }],
});
