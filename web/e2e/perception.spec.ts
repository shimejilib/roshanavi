import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// P5 perception demo: switch projects from the ⚙ settings menu, then see the sample
// nodes on the map and image_filter's output in the image viewer. Switches back afterwards.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));

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

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
// Back to the lab's own project; wait until its talker is on the graph again for the next tests.
test.afterAll(async ({ request }) => {
  await request.post('/api/projects/open', { data: { id: 'data:roshanavi.yaml' } });
  await expect.poll(async () => {
    const graph = await (await request.get('/api/graph')).json();
    const ids = (graph.nodes as { id: string }[]).map((n) => n.id);
    return ids.includes('/talker') && !ids.includes('/image_filter');
  }, { timeout: 60_000 }).toBe(true);
});

test('perception demo: video -> image_filter -> blob_detector, viewer shows the gray image', async ({ page }) => {
  test.setTimeout(150_000);
  await page.goto('/');
  await openProject(page, 'example:perception_demo');

  await page.getByTestId('tab-graph').click();
  const outline = page.getByTestId('graph-outline');
  for (const node of ['/image_filter', '/blob_detector', '/audio_level', '/dummy_camera', '/blob_count']) {
    await expect(outline.locator(`[data-id="n:${node}"]`)).toHaveCount(1, { timeout: 60_000 });
  }
  await expect(outline.locator('[data-id="n:/blob_count"]')).toHaveAttribute('data-role', 'transform');
  await expect(outline.locator('[data-id="t:/camera/detections"]')).toHaveCount(1, { timeout: 30_000 });
  await page.waitForTimeout(3000); // layout animation
  await page.getByRole('button', { name: '全体を表示' }).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}perception-demo-map.png` });

  await page.getByTestId('tab-traffic').click();
  const row = page.locator('tr[data-topic="/camera/gray"]');
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.click();
  const img = page.getByTestId('image-viewer');
  await expect(img).toBeVisible({ timeout: 30_000 });
  await expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth), { timeout: 20_000 }).toBe(320);

  const count = page.locator('tr[data-topic="/camera/blob_count"]');
  await expect(count).toBeVisible({ timeout: 30_000 });
  await count.click();
  await expect(page.getByTestId('echo-body')).toContainText('"data"', { timeout: 20_000 });
});
