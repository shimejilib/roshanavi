import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// #61: a heavy topic (images by default) is not subscribed, so it must say 計測していません with a
// 計測する button, never 受信なし / 未受信 / 分けられない; the choice is saved in the project and restored.
// demo-e2e runs `e2e_viz`, an image publisher outside roshanavi (like a turtle_viz node).
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const TOPIC = '/e2e_viz/image';
const RELAY = 'e2e_relay';
const COPY = '/e2e_viz/image_copy';
const NOT_MEASURED = '計測していません (画像などの重いデータは既定でオフ)';
const NEVER = ['受信なし', '未受信', '分けられない'];

async function openProject(page: Page, id: string) {
  await page.getByTestId('tab-launcher').click();
  // The settings menu is a <details>: press its summary until the entry shows (the tab may still be loading).
  await expect(async () => {
    if (!(await page.getByTestId('project-switch').isVisible())) await page.getByTestId('launcher-settings').click();
    await expect(page.getByTestId('project-switch')).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 20_000 });
  await page.getByTestId('project-switch').click();
  const dialog = page.getByTestId('projects-dialog');
  page.once('dialog', (d) => void d.accept());
  await dialog.getByTestId(`project-open-${id}`).click();
  await expect(dialog.getByRole('status')).toContainText('開きました', { timeout: 30_000 });
  await dialog.getByTestId('projects-close').click();
  await expect(dialog).toHaveCount(0);
}

async function topicLabel(page: Page, topic: string): Promise<string> {
  return page.getByTestId('graph-canvas').evaluate((el, id) => {
    type Cy = { getElementById: (i: string) => { data: (k: string) => string } };
    return (el as unknown as { _cyreg: { cy: Cy } })._cyreg.cy.getElementById(id).data('label');
  }, `t:${topic}`);
}

async function startRelay(page: Page) {
  const relay = await page.request.post('/api/transforms?start=true', { data: {
    id: RELAY, name: RELAY, mode: 'relay', inputs: [{ topic: TOPIC, type: 'sensor_msgs/msg/Image' }],
    output: { topic: COPY, qos: { reliability: 'reliable', durability: 'volatile', depth: 10 } },
    drop_ratio: 0, autostart: false,
  } });
  expect(relay.ok(), await relay.text()).toBeTruthy();
}

test.afterEach(async ({ request }) => {
  await request.delete(`/api/targets/${RELAY}`);
});

test.afterAll(async ({ request }) => {
  await request.put('/api/tracing', { data: { enabled: false } });
  await request.put(`/api/traffic${TOPIC}/monitor`, { data: { enabled: false } });
  await request.post('/api/projects/open', { data: { id: 'data:roshanavi.yaml' } });
  await expect.poll(async () => {
    const graph = await (await request.get('/api/graph')).json();
    return (graph.nodes as { id: string }[]).some((n) => n.id === '/talker');
  }, { timeout: 60_000 }).toBe(true);
});

