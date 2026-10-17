import { defineConfig, devices } from '@playwright/test';

// E2E against the isolated lab-e2e stack: run scripts/e2e.sh.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  // One worker: tests share one lab-e2e (the first-run guide empties its launch list).
  workers: 1,
  use: {
    baseURL: process.env.ROSHANAVI_URL ?? 'http://localhost:6871',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  // Fake microphone (beep) and camera (test pattern) without permission prompts.
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, permissions: ['microphone', 'camera'], launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] } } }],
});
