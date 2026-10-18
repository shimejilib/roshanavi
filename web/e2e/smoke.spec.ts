import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { CHATTER_KIND_LABEL } from './helpers';

// Requires `docker compose up -d lab demo`: lab starts the demo project's talker / listener
// (/chatter, roshanavi-owned); the demo container adds external_talker on /external/chatter.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const MESSAGE = `e2e hello ${Date.now()}`;

test('map shows the demo, inject once, echo receives it', async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');

  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator('[data-id="t:/chatter"]')).toHaveCount(1, { timeout: 15_000 });
  await expect(outline.locator('[data-id="n:/talker"]')).toHaveCount(1);
  await expect(outline.locator('[data-id="n:/listener"]')).toHaveCount(1);
  await expect(outline.locator('[data-id="n:/talker"]')).toHaveAttribute('data-role', 'mine', { timeout: 15_000 });
  await expect(outline.locator('[data-id="n:/external_talker"]')).toHaveAttribute('data-role', 'other');
  await expect(outline.locator('[data-id="t:/external/chatter"]')).toHaveCount(1);
  await expect(outline.locator('[data-id="e:pub:/talker:/chatter"]')).toContainText('Hz', { timeout: 15_000 });
  await page.waitForTimeout(1500); // let the layout animation and particles settle
  await page.screenshot({ path: `${SHOTS}graph.png` });

  await page.getByTestId('tab-traffic').click();
  const row = page.locator('tr[data-topic="/chatter"]');
  await expect(row).toBeVisible();
  await page.screenshot({ path: `${SHOTS}traffic.png` });

  // Per (node × topic × direction): expand /chatter, then the node view.
  await page.getByTestId('expand-/chatter').click();
  await expect(page.getByTestId('endpoint-/chatter-pub-/talker')).toContainText('Hz', { timeout: 10_000 });
  await expect(page.getByTestId('endpoint-/chatter-sub-/listener')).toContainText('理論値');
  await page.screenshot({ path: `${SHOTS}traffic-endpoints.png` });
  await page.getByTestId('traffic-view-node').click();
  await expect(page.getByTestId('node-traffic-/listener-sub-/chatter')).toContainText('理論値');
  await expect(page.getByTestId('node-traffic-/talker-pub-/chatter')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}traffic-by-node.png` });
  await page.getByTestId('traffic-view-topic').click();

  // Select /chatter: the detail pane starts echoing it.
  await row.click();
  await expect(page.getByTestId('detail-title')).toHaveText('/chatter');
  await expect(page.getByTestId('echo-body')).toContainText('Hello World', { timeout: 10_000 });

  // "Inject to this topic" -> Inject tab with topic and type prefilled.
  await page.getByTestId('detail-inject').click();
  await expect(page.getByTestId('inject-topic')).toHaveValue('/chatter');
  // An existing topic: no type to choose, the detected kind and ROS type are shown.
  await expect(page.getByTestId('inject-type-detected')).toContainText(CHATTER_KIND_LABEL);
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
  await page.getByTestId('inject-type-kind').selectOption('string');
  await expect(page.getByTestId('inject-yaml')).toHaveValue(/data:/);
  await page.getByTestId('inject-yaml').fill('data: "typo ${i}"');
  await page.getByLabel('周期的に').check();
  await page.getByLabel('周期 (Hz)').fill('5');
  await page.getByTestId('inject-start').click();
  await expect(page.getByRole('status')).toContainText('開始しました');

  await page.getByTestId('tab-graph').click();
  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator('li[data-id^="n:dummy:"]')).toHaveCount(1, { timeout: 10_000 });
  await expect(page.locator('.diag-item', { hasText: '/chater (送信) と /chatter (受信) は名前が似ていて' })).toBeVisible({ timeout: 10_000 });
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
  // The C++ probe counts each publisher (gid) on its own: talker is measured, not estimated.
  const talkerEdge = outline.locator('[data-id="e:pub:/talker:/chatter"]');
  await expect(talkerEdge).toContainText(/(0\.9\d|1\.0\d) Hz/, { timeout: 20_000 });
  await expect(talkerEdge).not.toContainText('推定');
  await expect(outline.locator('li[data-id^="e:pub:dummy:"][data-id$=":/chatter"]')).toContainText(/(0\.9\d|1\.0\d) Hz/);
  await expect(outline.locator('[data-id="t:/chatter"]')).toContainText('送信元 2');

  await page.getByTestId('tab-traffic').click();
  await expect(page.getByTestId('traffic-measurement')).toContainText('C++ 計測ノード');
  await page.getByTestId('expand-/chatter').click();
  const talker = page.getByTestId('endpoint-/chatter-pub-/talker');
  await expect(talker).toContainText(/(0\.9\d|1\.0\d) Hz/, { timeout: 15_000 });
  await expect(talker).toContainText('実測');
  const dummy = page.locator('[data-testid^="endpoint-/chatter-pub-dummy:"]');
  await expect(dummy).toContainText(/(0\.9\d|1\.0\d) Hz/);

  await page.getByTestId('tab-inject').click();
  const running = page.getByTestId('job').filter({ hasText: '/chatter' }).filter({ hasText: '実行中' });
  await running.getByRole('button', { name: '停止' }).click();
  await expect(running).toHaveCount(0, { timeout: 5_000 });
});