test('image topic: 計測していません + 計測する, measured after the press, kept in the project', async ({ page, request }) => {
  test.setTimeout(150_000);
  mkdirSync(SHOTS, { recursive: true });
  await page.goto('/');
  // A real subscriber of the image: roshanavi's relay node (so the topic is not "受信なし" on the map).
  await startRelay(page);

  await page.getByTestId('tab-traffic').click();
  const row = page.locator(`tr[data-topic="${TOPIC}"]`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(row).toContainText(NOT_MEASURED);
  await expect(row.getByTestId(`measure-on-${TOPIC}`)).toHaveText('計測する');
  for (const word of NEVER) await expect(row).not.toContainText(word);
  await expect(row).not.toContainText('0 Hz');

  // The publisher / subscriber rows say the same instead of 分けられない.
  await row.getByTestId(`expand-${TOPIC}`).click();
  await expect(page.getByTestId(`endpoint-${TOPIC}-pub-/e2e_viz`)).toContainText('計測していません', { timeout: 20_000 });
  await expect(page.getByTestId(`endpoint-${TOPIC}-sub-/${RELAY}`)).toContainText('計測していません', { timeout: 30_000 });
  for (const word of NEVER) await expect(page.locator('.traffic-table')).not.toContainText(word);
  await page.screenshot({ path: `${SHOTS}traffic-not-measured.png` });

  // The map: the image has a real subscriber (the relay), so it never reads 受信なし.
  await page.getByTestId('tab-graph').click();
  await expect(page.getByTestId('graph-outline').locator(`[data-id="t:${TOPIC}"]`)).toHaveCount(1, { timeout: 30_000 });
  await expect(page.getByTestId('graph-outline').locator(`[data-id="n:/${RELAY}"]`)).toHaveCount(1, { timeout: 30_000 });
  await expect.poll(() => topicLabel(page, TOPIC), { timeout: 20_000 }).not.toContain('受信なし');

  // The detail pane says it too, with the button inline.
  await page.getByTestId('tab-traffic').click();
  await row.click();
  await expect(page.getByTestId('detail-not-measured')).toContainText(NOT_MEASURED);

  // 計測する -> measured (numbers instead of the notice).
  await row.getByTestId(`measure-on-${TOPIC}`).click();
  await expect(row).not.toContainText('計測していません', { timeout: 20_000 });
  await expect(row).toContainText(/\d+\.\d+ Hz/, { timeout: 20_000 });
  await page.screenshot({ path: `${SHOTS}traffic-measured-heavy.png` });
  expect((await (await request.get('/api/project')).json()).project.traffic_monitor).toEqual({ [TOPIC]: true });

  // "Restart": another project forgets the choice, coming back to this one restores it from the file.
  await openProject(page, 'example:demo_project');
  await page.getByTestId('tab-traffic').click();
  await expect(page.locator(`tr[data-topic="${TOPIC}"]`)).toContainText(NOT_MEASURED, { timeout: 60_000 });
  await openProject(page, 'data:roshanavi.yaml');
  await page.getByTestId('tab-traffic').click();
  const again = page.locator(`tr[data-topic="${TOPIC}"]`);
  await expect(again).toContainText(/\d+\.\d+ Hz/, { timeout: 60_000 });
  await expect(again).not.toContainText('計測していません');
});

test('詳細計測モード: the Hz of a heavy topic comes from the trace, bandwidth says it cannot be measured', async ({ page, request }) => {
  test.setTimeout(150_000);
  mkdirSync(SHOTS, { recursive: true });
  // Tracing first: only nodes lab-e2e starts afterwards (the relay) are covered by the trace.
  const enabled = await request.put('/api/tracing', { data: { enabled: true } });
  test.skip(!enabled.ok(), '詳細計測モードが使えない環境 (lttng-tools なし)');
  await expect.poll(async () => (await (await request.get('/api/tracing')).json()).active, { timeout: 20_000 }).toBe(true);
  await startRelay(page);

  await page.goto('/');
  await page.getByTestId('tab-traffic').click();
  const row = page.locator(`tr[data-topic="${COPY}"]`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  // The relay publishes the (not measured) image copy at ~5 Hz: the trace counts it, nobody subscribes.
  await expect(row.getByTestId(`off-hz-${COPY}`)).toContainText(/[3-6]\.\d+ Hz/, { timeout: 60_000 });
  await expect(row).toContainText('— (詳細計測では帯域は測れません)');
  await expect(row).toContainText('計測していません (画像などの重いデータは既定でオフ)');
  await expect(row).not.toContainText('Hz は詳細計測モードで確認できます'); // the mode is on
  for (const word of NEVER) await expect(row).not.toContainText(word);
  await row.getByTestId(`expand-${COPY}`).click();
  const pub = page.getByTestId(`endpoint-${COPY}-pub-/${RELAY}`);
  await expect(pub).toContainText('実測(トレース)', { timeout: 20_000 });
  await expect(pub).toContainText(/[3-6]\.\d+ Hz/);
  await expect(pub).toContainText('— (詳細計測では帯域は測れません)');
  await page.screenshot({ path: `${SHOTS}traffic-heavy-traced.png` });
});
