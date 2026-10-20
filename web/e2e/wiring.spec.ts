import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Map wiring (docs/design/wiring.md): scaffold a function, wire it on the map by dragging (a
// channel into its input port, its output port into a blank part = a new channel) and by keyboard,
// and see the upper-case text on the new channel. An incompatible channel is refused with the reason.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const PKG = 'e2e_wire';
const FN = 'wire_fn';
const NUM = 'e2e_wire_num';

type Cy = { getElementById: (i: string) => { renderedPosition: () => { x: number; y: number }; empty: () => boolean } };

test.use({ screenshot: 'only-on-failure' });
test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterAll(async ({ request }) => {
  for (const id of [FN, NUM]) await request.delete(`/api/targets/${id}`);
  await request.post('/api/targets/moving_average/stop');
});

/** Page coordinates of a map element (cytoscape keeps its instance on the container). */
async function elementPoint(page: Page, elementId: string): Promise<{ x: number; y: number }> {
  const canvas = page.getByTestId('graph-canvas');
  const pos = await canvas.evaluate((el, id) => (el as unknown as { _cyreg: { cy: Cy } })._cyreg.cy.getElementById(id).renderedPosition(), elementId);
  const box = await canvas.boundingBox();
  if (!box) throw new Error('graph canvas not visible');
  return { x: box.x + pos.x, y: box.y + pos.y };
}

type CyAll = { nodes: () => { map: <T>(f: (n: { renderedBoundingBox: (o: object) => { x1: number; y1: number; x2: number; y2: number } }) => T) => T[] }; getElementById: Cy['getElementById'] };

/** Page coordinates of an empty spot of the map near `elementId` (no node or channel there). */
async function blankNear(page: Page, elementId: string): Promise<{ x: number; y: number }> {
  const canvas = page.getByTestId('graph-canvas');
  const box = await canvas.boundingBox();
  if (!box) throw new Error('graph canvas not visible');
  const spot = await canvas.evaluate((el, args) => {
    const cy = (el as unknown as { _cyreg: { cy: CyAll } })._cyreg.cy;
    const at = cy.getElementById(args.id).renderedPosition();
    const boxes = cy.nodes().map((n) => n.renderedBoundingBox({ includeLabels: true }));
    const free = (x: number, y: number) => x > 20 && y > 20 && x < args.w - 20 && y < args.h - 120
      && boxes.every((b) => x < b.x1 - 30 || x > b.x2 + 30 || y < b.y1 - 30 || y > b.y2 + 30);
    const offsets: [number, number][] = [[140, 0], [140, 70], [140, -70], [0, 110], [0, -110], [200, 140], [-160, 120], [220, -140]];
    for (const [dx, dy] of offsets) {
      if (free(at.x + dx, at.y + dy)) return { x: at.x + dx, y: at.y + dy };
    }
    return null;
  }, { id: elementId, w: box.width, h: box.height });
  if (!spot) throw new Error('no blank spot near ' + elementId);
  return { x: box.x + spot.x, y: box.y + spot.y };
}

async function center(page: Page, testId: string): Promise<{ x: number; y: number }> {
  const box = await page.getByTestId(testId).boundingBox();
  if (!box) throw new Error(`${testId} not visible`);
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

async function drag(page: Page, from: { x: number; y: number }, to: { x: number; y: number }, release = true) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move((from.x + to.x) / 2, (from.y + to.y) / 2, { steps: 6 });
  await page.mouse.move(to.x, to.y, { steps: 6 });
  if (release) await page.mouse.up();
}

const spec = async (page: Page) => (await (await page.request.get(`/api/targets/${FN}`)).json()).spec;

test('wire a function on the map by drag and by keyboard; incompatible channels are refused', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('graph-outline').locator('[data-id="t:/chatter"]')).toHaveCount(1, { timeout: 20_000 });

  // 1. Scaffold a function and create its node without channels (ports wired on the map later).
  await page.getByTestId('create-function').click();
  const dialog = page.getByTestId('create-function-dialog');
  const panel = dialog.getByTestId('code-locations');
  await expect(panel.getByTestId('code-summary')).toBeVisible({ timeout: 10_000 });
  if (!(await panel.evaluate((el) => (el as HTMLDetailsElement).open))) await panel.locator('summary').click();
  await panel.getByTestId('scaffold-name').fill(PKG);
  await panel.getByTestId('scaffold-submit').click();
  await expect(dialog.getByTestId('function-name')).toHaveValue('convert', { timeout: 15_000 });
  await dialog.getByTestId('function-node-name').fill(FN);
  await dialog.getByTestId('function-map-later').click();
  await expect(dialog.getByTestId('function-output-topic')).toHaveValue('');
  await expect(dialog.getByTestId('function-timing-text')).toHaveText('この入力が届くたびに呼ばれます');
  await dialog.getByTestId('function-timing').scrollIntoViewIfNeeded();
  await dialog.getByTestId('function-timing').screenshot({ path: `${SHOTS}wiring-timing.png` });
  await dialog.getByTestId('function-submit').click();
  await expect(dialog).toHaveCount(0);

  // The node is on the map with an input port (text) and an output port (戻り値), not wired yet.
  const input = page.getByTestId(`port-${FN}-in-0-0`);
  const output = page.getByTestId(`port-${FN}-out-0-0`);
  await expect(input).toBeVisible({ timeout: 30_000 });
  await expect(input).toHaveAttribute('aria-label', /入力口 text \(文字列\)、まだつながっていません/);
  await expect(output).toHaveAttribute('aria-label', /出力口 戻り値 \(文字列\)/);
  await page.waitForTimeout(1500); // layout animation
  const fit = () => page.getByTestId('fit-all').click(); // new nodes may land off-screen
  await fit();

  // 2. Drag the channel /chatter (its handle) into the input port.
  const chatter = await elementPoint(page, 't:/chatter');
  await page.mouse.move(chatter.x, chatter.y);
  await expect(page.getByTestId('wire-handle')).toBeVisible();
  await drag(page, await center(page, 'wire-handle'), await center(page, `port-${FN}-in-0-0`), false);
  await expect(page.getByTestId('wire-hint')).toContainText('つなぎます');
  await page.screenshot({ path: `${SHOTS}wiring-drag.png` });
  await page.mouse.up();
  await expect(page.getByTestId('wire-notice')).toContainText('/chatter', { timeout: 10_000 });
  await expect.poll(async () => (await spec(page)).inputs[0].topic, { timeout: 10_000 }).toBe('/chatter');
  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator(`[data-id="e:sub:/${FN}:/chatter"]`)).toHaveCount(1, { timeout: 30_000 }); // restarted, subscribed

  // 3. Drag the output port into a blank part of the map: a new channel, named /<node>/out.
  await expect(output).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(1500);
  await fit();
  await drag(page, await center(page, `port-${FN}-out-0-0`), await blankNear(page, `n:/${FN}`), false);
  await expect(page.getByTestId('wire-hint')).toContainText('新しいトピック');
  await page.mouse.up();
  const prompt = page.getByTestId('wire-prompt');
  await expect(prompt.getByTestId('wire-prompt-name')).toHaveValue(`/${FN}/out`);
  await prompt.getByTestId('wire-prompt-ok').click();
  await expect.poll(async () => (await spec(page)).output.topic, { timeout: 10_000 }).toBe(`/${FN}/out`);

  // The new channel carries the upper-case text (the scaffolded convert() returns text.upper()).
  await expect(outline.locator(`[data-id="e:pub:/${FN}:/${FN}/out"]`)).toHaveCount(1, { timeout: 30_000 });
  await page.waitForTimeout(1500);
  await fit();
  const outTopic = await elementPoint(page, `t:/${FN}/out`);
  await page.mouse.click(outTopic.x, outTopic.y);
  await expect(page.getByTestId('detail-title')).toHaveText(`/${FN}/out`);
  await expect(page.getByTestId('echo-body')).toContainText('HELLO WORLD', { timeout: 30_000 });
  await output.hover();
  await expect(page.getByTestId('wire-tip')).toContainText('この入力が届くたびに呼ばれます');
  await expect(page.getByTestId('wire-tip-value')).toContainText('HELLO WORLD', { timeout: 15_000 });
  await page.screenshot({ path: `${SHOTS}wiring-map.png` });

  // 4. An incompatible channel (numbers into a text input) is refused with the reason, nothing saved.
  const dummy = {
    id: NUM, name: NUM, topic: `/${NUM}`, type: 'std_msgs/msg/Float64', kind: 'float', mode: 'periodic', rate_hz: 2, payload: { data: 1.5 },
  };
  expect((await page.request.post('/api/dummies?start=true', { data: dummy })).status()).toBe(201);
  await expect(outline.locator(`[data-id="t:/${NUM}"]`)).toHaveCount(1, { timeout: 30_000 });
  await page.waitForTimeout(1500);
  await fit();
  await drag(page, await center(page, `port-${FN}-in-0-0`), await elementPoint(page, `t:/${NUM}`), false);
  await expect(page.getByTestId('wire-hint')).toContainText('文字列の入力口に、数値 (小数)のトピックはつなげません');
  await page.screenshot({ path: `${SHOTS}wiring-refused.png` });
  await page.mouse.up();
  await expect(page.getByTestId('wire-notice')).toContainText('つなげません');
  expect((await spec(page)).inputs[0].topic).toBe('/chatter');

  // 5. Keyboard: Delete takes the wire off; Enter -> choose /chatter in the list -> Enter -> Enter.
  await input.focus();
  await page.keyboard.press('Delete');
  await expect.poll(async () => (await spec(page)).inputs[0].topic, { timeout: 10_000 }).toBe('');
  await expect(input).toHaveAttribute('aria-label', /まだつながっていません/, { timeout: 20_000 });
  await expect(input).toBeFocused({ timeout: 20_000 }); // the focus stays on the port across the restart
  await expect(outline.locator(`[data-id="e:sub:/${FN}:/chatter"]`)).toHaveCount(0, { timeout: 30_000 });
  await input.focus();
  await page.keyboard.press('Enter');
  const wire = page.getByTestId('wire-dialog');
  const list = wire.getByTestId('wire-options');
  await expect(list).toBeFocused();
  await expect(wire.getByTestId(`wire-option-topic:/${NUM}`)).toHaveAttribute('aria-disabled', 'true');
  await expect(wire.getByTestId(`wire-option-topic:/${NUM}`)).toContainText('つなげません');
  for (let i = 0; i < 40; i += 1) {
    const focused = await list.getAttribute('aria-activedescendant');
    if (focused && (await wire.locator(`#${focused}`).getAttribute('data-testid')) === 'wire-option-topic:/chatter') break;
    await page.keyboard.press('ArrowDown');
  }
  await page.screenshot({ path: `${SHOTS}wiring-keyboard.png` });
  await page.keyboard.press('Enter');
  await expect(wire.getByTestId('wire-confirm')).toContainText('/chatter');
  await page.keyboard.press('Enter');
  await expect(wire).toHaveCount(0);
  await expect.poll(async () => (await spec(page)).inputs[0].topic, { timeout: 10_000 }).toBe('/chatter');
  await expect(outline.locator(`[data-id="e:sub:/${FN}:/chatter"]`)).toHaveCount(1, { timeout: 30_000 });
  await expect(input).toBeFocused({ timeout: 20_000 });
  await expect(page.getByTestId('echo-body')).toContainText('HELLO WORLD', { timeout: 30_000 });

  // 6. The pub/sub primer opens from the legend.
  await page.getByTestId('legend-primer').click();
  await expect(page.getByTestId('primer')).toContainText('名前付きのトピック');
  await page.getByTestId('primer').screenshot({ path: `${SHOTS}wiring-primer.png` });
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('primer')).toHaveCount(0);

  // 7. A class node: one group of ports per bound method, action methods as buttons.
  await page.getByRole('complementary', { name: 'detail' }).getByRole('button', { name: '閉じる' }).click(); // no focus fading
  expect((await page.request.post('/api/targets/moving_average/start')).ok()).toBe(true);
  await expect(page.getByTestId('port-moving_average-in-0-0')).toHaveAttribute('aria-label', /メソッド process の入力口 x \(数値 \(小数\)\)、\/number につながっています/, { timeout: 30_000 });
  await page.waitForTimeout(1500);
  await fit();
  const reset = page.getByRole('button', { name: 'moving_average の reset を呼ぶ' });
  await expect(reset).toBeEnabled({ timeout: 20_000 });
  await page.getByTestId('port-moving_average-out-0-0').hover();
  await expect(page.getByTestId('wire-tip')).toContainText('この入力が届くたびに呼ばれます');
  await page.screenshot({ path: `${SHOTS}wiring-class.png` });
  await reset.click();
  await expect(page.getByTestId('wire-notice')).toContainText('reset を呼びました', { timeout: 10_000 });
});
