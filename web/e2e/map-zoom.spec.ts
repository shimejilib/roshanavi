import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Zoom control in the bottom-right corner of the map (docs/design/ui.md "地図の操作"):
// ＋ / − / 100% / 全体を表示 and the zoom percentage, in step with cytoscape's own zoom.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));

type Cy = {
  zoom: (level?: number) => number;
  width: () => number;
  height: () => number;
  pan: () => { x: number; y: number };
  maxZoom: () => number;
  minZoom: () => number;
};
type Reg = { _cyreg: { cy: Cy } };

const zoomOf = (page: Page) => page.getByTestId('graph-canvas').evaluate((el) => (el as unknown as Reg)._cyreg.cy.zoom());
const setZoom = (page: Page, level: number) => page.getByTestId('graph-canvas').evaluate((el, z) => { (el as unknown as Reg)._cyreg.cy.zoom(z); }, level);
/** The model-space point at the centre of the visible map (what ＋ / − / 100% must keep in place). */
const centreOf = (page: Page) => page.getByTestId('graph-canvas').evaluate((el) => {
  const cy = (el as unknown as Reg)._cyreg.cy;
  const z = cy.zoom();
  return { x: (cy.width() / 2 - cy.pan().x) / z, y: (cy.height() / 2 - cy.pan().y) / z };
});

async function openMap(page: Page) {
  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');
  await expect(page.getByTestId('graph-outline').locator('[data-id="n:/talker"]')).toHaveCount(1, { timeout: 20_000 });
  await page.waitForTimeout(1500); // layout animation
}

const percentOf = async (page: Page) => (await page.getByTestId('map-zoom-percent').textContent()) ?? '';
const expectPercentMatchesZoom = async (page: Page) => {
  await expect.poll(async () => percentOf(page)).toBe(`${Math.round((await zoomOf(page)) * 100)}%`);
};

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));

test('＋ / − / 100% / 全体を表示 change the zoom and the percentage follows', async ({ page }) => {
  await openMap(page);
  const control = page.getByTestId('map-zoom');
  await expect(control).toBeVisible();
  // Real buttons with a Japanese name and a title (keyboard focusable).
  for (const [id, name] of [['out', '縮小'], ['in', '拡大'], ['actual', '表示倍率を 100% に戻す'], ['fit', '全体を表示']] as const) {
    const button = page.getByTestId(`map-zoom-${id}`);
    await expect(button).toHaveAccessibleName(name);
    await expect(button).toHaveAttribute('title', /.+/);
  }

  await page.getByTestId('map-zoom-fit').click();
  await expectPercentMatchesZoom(page);
  const fitted = await zoomOf(page);
  expect(fitted).toBeLessThanOrEqual(1.3 + 1e-6); // the same cap as the top bar button
  // Same result as the top bar's 全体を表示.
  await setZoom(page, 0.5);
  await page.getByTestId('fit-all').click();
  expect(await zoomOf(page)).toBeCloseTo(fitted, 3);

  // ＋ : ×1.25 around the centre of the visible map.
  await setZoom(page, 0.8);
  await expect(page.getByTestId('map-zoom-percent')).toHaveText('80%');
  const centre = await centreOf(page);
  await page.getByTestId('map-zoom-in').click();
  expect(await zoomOf(page)).toBeCloseTo(1.0, 3);
  await expect(page.getByTestId('map-zoom-percent')).toHaveText('100%');
  const afterIn = await centreOf(page);
  expect(afterIn.x).toBeCloseTo(centre.x, 1);
  expect(afterIn.y).toBeCloseTo(centre.y, 1);

  // − : ÷1.25.
  await page.getByTestId('map-zoom-out').click();
  expect(await zoomOf(page)).toBeCloseTo(0.8, 3);
  await expect(page.getByTestId('map-zoom-percent')).toHaveText('80%');

  // 100% : zoom 1, centre kept.
  await setZoom(page, 0.37);
  const centre2 = await centreOf(page);
  await page.getByTestId('map-zoom-actual').click();
  expect(await zoomOf(page)).toBeCloseTo(1, 3);
  await expect(page.getByTestId('map-zoom-percent')).toHaveText('100%');
  const after100 = await centreOf(page);
  expect(after100.x).toBeCloseTo(centre2.x, 1);
  expect(after100.y).toBeCloseTo(centre2.y, 1);

  // The wheel updates the percentage too.
  const box = await page.getByTestId('graph-canvas').boundingBox();
  if (!box) throw new Error('graph canvas not visible');
  await page.mouse.move(box.x + box.width / 2, box.y + 40);
  await page.mouse.wheel(0, -300);
  await expect.poll(() => zoomOf(page)).toBeGreaterThan(1);
  await expectPercentMatchesZoom(page);
});

