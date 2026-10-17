import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Requires `docker compose up -d lab demo` (talker/listener on /chatter).
const SHOTS = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
const MESSAGE = `e2e hello ${Date.now()}`;

test('map shows the demo, inject once, echo receives it', async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');

  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator('[data-id="t:/chatter"]')).toHaveCount(1, { timeout: 15_000 });
  await expect(outline.locator('[data-id="n:/talker"]')).toHaveCount(1);
  await expect(outline.locator('[data-id="n:/listener"]')).toHaveCount(1);
  await expect(outline.locator('[data-id="e:pub:/talker:/chatter"]')).toContainText('Hz', { timeout: 15_000 });
  await page.waitForTimeout(1500); // let the layout animation and particles settle
  await page.screenshot({ path: `${SHOTS}graph.png` });

  await page.getByTestId('tab-traffic').click();
  const row = page.locator('tr[data-topic="/chatter"]');
  await expect(row).toBeVisible();
  await page.screenshot({ path: `${SHOTS}traffic.png` });

  // Select /chatter: the detail pane starts echoing it.
  await row.click();
  await expect(page.getByTestId('detail-title')).toHaveText('/chatter');
  await expect(page.getByTestId('echo-body')).toContainText('Hello World', { timeout: 10_000 });

  // "Inject to this topic" -> Inject tab with topic and type prefilled.
  await page.getByTestId('detail-inject').click();
  await expect(page.getByTestId('inject-topic')).toHaveValue('/chatter');
  await expect(page.getByTestId('inject-type')).toHaveValue('std_msgs/msg/String');
  await expect(page.getByTestId('inject-yaml')).toHaveValue(/data:/);
  await page.getByTestId('inject-yaml').fill(`data: "${MESSAGE}"`);
  await page.getByTestId('inject-start').click();
  await expect(page.getByRole('status')).toContainText('開始しました');
  await expect(page.getByTestId('echo-body')).toContainText(MESSAGE, { timeout: 5_000 });
  await page.screenshot({ path: `${SHOTS}inject-echo.png` });
});

test('a periodic injection appears as a dummy source with a diagnostic', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('tab-inject').click();
  await page.getByTestId('inject-topic').fill('/chater');
  await page.getByTestId('inject-type').fill('std_msgs/msg/String');
  await expect(page.getByTestId('inject-yaml')).toHaveValue(/data:/);
  await page.getByTestId('inject-yaml').fill('data: "typo ${i}"');
  await page.getByLabel('周期的に').check();
  await page.getByLabel('周期 (Hz)').fill('5');
  await page.getByTestId('inject-start').click();
  await expect(page.getByRole('status')).toContainText('開始しました');

  await page.getByTestId('tab-graph').click();
  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator('li[data-id^="n:dummy:"]')).toHaveCount(1, { timeout: 10_000 });
  await expect(page.locator('.diag-item', { hasText: '/chater は送信されていますが' })).toBeVisible({ timeout: 10_000 });
  await page.locator('.diag-item', { hasText: '/chater' }).click();
  await expect(page.getByTestId('detail-title')).toHaveText('/chater');
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${SHOTS}graph-dummy-diagnostic.png` });

  await page.getByTestId('tab-inject').click();
  const running = page.getByTestId('job').filter({ hasText: '/chater' }).filter({ hasText: '実行中' });
  await running.getByRole('button', { name: '停止' }).click();
  await expect(running).toHaveCount(0, { timeout: 5_000 });
});

test('talker + dummy on /chatter: each publisher edge shows its own rate', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('tab-inject').click();
  await page.getByTestId('inject-topic').fill('/chatter');
  await expect(page.getByTestId('inject-yaml')).toHaveValue(/data:/);
  await page.getByTestId('inject-yaml').fill('data: "split ${i}"');
  await page.getByLabel('周期的に').check();
  await page.getByLabel('周期 (Hz)').fill('1');
  await page.getByTestId('inject-start').click();
  await expect(page.getByRole('status')).toContainText('開始しました');

  await page.getByTestId('tab-graph').click();
  const outline = page.getByTestId('graph-outline');
  // talker (1 Hz) is estimated from the total (≈2 Hz) minus the dummy's counted 1 Hz.
  await expect(outline.locator('[data-id="e:pub:/talker:/chatter"]')).toContainText(/(0\.[89]\d|1\.[01]\d) Hz.*推定/, { timeout: 20_000 });
  await expect(outline.locator('li[data-id^="e:pub:dummy:"][data-id$=":/chatter"]')).toContainText(/(0\.9\d|1\.0\d) Hz/);
  await expect(outline.locator('[data-id="t:/chatter"]')).toContainText('送信元 2');

  await page.getByTestId('tab-inject').click();
  const running = page.getByTestId('job').filter({ hasText: '/chatter' }).filter({ hasText: '実行中' });
  await running.getByRole('button', { name: '停止' }).click();
  await expect(running).toHaveCount(0, { timeout: 5_000 });
});
