import { defineConfig, devices } from '@playwright/test';

// Smoke E2E against a running stack: `docker compose up -d lab demo` (UI on :8080).
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: process.env.ROSHANAVI_URL ?? 'http://localhost:8080',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  // Fake microphone (beep) and camera (test pattern) without permission prompts.
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, permissions: ['microphone', 'camera'], launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] } } }],
});
