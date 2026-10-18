import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Relay pipeline sample (#51, scripts/gen_pipeline.py): the medium preset is a 5 x 4 grid of
// 20 C++ nodes (src_j -> relay_s_j -> sink_j, every node talking to two neighbours).
//  1. one process per node: the project is opened from the ⚙ settings menu, all 20 nodes are on
//     the map with live Hz on their edges, and the map stays smooth with real data.
//  2. the same pipeline in a composable container (#22): the nodes form one group, stopping any
//     one of them asks about all of them.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const COLUMNS = 4;
const NODES = [...Array(COLUMNS).keys()].flatMap((j) => [
  `src_${j}`, ...[1, 2, 3].map((s) => `relay_${s}_${j}`), `sink_${j}`,
]);
const CONTAINER_TARGET = 'pipe-container';
const LAB_PROJECT = 'data:roshanavi.yaml';

async function openProject(page: Page, id: string) {
  await page.getByTestId('tab-launcher').click();
  await page.getByTestId('launcher-settings').click();
  await page.getByTestId('project-switch').click();
  const dialog = page.getByTestId('projects-dialog');
  page.once('dialog', (d) => void d.accept());
  await dialog.getByTestId(`project-open-${id}`).click();
  await expect(dialog.getByRole('status')).toContainText('開きました', { timeout: 30_000 });
  await dialog.getByTestId('projects-close').click();
  await expect(dialog).toHaveCount(0);
}

async function graphNodeIds(page: Page): Promise<string[]> {
  const graph = await (await page.request.get('/api/graph')).json();
  return (graph.nodes as { id: string }[]).map((n) => n.id);
}

/** Back to the lab's own project; wait until its talker is on the graph and the pipeline is gone. */
async function backToLabProject(page: Page) {
  await page.request.delete(`/api/targets/${CONTAINER_TARGET}`);
  await page.request.post('/api/projects/open', { data: { id: LAB_PROJECT } });
  await expect.poll(async () => {
    const ids = await graphNodeIds(page);
    return ids.includes('/talker') && !ids.includes('/src_0') && !ids.includes('/pipeline_container');
  }, { timeout: 90_000 }).toBe(true);
}

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterEach(({ page }) => backToLabProject(page));

test('medium pipeline: 20 nodes on the map with flowing edges, one process each', async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto('/');
  await openProject(page, 'example:pipeline_medium');
  await page.getByTestId('tab-graph').click();
  const outline = page.getByTestId('graph-outline');
  for (const node of NODES) {
    await expect(outline.locator(`[data-id="n:/${node}"]`)).toHaveCount(1, { timeout: 90_000 });
  }
  await expect(outline.locator('[data-id="n:/relay_2_1"]')).toHaveAttribute('data-role', 'mine');
  // every topic is a half-rate branch of the 10 Hz sources (round robin): ~5 Hz on each edge
  await expect(outline.locator('[data-id="e:pub:/src_0:/pipe/src_0"]')).toContainText('Hz', { timeout: 30_000 });
  await expect(outline.locator('[data-id="e:pub:/relay_3_2:/pipe/relay_3_2"]')).toContainText('Hz', { timeout: 30_000 });
  await page.waitForTimeout(3000); // layout animation + particles
  await page.getByRole('button', { name: '全体を表示' }).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}pipeline-medium-map.png` });

  // The real 20-node map with live traffic keeps a smooth frame rate (headless, shared machine).
  const fps = await page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        let frames = 0;
        const start = performance.now();
        const loop = (now: number) => {
          frames += 1;
          if (now - start < 3000) requestAnimationFrame(loop);
          else resolve((frames * 1000) / (now - start));
        };
        requestAnimationFrame(loop);
      }),
  );
  test.info().annotations.push({ type: 'fps', description: fps.toFixed(1) });
  expect(fps).toBeGreaterThan(30);

  await page.getByTestId('tab-nodes').click();
  await expect(page.getByTestId('node-row-/sink_3')).toBeVisible({ timeout: 15_000 });
});

test('the same pipeline in a composable container: one group, stopping one node asks about all', async ({ page }) => {
  test.setTimeout(180_000);
  const created = await page.request.post('/api/targets', {
    data: {
      id: CONTAINER_TARGET, kind: 'launch', package: 'roshanavi_examples', launch_file: 'pipeline.launch.py',
      args: ['spec:=/examples/pipeline_medium/pipeline.json', 'mode:=container'], role: 'mine',
    },
  });
  expect(created.status()).toBe(201);
  await page.request.post(`/api/targets/${CONTAINER_TARGET}/start`);
  await page.goto('/');
  await expect.poll(async () => {
    const ids = await graphNodeIds(page);
    return NODES.every((n) => ids.includes(`/${n}`));
  }, { timeout: 120_000 }).toBe(true);

  await page.getByTestId('tab-nodes').click();
  const group = page.getByTestId(`node-group-${CONTAINER_TARGET}`);
  await expect(group).toBeVisible({ timeout: 30_000 });
  await expect(group).toContainText('pipeline.launch.py');
  await expect(group).toContainText(/この 2\d 個/); // 20 pipeline nodes + the container + the launch service
  await page.screenshot({ path: `${SHOTS}pipeline-container-nodes.png` });

  // Checking one node and stopping it: the dialog names the container's other nodes too.
  await page.getByTestId('node-check-/relay_2_1').check();
  await page.getByTestId('nodes-bulk-stop').click();
  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible();
  for (const node of ['/pipeline_container', '/src_0', '/relay_2_1', '/sink_3']) {
    await expect(dialog).toContainText(node);
  }
  await page.keyboard.press('Escape'); // do not stop it here; the API test covers the stop itself
  await expect(dialog).toHaveCount(0);
});
