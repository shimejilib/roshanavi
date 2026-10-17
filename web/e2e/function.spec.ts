import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { CHATTER_KIND_LABEL, rightClickNode } from './helpers';

// Function nodes (#29): a plain Python function of a workspace package run as a node.
// Uses roshanavi_examples.logic.shout on /chatter (the demo talker) -> /e2e_shouted.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const NAME = 'e2e_shout';

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterEach(async ({ page }) => {
  await page.request.delete(`/api/targets/${NAME}`);
});

test('create a function node from the example module; its output is echoed', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('graph-outline').locator('[data-id="t:/chatter"]')).toHaveCount(1, { timeout: 20_000 });
  await page.getByTestId('create-function').click();
  const dialog = page.getByTestId('create-function-dialog');
  await dialog.getByTestId('function-module').selectOption('roshanavi_examples.logic');
  // Signatures come from a static parse of the file (the server never imports user code).
  await expect(dialog.getByTestId('function-name').locator('option')).toContainText(['shout(text: str) -> str', 'add(a: float, b: float) -> float']);
  await dialog.getByTestId('function-name').selectOption('shout');
  await expect(dialog.getByTestId('function-signature')).toContainText('roshanavi_examples/logic.py');
  await expect(dialog.getByTestId('function-call-on_message')).toBeChecked();
  await dialog.getByTestId('function-node-name').fill(NAME);
  await dialog.getByTestId('function-input-0-topic').fill('/chatter');
  await expect(dialog.getByTestId('function-input-0-type-detected')).toContainText(CHATTER_KIND_LABEL);
  await dialog.getByTestId('function-output-topic').fill('/e2e_shouted');
  // The return annotation `-> str` already chose 文字列 for the new output topic.
  await expect(dialog.getByTestId('function-output-type-kind')).toHaveValue('string');
  await page.screenshot({ path: `${SHOTS}function-dialog.png` });
  await dialog.getByTestId('function-submit').click();
  await expect(dialog).toHaveCount(0);

  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator(`[data-id="n:/${NAME}"]`)).toHaveAttribute('data-role', 'function', { timeout: 30_000 });
  await expect(page.getByTestId('detail-title')).toHaveText('/e2e_shouted');
  await expect(page.getByTestId('echo-body')).toContainText('HELLO WORLD', { timeout: 20_000 });
  await expect(page.getByTestId('echo-body')).toContainText('!');

  const project = await (await page.request.get('/api/project')).json();
  const saved = project.project.functions.find((f: { id: string }) => f.id === NAME);
  expect(saved).toMatchObject({ module: 'roshanavi_examples.logic', function: 'shout', inputs: [{ topic: '/chatter', kind: 'string' }] });

  // The edit dialog (map menu) shows the live status of the running function.
  await page.waitForTimeout(1500); // layout animation
  await rightClickNode(page, `n:/${NAME}`);
  await page.getByTestId('map-menu').getByTestId('menu-editFunction').click();
  const edit = page.getByTestId('create-function-dialog');
  await expect(edit.getByTestId('function-status')).toHaveAttribute('data-state', 'running', { timeout: 10_000 });
  await expect(edit.getByTestId('function-stats')).toContainText('送信');
  await expect(edit.getByTestId('function-export')).toBeVisible();
  await page.keyboard.press('Escape');
});
