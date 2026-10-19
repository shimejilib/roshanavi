import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { clickElement, rightClickBlank, rightClickNode } from './helpers';

// P4.5a flows (requires `docker compose up -d lab demo`): map menus, input nodes,
// parameters, node I/O pane and the Launcher's first-run guide.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
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
  // The current `paused` parameter decides: a running input offers 一時停止 only, not 再開 too.
  await expect(page.getByTestId('menu-resume')).toHaveCount(0);
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
  // ROS's own settings are folded away (「ROS の内部のパラメータ」); open them to see use_sim_time.
  await expect(dialog.getByTestId('params-internal')).toContainText('ROS の内部のパラメータ', { timeout: 10_000 });
  await expect(dialog.locator('[data-param="use_sim_time"]')).toBeHidden();
  await dialog.getByTestId('params-internal').locator('summary').click();
  await expect(dialog.locator('[data-param="use_sim_time"]')).toBeVisible();
  await expect(dialog.getByTestId('param-input-use_sim_time')).toHaveValue('false');
  await page.screenshot({ path: `${SHOTS}params-dialog.png` });
  await page.keyboard.press('Escape');

  await rightClickNode(page, 'n:/external_talker');
  await expect(page.getByTestId('map-menu').getByTestId('menu-stop')).toBeDisabled();
  await page.getByTestId('map-menu').getByTestId('menu-params').click();
  await expect(page.getByTestId('params-external')).toContainText('閲覧のみ', { timeout: 10_000 });
  await page.getByTestId('params-internal').locator('summary').click();
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

type CyHost = { _cyreg: { cy: { getElementById: (i: string) => { position: () => { x: number; y: number } } } } };
const modelPosition = (page: Page, id: string) =>
  page.getByTestId('graph-canvas').evaluate((el, i) => {
    const p = (el as unknown as CyHost)._cyreg.cy.getElementById(i).position();
    return { x: Math.round(p.x), y: Math.round(p.y) };
  }, id);

test('a dragged node keeps its place when the topology changes; 整列し直す lays everything out again (#8)', async ({ page }) => {
  await openMap(page);
  const canvas = page.getByTestId('graph-canvas');
  const rendered = await canvas.evaluate((el) => {
    const p = (el as unknown as { _cyreg: { cy: { getElementById: (i: string) => { renderedPosition: () => { x: number; y: number } } } } })._cyreg.cy.getElementById('n:/talker').renderedPosition();
    return { x: p.x, y: p.y };
  });
  const box = await canvas.boundingBox();
  if (!box) throw new Error('graph canvas not visible');
  const automatic = await modelPosition(page, 'n:/talker');
  await page.mouse.move(box.x + rendered.x, box.y + rendered.y);
  await page.mouse.down();
  await page.mouse.move(box.x + rendered.x + 40, box.y + rendered.y + 140, { steps: 8 });
  await page.mouse.up();
  const dragged = await modelPosition(page, 'n:/talker');
  expect(Math.abs(dragged.y - automatic.y)).toBeGreaterThan(40);

  // A new node changes the topology: the layout runs again, but the dragged node stays.
  await page.request.post('/api/dummies?start=true', {
    data: { id: INPUT_ID, name: INPUT_ID, topic: '/e2e_pin_topic', type: 'std_msgs/msg/String', mode: 'periodic', payload: { data: 'x' }, rate_hz: 1 },
  });
  await expect(page.getByTestId('graph-outline').locator(`[data-id="n:/${INPUT_ID}"]`)).toHaveCount(1, { timeout: 20_000 });
  await page.waitForTimeout(1200); // layout animation
  expect(await modelPosition(page, 'n:/talker')).toEqual(dragged);

  // The pin survives a reload (saved per project in localStorage).
  await page.reload();
  await expect(page.getByTestId('graph-outline').locator(`[data-id="n:/${INPUT_ID}"]`)).toHaveCount(1, { timeout: 20_000 });
  await page.waitForTimeout(1500);
  expect(await modelPosition(page, 'n:/talker')).toEqual(dragged);

  // 整列し直す unpins everything.
  await rightClickBlank(page);
  await page.getByTestId('menu-relayout').click();
  await page.waitForTimeout(1200);
  const relaid = await modelPosition(page, 'n:/talker');
  expect(Math.abs(relaid.y - dragged.y)).toBeGreaterThan(20);
});
