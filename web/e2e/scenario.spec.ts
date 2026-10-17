import { expect, type Page, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Scenarios (#31): record a scenario through the UI (send to /chatter, click the function
// node's output on /shouted, save), run it from the Scenarios tab, break it, see why it fails.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const NAME = 'e2e_recorded';
const ID = `project:${NAME}.yaml`;

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.beforeEach(async ({ request }) => {
  await request.delete('/api/scenario-record?discard=true'); // no session left from a previous run
});
test.afterAll(async ({ request }) => {
  await request.delete('/api/scenario-record?discard=true');
  await request.delete(`/api/scenarios/${encodeURIComponent(ID)}`);
  await request.post('/api/targets/text_shout/stop');
});

/** text_shout (demo project): the example function shout() on /chatter -> /shouted. */
async function startShout(page: Page) {
  const resp = await page.request.post('/api/targets/text_shout/start');
  expect(resp.ok() || resp.status() === 409, await resp.text()).toBeTruthy(); // 409: already running
  await expect.poll(async () => {
    const graph = await (await page.request.get('/api/graph')).json();
    return graph.topics.some((t: { name: string }) => t.name === '/shouted');
  }, { timeout: 30_000 }).toBe(true);
}

test('record, run, break: the failure is explained', async ({ page }) => {
  await startShout(page);

  await page.goto('/');
  await page.getByTestId('tab-scenarios').click();
  await expect(page.getByTestId('scn-item-example:state_machine.yaml')).toBeVisible();
  await page.getByTestId('scn-record-open').click();
  await page.getByTestId('scn-watch-/shouted').check();
  await page.getByTestId('scn-rec-start').click();
  await expect(page.getByTestId('scn-rec-badge')).toBeVisible();

  // An operation in another tab becomes a step.
  await page.getByTestId('tab-inject').click();
  await page.getByTestId('inject-topic').fill('/chatter');
  await expect(page.getByTestId('inject-type-detected')).toContainText('文字列 (std_msgs/String)');
  await page.getByTestId('inject-yaml').fill('data: "hello scenario"');
  await page.getByTestId('inject-start').click();
  await expect(page.getByRole('status')).toContainText('開始しました');

  // Back in the Scenarios tab (the badge leads there): click the answer -> 「これが来るはず」.
  await page.getByTestId('scn-rec-badge').click();
  await expect(page.getByTestId('scn-tl-op')).toContainText('/chatter');
  const answer = page.getByTestId('scn-tl-msg').filter({ hasText: 'HELLO SCENARIO!' }).first();
  await expect(answer).toBeVisible({ timeout: 10_000 });
  await answer.click();
  await page.getByTestId('scn-expect-this').click();
  await expect(page.getByTestId('scn-pick-data')).toBeChecked();
  await expect(page.getByTestId('scn-pick-value-data')).toHaveValue('HELLO SCENARIO!');
  // within = 3 x the measured response, at least 0.5 s.
  expect(Number(await page.getByTestId('scn-pick-within').inputValue())).toBeGreaterThanOrEqual(0.5);
  await page.screenshot({ path: `${SHOTS}scenario-record.png` });
  await page.getByTestId('scn-pick-add').click();
  await expect(page.getByTestId('scn-rec-steps').locator('li')).toHaveCount(2);
  await expect(page.getByTestId('scn-rec-steps')).toContainText('HELLO SCENARIO!');
  await page.getByTestId('scn-rec-stop').click();
  await page.getByTestId('scn-rec-name').fill(NAME);
  await page.getByTestId('scn-rec-save').click();
  await expect(page.getByTestId('scn-rec-badge')).toHaveCount(0);

  // Run it: passes.
  const item = page.getByTestId(`scn-item-${ID}`);
  await expect(item).toBeVisible();
  await page.getByTestId(`scn-run-${ID}`).click();
  const result = page.getByTestId('scn-result');
  await expect(result).toHaveAttribute('data-status', 'passed', { timeout: 30_000 });
  await expect(page.getByTestId('scn-step-2')).toHaveAttribute('data-status', 'passed');
  await expect(item.getByTestId('scn-item-status')).toHaveText('成功');

  // Break it: expect a different answer -> fails, and says what arrived instead.
  await page.getByTestId(`scn-edit-${ID}`).click();
  const value = page.getByTestId('scn-editor').locator('[data-testid^="scn-cond-"][data-testid$="-value"]').first();
  await expect(value).toHaveValue('HELLO SCENARIO!');
  await value.fill('HELLO NOBODY!');
  await page.getByTestId('scn-edit-save').click();
  await expect(page.getByTestId('scn-editor')).toHaveCount(0);
  await page.getByTestId(`scn-run-${ID}`).click();
  await expect(result).toHaveAttribute('data-status', 'failed', { timeout: 30_000 });
  const failed = page.getByTestId('scn-step-2');
  await expect(failed).toHaveAttribute('data-status', 'failed');
  // What arrived instead (the function's real answer) and which condition did not hold.
  await expect(failed.getByTestId('scn-step-message')).toContainText('HELLO SCENARIO!');
  await expect(failed.getByTestId('scn-step-message')).toContainText('data = "HELLO NOBODY!" → 実際は');
  await page.screenshot({ path: `${SHOTS}scenario-result.png` });

  const saved = await (await page.request.get(`/api/scenarios/${encodeURIComponent(ID)}`)).json();
  expect(saved.yaml).toContain('HELLO NOBODY!');
  expect(saved.spec.steps[0]).toMatchObject({ send: { topic: '/chatter', data: { data: 'hello scenario' } } });
});

test('an example scenario runs from the Scenarios tab', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('tab-scenarios').click();
  await page.getByTestId('scn-run-example:state_machine.yaml').click();
  const result = page.getByTestId('scn-result');
  await expect(result).toHaveAttribute('data-status', 'passed', { timeout: 60_000 });
  await expect(result).toContainText('ガード');
});

test('record mode: a selected range becomes a rate check with a proposed threshold', async ({ page }) => {
  await startShout(page);
  await page.goto('/');
  await page.getByTestId('tab-scenarios').click();
  await page.getByTestId('scn-record-open').click();
  await page.getByTestId('scn-watch-/shouted').check();
  await page.getByTestId('scn-rec-start').click();
  // The demo talker -> text_shout gives /shouted about once a second.
  const messages = page.getByTestId('scn-tl-msg');
  await expect(messages).toHaveCount(4, { timeout: 15_000 });
  await messages.nth(0).click();
  await messages.nth(3).click({ modifiers: ['Shift'] });
  await expect(page.getByTestId('scn-selected')).toContainText('区間');
  await page.getByTestId('scn-range-rate').click();
  const card = page.getByTestId('scn-exp-rate');
  await expect(card).toBeVisible();
  const values = await card.locator('input.num').evaluateAll((els) => els.map((e) => Number((e as HTMLInputElement).value)));
  // [for, min_hz, max_hz]: about 3 s of a ~1 Hz topic -> 0.8 .. 1.2 Hz around the measurement.
  expect(values[0]).toBeGreaterThan(2);
  expect(values[1]).toBeGreaterThan(0.5);
  expect(values[2]).toBeLessThan(2);
  await expect(page.getByTestId('scn-rec-steps')).toContainText('周期: /shouted');
  await page.getByTestId('scn-range-never').click();
  await expect(page.getByTestId('scn-exp-never')).toBeVisible();
  await page.getByTestId('scn-rec-stop').click();
  await page.getByTestId('scn-rec-discard').click();
  await expect(page.getByTestId('scn-rec-start')).toBeVisible();
});
