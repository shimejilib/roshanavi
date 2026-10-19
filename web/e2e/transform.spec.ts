import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { CHATTER_KIND_LABEL, rightClickNode } from './helpers';

// P5 transform nodes: topic menu -> editor with live preview -> node on the map -> echo.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const NAME = 'chatter_upper';
const ARRAY_INPUT = 'e2e_long_array';

async function openMap(page: Page) {
  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');
  await expect(page.getByTestId('graph-outline').locator('[data-id="t:/chatter"]')).toHaveCount(1, { timeout: 30_000 });
  await page.waitForTimeout(1500); // layout animation
}

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterEach(async ({ page }) => {
  await page.request.delete(`/api/targets/${NAME}`);
  await page.request.delete(`/api/targets/${ARRAY_INPUT}`);
});

test('topic menu -> transform /chatter to upper case -> it runs and echoes upper case', async ({ page }) => {
  await openMap(page);
  await rightClickNode(page, 't:/chatter');
  await page.getByTestId('map-menu').getByTestId('menu-createTransform').click();

  const dialog = page.getByTestId('create-transform-dialog');
  await expect(dialog.getByTestId('transform-input-topic-0')).toHaveValue('/chatter');
  await expect(dialog.getByTestId('transform-input-type-0-detected')).toContainText(CHATTER_KIND_LABEL);
  await dialog.getByTestId('transform-name').fill(NAME);
  await dialog.getByTestId('transform-output-topic').fill('/chatter_upper');
  // The starting mapping copies the field; then write the expression.
  await expect(dialog.getByTestId('transform-mapping')).toHaveValue(/\$\{msg\.data\}/, { timeout: 10_000 });

  // A mistake is explained in plain Japanese at the field.
  await dialog.getByTestId('transform-mapping').fill('data: ${upper(msg.nope)}');
  await expect(dialog.getByTestId('transform-field-errors')).toContainText('フィールド「nope」はありません', { timeout: 10_000 });

  await dialog.getByTestId('transform-mapping').fill('data: ${upper(msg.data)}');
  await expect(dialog.getByTestId('transform-preview-input-msg')).toContainText('Hello World', { timeout: 15_000 });
  await expect(dialog.getByTestId('transform-preview-output')).toContainText('HELLO WORLD', { timeout: 10_000 });
  // Scroll so the mapping and the preview (input left, output right) are both in view.
  await dialog.getByTestId('transform-output-topic').evaluate((el) => el.scrollIntoView({ block: 'start' }));
  await page.screenshot({ path: `${SHOTS}transform-editor.png` });
  await dialog.getByTestId('transform-submit').click();
  await expect(dialog).toHaveCount(0);

  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator(`[data-id="n:/${NAME}"]`)).toHaveAttribute('data-role', 'transform', { timeout: 30_000 });
  await expect(outline.locator('[data-id="t:/chatter_upper"]')).toHaveCount(1);
  await expect(page.getByTestId('detail-title')).toHaveText('/chatter_upper');
  await expect(page.getByTestId('echo-body')).toContainText('HELLO WORLD', { timeout: 20_000 });

  const project = await (await page.request.get('/api/project')).json();
  expect(project.project.transforms[0].mapping).toEqual({ data: '${upper(msg.data)}' });
  await page.waitForTimeout(1500);
  await rightClickNode(page, `n:/${NAME}`);
  await expect(page.getByTestId('menu-editTransform')).toBeEnabled();
  await page.keyboard.press('Escape');
});

test('the preview computes on the whole array, not the 32-item echo copy', async ({ page }) => {
  const created = await page.request.post('/api/dummies?start=true', {
    data: {
      id: ARRAY_INPUT, name: ARRAY_INPUT, topic: '/e2e_long_array', type: 'std_msgs/msg/Int32MultiArray',
      mode: 'periodic', payload: { data: Array.from({ length: 40 }, (_, i) => i) }, rate_hz: 2,
    },
  });
  expect(created.ok()).toBeTruthy();
  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');
  // The echo of an input that does not exist yet is refused for good: wait for the topic first.
  await expect(page.getByTestId('graph-outline').locator('[data-id="t:/e2e_long_array"]')).toHaveCount(1, { timeout: 30_000 });
  await page.getByTestId('create-transform').click();
  const dialog = page.getByTestId('create-transform-dialog');
  await dialog.getByTestId('transform-input-topic-0').fill('/e2e_long_array');
  await dialog.getByTestId('transform-output-topic').fill('/e2e_long_array_len');
  await dialog.getByTestId('transform-output-type-kind').selectOption('int');
  await dialog.getByTestId('transform-mapping').fill('data: ${len(msg.data)}');
  // The left pane is the echo view's copy (cut to 32 items); the output is computed on all 40.
  await expect(dialog.getByTestId('transform-preview-input-msg')).toContainText('_truncated', { timeout: 20_000 });
  await expect(dialog.getByTestId('transform-preview-output')).toContainText('40', { timeout: 20_000 });
  await expect(dialog.getByTestId('transform-preview-truncated')).toHaveCount(0);
});
