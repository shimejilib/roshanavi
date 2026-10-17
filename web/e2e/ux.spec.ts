import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { clickElement, rightClickBlank, rightClickNode } from './helpers';

// P4.5a flows (requires `docker compose up -d lab demo`): map menus, input nodes,
// parameters, node I/O pane and the Launcher's first-run guide.
const SHOTS = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
const INPUT_ID = 'e2e_input';

async function openMap(page: Page) {
  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');
  await expect(page.getByTestId('graph-outline').locator('[data-id="n:/talker"]')).toHaveCount(1, { timeout: 20_000 });
  await page.waitForTimeout(1500); // layout animation
}

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterEach(async ({ page }) => {
  await page.request.delete(`/api/targets/${INPUT_ID}`);
});

test('blank-area menu -> create an input node on a new topic -> it appears on the map', async ({ page }) => {
  await openMap(page);
  await expect(page.getByTestId('last-update')).toContainText('最終更新');
  await rightClickBlank(page);
  const menu = page.getByTestId('map-menu');
  await expect(menu).toHaveAttribute('data-kind', 'blank');
  await page.screenshot({ path: `${SHOTS}menu-blank.png` });
  await menu.getByTestId('menu-addTopic').click();

  const dialog = page.getByTestId('create-input-dialog');
  await dialog.getByTestId('input-topic').fill('/e2e_new_topic');
  await expect(dialog).toContainText('新しいトピックです');
  await dialog.getByTestId('input-name').fill(INPUT_ID);
  await dialog.getByTestId('input-content-expression').check();
  await dialog.getByTestId('input-rate').fill('2');
  await page.screenshot({ path: `${SHOTS}create-input-dialog.png` });
  await dialog.getByTestId('input-submit').click();
  await expect(dialog).toHaveCount(0);

  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator(`[data-id="n:/${INPUT_ID}"]`)).toHaveAttribute('data-role', 'dummy', { timeout: 20_000 });
  await expect(outline.locator('[data-id="t:/e2e_new_topic"]')).toHaveCount(1);
  await expect(page.getByTestId('detail-title')).toHaveText('/e2e_new_topic');
  await expect(page.getByTestId('echo-body')).toContainText('hello', { timeout: 10_000 });

  // The input node's own menu: pause / edit / export are available.
  await page.waitForTimeout(1500);
  await rightClickNode(page, `n:/${INPUT_ID}`);
  await expect(page.getByTestId('menu-pause')).toBeEnabled();
  await expect(page.getByTestId('menu-editDummy')).toBeEnabled();
  await page.screenshot({ path: `${SHOTS}menu-input-node.png` });
  await page.keyboard.press('Escape');
});

test('node menu: parameters of talker; external node is read-only', async ({ page }) => {
  await openMap(page);
  await rightClickNode(page, 'n:/talker');
  const menu = page.getByTestId('map-menu');
  await expect(menu.getByTestId('menu-stop')).toBeEnabled();
  await expect(menu.getByTestId('menu-buildRestart')).toBeDisabled();
  await page.screenshot({ path: `${SHOTS}menu-node.png` });
  await menu.getByTestId('menu-params').click();
  const dialog = page.getByTestId('params-dialog');
  await expect(dialog.locator('[data-param="use_sim_time"]')).toBeVisible({ timeout: 10_000 });
  await expect(dialog.getByTestId('param-input-use_sim_time')).toHaveValue('false');
  await page.screenshot({ path: `${SHOTS}params-dialog.png` });
  await page.keyboard.press('Escape');

  await rightClickNode(page, 'n:/external_talker');
  await expect(page.getByTestId('map-menu').getByTestId('menu-stop')).toBeDisabled();
  await page.getByTestId('map-menu').getByTestId('menu-params').click();
  await expect(page.getByTestId('params-external')).toContainText('閲覧のみ', { timeout: 10_000 });
  await expect(page.getByTestId('param-value-use_sim_time')).toBeVisible();
  await page.keyboard.press('Escape');
});

test('topic menu shows the type definition; node click shows its I/O data', async ({ page }) => {
  await openMap(page);
  await rightClickNode(page, 't:/chatter');
  await expect(page.getByTestId('map-menu')).toHaveAttribute('data-kind', 'topic');
  await page.screenshot({ path: `${SHOTS}menu-topic.png` });
  await page.getByTestId('menu-typeDef').click();
  await expect(page.getByTestId('interface-body')).toContainText('string data');
  await page.keyboard.press('Escape');

  await clickElement(page, 'n:/listener');
  await expect(page.getByTestId('detail-title')).toHaveText('/listener');
  const inputs = page.getByTestId('io-inputs');
  await expect(inputs).toContainText('/chatter');
  await expect(inputs.getByTestId('io-echo-body')).toContainText('Hello World', { timeout: 10_000 });
  await page.screenshot({ path: `${SHOTS}node-io-pane.png` });
});

test('first-run guide appears with an empty launch list and starts talker', async ({ page }) => {
  // The fresh lab-e2e project starts with the demo launch list; empty it to see the guide.
  const original = (await (await page.request.get('/api/project')).json()).project;
  for (const target of original.targets ?? []) await page.request.delete(`/api/targets/${target.id}`);
  await page.goto('/');
  await page.getByTestId('tab-launcher').click();
  const guide = page.getByTestId('first-run-guide');
  await expect(guide).toBeVisible();
  await page.screenshot({ path: `${SHOTS}launcher-guide.png` });
  await guide.getByTestId('guide-try-talker').click();
  await expect(page.getByTestId('target-status-talker')).toHaveAttribute('data-status', /starting|running/, { timeout: 10_000 });
  await expect(guide).toHaveCount(0);
});