test('＋ is disabled at the maximum zoom and − at the minimum', async ({ page }) => {
  await openMap(page);
  const zoomIn = page.getByTestId('map-zoom-in');
  const zoomOut = page.getByTestId('map-zoom-out');
  await setZoom(page, 1);
  await expect(zoomIn).toBeEnabled();
  await expect(zoomOut).toBeEnabled();

  await setZoom(page, 3.5);
  await zoomIn.click(); // 3.5 x 1.25 > 4: clamped to the maximum
  expect(await zoomOf(page)).toBeCloseTo(4, 3);
  await expect(page.getByTestId('map-zoom-percent')).toHaveText('400%');
  await expect(zoomIn).toBeDisabled();
  await expect(zoomOut).toBeEnabled();

  await setZoom(page, 0.11);
  await zoomOut.click();
  expect(await zoomOf(page)).toBeCloseTo(0.1, 3);
  await expect(page.getByTestId('map-zoom-percent')).toHaveText('10%');
  await expect(zoomOut).toBeDisabled();
  await expect(zoomIn).toBeEnabled();
});

test('the control sits in the bottom-right corner, clear of the legend, and shows a focus ring', async ({ page }) => {
  await openMap(page);
  await page.getByTestId('map-zoom-fit').click();
  const control = page.getByTestId('map-zoom');
  const box = await control.boundingBox();
  const map = await page.getByTestId('graph-canvas').boundingBox();
  const legend = await page.getByRole('list', { name: 'legend' }).boundingBox();
  if (!box || !map || !legend) throw new Error('map, legend or zoom control not visible');
  // Inside the map's bottom-right corner.
  expect(box.x + box.width).toBeLessThanOrEqual(map.x + map.width);
  expect(box.y + box.height).toBeLessThanOrEqual(map.y + map.height);
  expect(box.x).toBeGreaterThan(map.x + map.width / 2);
  expect(box.y).toBeGreaterThan(map.y + map.height / 2);
  // Not over the legend.
  const apart = box.x >= legend.x + legend.width || legend.x >= box.x + box.width || box.y >= legend.y + legend.height || legend.y >= box.y + box.height;
  expect(apart, 'zoom control overlaps the legend').toBe(true);

  // Keyboard: Tab reaches the buttons, the focused one gets an outline.
  await page.getByTestId('map-zoom-out').focus();
  await page.keyboard.press('Tab'); // -> ＋ (the percentage is not focusable)
  await expect(page.getByTestId('map-zoom-in')).toBeFocused();
  await expect(page.getByTestId('map-zoom-in')).toHaveCSS('outline-style', 'solid');
  const before = await zoomOf(page);
  await page.keyboard.press('Enter');
  await expect.poll(() => zoomOf(page)).toBeGreaterThan(before);

  await page.mouse.move(map.x + 40, map.y + 40);
  await page.screenshot({ path: `${SHOTS}map-zoom-controls.png` });
});

test('works in the dark theme', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await openMap(page);
  const control = page.getByTestId('map-zoom');
  await expect(control).toBeVisible();
  await expect(page.getByTestId('map-zoom-percent')).toBeVisible();
  // The page really is in the dark theme (body background), and the panel follows its tokens.
  const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const channels = background.match(/[\d.]+/g)?.slice(0, 3).map(Number) ?? [255, 255, 255];
  expect(Math.max(...channels)).toBeLessThan(100);
  await page.getByTestId('map-zoom-in').click();
});
