import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { clickElement, rightClickNode } from './helpers';

// Class nodes: a plain Python class (MovingAverage) run as a node. Parameters come from
// __init__, `reset` is an action method (map menu / node pane / topic), state lives in the instance.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const NAME = 'e2e_average';
const NUMBER = '/e2e_number';
const OUT = '/e2e_average_out';

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterEach(async ({ page }) => {
  await page.request.delete(`/api/targets/${NAME}`);
  await page.request.delete('/api/targets/e2e_counter');
});

const send = (page: import('@playwright/test').Page, value: number) =>
  page.request.post('/api/inject', { data: { mode: 'once', topic: NUMBER, type: 'std_msgs/msg/Float64', payload: { data: value } } });

test('create MovingAverage as a class node, see the average, press reset and see the state start over', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('graph-outline').locator('[data-id="t:/chatter"]')).toHaveCount(1, { timeout: 20_000 });
  await page.getByTestId('create-function').click();
  const dialog = page.getByTestId('create-function-dialog');
  await dialog.getByTestId('node-mode-class').check();
  await dialog.getByTestId('class-module').selectOption('roshanavi_examples.stateful');
  // Classes and their __init__ arguments come from a static parse (the server never imports user code).
  await expect(dialog.getByTestId('class-name').locator('option')).toContainText(['MovingAverage(window: int = 5)', 'Counter(start: int = 0)', 'RunningStats()']);
  await dialog.getByTestId('class-name').selectOption('MovingAverage');
  await expect(dialog.getByTestId('class-signature')).toContainText('roshanavi_examples/stateful.py');
  // __init__ arguments are parameters, with their defaults.
  await expect(dialog.getByTestId('class-param-window')).toHaveValue('5');
  await dialog.getByTestId('class-param-window').fill('3');
  // process takes a value (-> topic); reset takes none (-> action button).
  await expect(dialog.getByTestId('class-method-process-use-topic')).toBeChecked();
  await expect(dialog.getByTestId('class-method-reset-use-action')).toBeChecked();
  await dialog.getByTestId('class-node-name').fill(NAME);
  await dialog.getByTestId('class-method-process-input-0-topic').fill(NUMBER);
  await expect(dialog.getByTestId('class-method-process-input-0-type-kind')).toHaveValue('float');
  await expect(dialog.getByTestId('class-method-process-output-0-topic')).toHaveValue(OUT);
  // The whole dialog in one picture: a taller window for the screenshot only.
  await page.setViewportSize({ width: 1440, height: 1700 });
  await dialog.getByTestId('node-mode-class').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}class-node-dialog.png` });
  await page.setViewportSize({ width: 1440, height: 900 });
  await dialog.getByTestId('class-submit').click();
  await expect(dialog).toHaveCount(0);

  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator(`[data-id="n:/${NAME}"]`)).toHaveAttribute('data-role', 'function', { timeout: 30_000 });
  await expect(page.getByTestId('detail-title')).toHaveText(OUT);

  const project = await (await page.request.get('/api/project')).json();
  expect(project.project.classes.find((c: { id: string }) => c.id === NAME)).toMatchObject({
    module: 'roshanavi_examples.stateful', class_name: 'MovingAverage', params: { window: 3 }, actions: ['reset'],
    methods: [{ method: 'process', inputs: [{ topic: NUMBER, kind: 'float' }], outputs: [{ topic: OUT, kind: 'float' }] }],
  });
  // Give the node's subscription time to be discovered, then feed it numbers.
  await expect.poll(async () => (await (await page.request.get(`/api/targets/${NAME}`)).json()).function_status?.state, { timeout: 20_000 }).toBe('running');
  await page.waitForTimeout(1500);
  for (const value of [10, 20, 30]) {
    await send(page, value);
    await page.waitForTimeout(300);
  }
  await expect(page.getByTestId('echo-body')).toContainText(/"data": 20\b/, { timeout: 20_000 });   // (10 + 20 + 30) / 3

  // 「reset を呼ぶ」 from the map menu.
  await page.waitForTimeout(1500); // layout animation
  await rightClickNode(page, `n:/${NAME}`);
  await page.getByTestId('map-menu').getByTestId('menu-call:reset').click();
  await expect.poll(async () => (await (await page.request.get(`/api/targets/${NAME}`)).json()).function_status?.actions?.reset?.count, { timeout: 15_000 }).toBe(1);
  await send(page, 100);
  // Without reset the average would be (20 + 30 + 100) / 3 = 50; after it, the 100 stands alone.
  await expect(page.getByTestId('echo-body')).toContainText(/"data": 100\b/, { timeout: 15_000 });

  // The node pane has the same button and remembers the call.
  await clickElement(page, `n:/${NAME}`);
  await expect(page.getByTestId('class-status')).toHaveAttribute('data-state', 'running', { timeout: 10_000 });
  await expect(page.getByTestId('class-last-reset')).toContainText('1 回目', { timeout: 10_000 });
  await page.getByTestId('class-call-reset').click();
  await expect(page.getByTestId('class-call-result-reset')).toContainText('reset() を呼びました', { timeout: 10_000 });
  await expect(page.getByTestId('class-last-reset')).toContainText('2 回目', { timeout: 10_000 });
  await page.screenshot({ path: `${SHOTS}class-node-pane.png` });
});

test('a parameter change that recreates the instance says the state was reset', async ({ page }) => {
  const body = {
    id: 'e2e_counter', name: 'e2e_counter', module: 'roshanavi_examples.stateful', class_name: 'Counter', params: { start: 5 },
    methods: [{ method: 'process', inputs: [{ topic: '/chatter', kind: 'string' }], outputs: [{ topic: '/e2e_count', kind: 'int' }] }],
    actions: ['reset'],
  };
  expect((await page.request.post('/api/classes?start=true', { data: body })).status()).toBe(201);
  await page.goto('/');
  await expect(page.getByTestId('graph-outline').locator('[data-id="n:/e2e_counter"]')).toHaveAttribute('data-role', 'function', { timeout: 30_000 });
  await page.waitForTimeout(1500);
  await clickElement(page, 'n:/e2e_counter');
  await expect(page.getByTestId('class-status')).toHaveAttribute('data-state', 'running', { timeout: 20_000 });
  await expect(page.getByTestId('class-param-values')).toContainText('start');
  await expect(page.getByTestId('class-notice')).toHaveCount(0);
  const set = await page.request.put('/api/nodes/e2e_counter/parameters', { data: { name: 'start', type: 'integer', value: 100 } });
  expect(set.status()).toBe(200);
  await expect(page.getByTestId('class-notice')).toContainText('状態をリセットしました', { timeout: 15_000 });
  await expect(page.getByTestId('class-param-values')).toContainText('100');
  // a value the class refuses is explained, and the instance is untouched
  const bad = await page.request.put('/api/nodes/e2e_counter/parameters', { data: { name: 'start', type: 'string', value: 'x' } });
  expect(bad.ok()).toBe(false);
});
