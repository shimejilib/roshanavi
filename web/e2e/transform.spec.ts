import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { rightClickNode } from './helpers';

// P5 transform nodes: topic menu -> editor with live preview -> node on the map -> echo.
const SHOTS = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
const NAME = 'chatter_upper';

async function openMap(page: Page) {
  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');
  await expect(page.getByTestId('graph-outline').locator('[data-id="t:/chatter"]')).toHaveCount(1, { timeout: 30_000 });
  await page.waitForTimeout(1500); // layout animation
}

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterEach(async ({ page }) => {
  await page.request.delete(`/api/targets/${NAME}`);
});

test('topic menu -> transform /chatter to upper case -> it runs and echoes upper case', async ({ page }) => {
  await openMap(page);
  await rightClickNode(page, 't:/chatter');
  await page.getByTestId('map-menu').getByTestId('menu-createTransform').click();

  const dialog = page.getByTestId('create-transform-dialog');
  await expect(dialog.getByTestId('transform-input-topic-0')).toHaveValue('/chatter');
  await expect(dialog.getByTestId('transform-input-type-0')).toHaveValue('std_msgs/msg/String');
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
