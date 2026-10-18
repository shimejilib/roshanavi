import { expect, test } from '@playwright/test';

// A short scripted tour for the README GIF (about 15 s of video): the live map with the demo
// talker / listener and their edges animated, then an input node created on a new topic and its
// data showing up. Runs against the isolated lab-e2e stack only (see scripts/record_demo_gif.sh).
const TOPIC = '/greeting';
const NODE = 'hello_input';

test.afterEach(async ({ page }) => {
  await page.request.delete(`/api/targets/${NODE}`);
});

test('record the map and an input node being created', async ({ page }) => {
  await page.goto('/');
  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator('[data-id="t:/chatter"]')).toHaveCount(1, { timeout: 30_000 });
  await expect(page.getByTestId('last-update')).toContainText('最終更新');
  // Let the viewer watch the flowing edges first.
  await page.waitForTimeout(4000);

  await page.getByTestId('create-input').click();
  const dialog = page.getByTestId('create-input-dialog');
  await dialog.getByTestId('input-topic').pressSequentially(TOPIC, { delay: 70 });
  await dialog.getByTestId('input-name').fill(NODE);
  await dialog.getByTestId('input-text').fill('hello roshanavi');
  await dialog.getByTestId('input-rate').fill('2');
  await page.waitForTimeout(1200);
  await dialog.getByTestId('input-submit').click();
  await expect(dialog).toHaveCount(0);

  await expect(outline.locator(`[data-id="n:/${NODE}"]`)).toHaveAttribute('data-role', 'dummy', { timeout: 20_000 });
  await expect(page.getByTestId('echo-body')).toContainText('hello roshanavi', { timeout: 15_000 });
  // New nodes can land outside the current view: fit the whole map so the new node is in frame.
  await page.getByRole('button', { name: '全体を表示' }).click();
  await page.waitForTimeout(4000);
});
