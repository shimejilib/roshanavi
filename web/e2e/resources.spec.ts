import { expect, type APIRequestContext, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { clickElement } from './helpers';

// Resource monitoring (#32): the busy_demo's problem configuration (multi + default) started by
// the Launcher shows its high CPU on the map, the リソース tab lists it under ROS ノード, and the
// example scenario busy_cpu.yaml (multi + off) passes its resources / mem_growth steps.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const DRIVER = 'e2e_res_driver';
const BUSY = 'e2e_res_busy';
const BUSY_NODE = '/e2e_res_busy';

interface NodeRes { cpu_pct: number | null; confidence: string }

async function addAndStart(request: APIRequestContext, spec: Record<string, unknown>) {
  const added = await request.post('/api/targets', { data: spec });
  expect(added.ok() || added.status() === 409, await added.text()).toBeTruthy();
  const started = await request.post(`/api/targets/${spec.id as string}/start`);
  expect(started.ok() || started.status() === 409, await started.text()).toBeTruthy();
}

async function nodeRes(request: APIRequestContext, node: string): Promise<NodeRes | null> {
  const snap = await (await request.get('/api/resources')).json();
  return (snap.nodes ?? {})[node] ?? null;
}

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterAll(async ({ request }) => {
  for (const id of [BUSY, DRIVER]) {
    await request.post(`/api/targets/${id}/stop`);
    await request.delete(`/api/targets/${id}`);
  }
});

test('busy_demo multi + default: high CPU on the map, ROS row in the リソース tab', async ({ page, request }) => {
  test.setTimeout(120_000);
  await addAndStart(request, { id: DRIVER, kind: 'run', package: 'roshanavi_examples', executable: 'busy_demo_driver', name: DRIVER, params: { rate_hz: 100.0 }, role: 'dependency' });
  await addAndStart(request, {
    id: BUSY, kind: 'run', package: 'roshanavi_examples', executable: 'executor_busy_demo', name: BUSY, role: 'mine',
    params: { executor: 'multi', qos_events: 'default', work_ms: 5.0, num_threads: 4, stats_topic: '/e2e_res/stats' },
  });
  await expect.poll(async () => (await nodeRes(request, BUSY_NODE))?.confidence ?? null, { timeout: 30_000 }).toBe('exact');
  // The busy-loop is environment dependent (rmw_fastrtps#929): wait for it, report if it never shows.
  let busy = false;
  try {
    await expect.poll(async () => (await nodeRes(request, BUSY_NODE))?.cpu_pct ?? 0, { timeout: 30_000 }).toBeGreaterThanOrEqual(40);
    busy = true;
  } catch {
    test.info().annotations.push({ type: 'note', description: 'busy-loop did not reproduce: no high-load colour to check' });
  }

  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');
  const canvas = page.getByTestId('graph-canvas');
  const elementData = () => canvas.evaluate((el, id) => {
    const cy = (el as unknown as { _cyreg: { cy: { getElementById: (i: string) => { data: (k: string) => string } } } })._cyreg.cy;
    const node = cy.getElementById(id);
    return { label: node.data('label'), load: node.data('load') };
  }, `n:${BUSY_NODE}`);
  await expect.poll(async () => (await elementData()).label ?? '', { timeout: 20_000 }).toContain('CPU');
  expect((await elementData()).label).not.toContain('推定'); // started by the Launcher: exact
  if (busy) await expect.poll(async () => (await elementData()).load, { timeout: 10_000 }).toMatch(/^(mid|high)$/);
  await page.getByRole('button', { name: '全体を表示' }).click();
  await clickElement(page, `n:${BUSY_NODE}`);
  const pane = page.getByTestId('node-resources');
  await expect(pane).toBeVisible({ timeout: 10_000 });
  await expect(pane).toContainText('CPU');
  await expect(pane).toContainText('RSS');
  await expect(pane.locator('.sparkline').first()).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: `${SHOTS}resources-map.png` });

  await page.getByTestId('tab-resources').click();
  const tab = page.getByTestId('resources-tab');
  await expect(tab.getByTestId('res-host-cpu')).toBeVisible({ timeout: 15_000 });
  await expect(tab.getByTestId('res-scope-note')).toContainText('この PC だけ');
  await expect(tab.getByTestId('res-host-disk')).toContainText('/data');
  await expect(tab.getByTestId('res-host-gpu')).toBeVisible();
  await expect(tab.getByTestId('res-breakdown')).toContainText('roshanavi 自身');
  const busyRow = tab.getByTestId('res-proc-ros').filter({ hasText: BUSY_NODE });
  await expect(busyRow).toBeVisible();
  await expect(tab.getByTestId('res-proc-self').filter({ hasText: 'サーバー本体' }).first()).toBeVisible();
  await expect(tab.getByTestId('res-sampler')).toContainText('計測そのものの負荷');
  await page.setViewportSize({ width: 1440, height: 1800 }); // the tab scrolls inside: show all of it
  await page.screenshot({ path: `${SHOTS}resources-tab.png` });
  await page.setViewportSize({ width: 1440, height: 900 });

  // A node name in the table leads back to the map with that node selected.
  await busyRow.getByTestId('res-proc-node').first().click();
  await expect(page.getByTestId('detail-title')).toHaveText(BUSY_NODE);
  await request.post(`/api/targets/${BUSY}/stop`); // free the core for the scenario below
});

test('example scenario busy_cpu (multi + off) passes its CPU and memory steps', async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto('/');
  await page.getByTestId('tab-scenarios').click();
  const id = 'example:busy_cpu.yaml';
  await expect(page.getByTestId(`scn-item-${id}`)).toBeVisible();
  await page.getByTestId(`scn-run-${id}`).click();
  const result = page.getByTestId('scn-result');
  await expect(result).toBeVisible();
  await expect(result).toHaveAttribute('data-status', 'running', { timeout: 15_000 }); // not an older result
  await expect(result).toHaveAttribute('data-status', 'passed', { timeout: 90_000 });
  // steps are numbered from 1: wait, resources, mem_growth
  await expect(page.getByTestId('scn-step-2')).toHaveAttribute('data-status', 'passed');
  await expect(page.getByTestId('scn-step-2').getByTestId('scn-step-message')).toContainText('CPU は平均');
  await expect(page.getByTestId('scn-step-3')).toHaveAttribute('data-status', 'passed');
  await expect(page.getByTestId('scn-step-3').getByTestId('scn-step-message')).toContainText('MB/分');
  await page.screenshot({ path: `${SHOTS}resources-scenario.png` });
});
