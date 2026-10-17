import { expect, test, type Page } from '@playwright/test';
import { clickElement } from './helpers';

// Regression: a multi-input transform (lifecycle TransitionEvent + String, condition, delay,
// empty mapping) blanked the whole UI as soon as it, its output topic or an edge was clicked.
const ID = 'topic_transform';
const SPEC = {
  id: ID,
  name: ID,
  inputs: [
    { topic: '/lc_talker/transition_event', type: 'lifecycle_msgs/msg/TransitionEvent', alias: 'msg1' },
    { topic: '/chatter', type: 'std_msgs/msg/String', alias: 'msg2' },
  ],
  output: { topic: '/output_test', type: 'std_msgs/msg/String', qos: { reliability: 'reliable', durability: 'volatile', depth: 10 } },
  mode: 'map',
  mapping: { data: '' },
  condition: 'msg2.data != ""',
  trigger: 'msg2',
  delay: { min_ms: 100, max_ms: 200 },
  drop_ratio: 0,
  autostart: false,
};

test.afterEach(async ({ page }) => {
  await page.request.delete(`/api/targets/${ID}`);
});

const errors: string[] = [];

/** The app shell and the map are still rendered; on failure the captured browser errors are the message. */
async function appIsAlive(page: Page) {
  try {
    await expect(page.getByTestId('ws-status')).toBeVisible({ timeout: 3000 });
    await expect(page.getByTestId('graph-canvas')).toBeVisible({ timeout: 3000 });
  } catch (err) {
    throw new Error(`UI went blank. Browser errors:\n${errors.join('\n')}\n${String(err)}`);
  }
}

async function edgePoints(page: Page): Promise<Array<{ id: string; x: number; y: number }>> {
  const canvas = page.getByTestId('graph-canvas');
  return canvas.evaluate((el) => {
    type Cy = { edges: () => { map: <T>(f: (e: { id: () => string; renderedMidpoint: () => { x: number; y: number } }) => T) => T[] } };
    const cy = (el as unknown as { _cyreg: { cy: Cy } })._cyreg.cy;
    return cy.edges().map((e) => ({ id: e.id(), ...e.renderedMidpoint() }));
  });
}

test('clicking a multi-input transform, its output topic and its edges never blanks the UI', async ({ page }) => {
  errors.length = 0;
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`console: ${msg.text()}`);
  });

  const created = await page.request.post('/api/transforms?start=true', { data: SPEC });
  expect(created.ok(), await created.text()).toBeTruthy();

  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');
  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator(`[data-id="n:/${ID}"]`)).toHaveCount(1, { timeout: 30_000 });
  await expect(outline.locator('[data-id="t:/output_test"]')).toHaveCount(1, { timeout: 30_000 });
  await page.waitForTimeout(2500); // layout animation + a few snapshots

  for (const id of [`n:/${ID}`, 't:/output_test', 't:/lc_talker/transition_event', 't:/chatter']) {
    await clickElement(page, id);
    await page.waitForTimeout(700);
    await appIsAlive(page);
    await clickElement(page, id, 'right');
    await page.waitForTimeout(300);
    await appIsAlive(page);
    await page.keyboard.press('Escape');
  }
  for (const edge of await edgePoints(page)) {
    const box = await page.getByTestId('graph-canvas').boundingBox();
    if (!box) throw new Error('canvas not visible');
    await page.mouse.click(box.x + edge.x, box.y + edge.y);
    await page.waitForTimeout(250);
    await appIsAlive(page);
    await page.mouse.click(box.x + edge.x, box.y + edge.y, { button: 'right' });
    await page.waitForTimeout(250);
    await appIsAlive(page);
    await page.keyboard.press('Escape');
  }
  // The traffic table: expand the rows of the transform's topics, then the per-node view.
  await page.getByTestId('tab-traffic').click();
  for (const topic of ['/output_test', '/lc_talker/transition_event', '/chatter']) {
    await page.getByTestId(`expand-${topic}`).click();
    await page.waitForTimeout(300);
    await expect(page.locator('.app')).toBeVisible();
  }
  await page.getByTestId('traffic-view-node').click();
  await page.waitForTimeout(500);
  await expect(page.getByTestId('node-traffic')).toBeVisible();
  // Other tabs that list the same node / topics.
  for (const tab of ['nodes', 'traffic', 'inject', 'launcher', 'graph']) {
    await page.getByTestId(`tab-${tab}`).click();
    await page.waitForTimeout(500);
    await expect(page.locator('.app')).toBeVisible();
  }
  expect(errors).toEqual([]);
});
