import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Requires `docker compose up -d lab demo` (demo runs the lifecycle node lc_talker).
// Node list tab: bulk stop / start of talker + listener, lifecycle transitions of an
// external lifecycle node, and the launch decomposition import.
const SHOTS = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
const IMPORTED = ['imported_talker', 'imported_listener'];

async function openNodes(page: Page) {
  await page.goto('/');
  await page.getByTestId('tab-nodes').click();
  await expect(page.getByTestId('node-table')).toBeVisible();
}

async function confirm(page: Page) {
  await expect(page.getByTestId('confirm-dialog')).toBeVisible();
  await page.getByTestId('confirm-ok').click();
}

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));

test('bulk stop and start talker + listener with checkboxes', async ({ page }) => {
  await openNodes(page);
  await expect(page.getByTestId('node-row-/talker')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('node-check-/external_talker')).toBeDisabled();
  await expect(page.getByTestId('nodes-import-hint')).toBeVisible();
  await page.getByTestId('node-check-/listener').check();
  // Keyboard: ↓ moves to the next row's checkbox (/talker sorts after /listener), Space selects it.
  await page.getByTestId('node-check-/listener').focus();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByTestId('node-check-/talker')).toBeFocused();
  await page.keyboard.press('Space');
  await expect(page.getByTestId('node-check-/talker')).toBeChecked();
  await expect(page.getByTestId('nodes-selected')).toContainText('2 個選択');
  await page.screenshot({ path: `${SHOTS}node-list.png` });

  await page.getByTestId('nodes-bulk-stop').click();
  await expect(page.getByTestId('confirm-dialog')).toContainText('/talker');
  await expect(page.getByTestId('confirm-dialog')).toContainText('/listener');
  await confirm(page);
  await expect(page.getByTestId('node-row-target:talker')).toHaveAttribute('data-status', 'stopped', { timeout: 20_000 });
  await expect(page.getByTestId('node-row-target:listener')).toHaveAttribute('data-status', 'stopped', { timeout: 20_000 });

  await page.getByTestId('nodes-status').selectOption('stopped');
  await page.getByTestId('node-check-target:talker').check();
  await page.getByTestId('node-check-target:listener').check();
  await page.getByTestId('nodes-bulk-start').click();
  await confirm(page);
  await page.getByTestId('nodes-status').selectOption('all');
  await expect(page.getByTestId('node-row-/talker')).toHaveAttribute('data-status', /starting|running/, { timeout: 20_000 });
  await expect(page.getByTestId('node-row-/listener')).toHaveAttribute('data-status', /starting|running/, { timeout: 20_000 });
});

async function transition(page: Page, label: string, expected: string) {
  await page.getByTestId(`lifecycle-${label}`).click();
  await expect(page.getByTestId('confirm-dialog')).toContainText('roshanavi が起動していないノード');
  await page.getByTestId('confirm-ok').click();
  await expect(page.getByTestId('lifecycle-state')).toContainText(expected, { timeout: 15_000 });
}

test('deactivate and activate an external lifecycle node', async ({ page }) => {
  await openNodes(page);
  const row = page.getByTestId('node-row-/lc_talker');
  await expect(row).toHaveAttribute('data-control', 'lifecycle', { timeout: 15_000 });
  await expect(page.getByTestId('node-check-/lc_talker')).toBeEnabled();
  await page.getByTestId('lc-open-/lc_talker').click();
  const dialog = page.getByTestId('lifecycle-dialog');
  await expect(dialog.getByTestId('lifecycle-state')).not.toContainText('取得', { timeout: 10_000 });
  if (await page.getByTestId('lifecycle-configure').isVisible()) await transition(page, 'configure', '(inactive)');
  if (await page.getByTestId('lifecycle-activate').isVisible()) await transition(page, 'activate', '(active)');
  await expect(page.getByTestId('lifecycle-deactivate')).toBeEnabled();
  await page.screenshot({ path: `${SHOTS}lifecycle.png` });
  await transition(page, 'deactivate', '(inactive)');
  await transition(page, 'activate', '(active)');
  // Leave the demo as it started (unconfigured) for the next run.
  await transition(page, 'deactivate', '(inactive)');
  await transition(page, 'cleanup', '(unconfigured)');
  await dialog.getByRole('button', { name: '閉じる' }).last().click();
  await expect(page.getByTestId('lc-state-/lc_talker')).toContainText('unconfigured', { timeout: 10_000 });
});

test('import a launch file as per-node targets', async ({ page }) => {
  for (const id of IMPORTED) await page.request.delete(`/api/targets/${id}`);
  await openNodes(page);
  await page.getByTestId('nodes-import').click();
  await page.getByTestId('import-package').selectOption('roshanavi');
  await page.getByTestId('import-file').selectOption('demo_system.launch.py');
  await page.getByTestId('import-analyse').click();
  const preview = page.getByTestId('import-preview');
  await expect(preview).toContainText('/demo_robot/imported_talker', { timeout: 30_000 });
  await expect(preview).toContainText('/demo_robot/imported_listener');
  await expect(page.getByTestId('import-blocked')).toContainText('ExecuteProcess');
  await expect(page.getByTestId('import-args')).toBeVisible();
  await page.getByTestId('import-blocked').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}launch-import-preview.png` });
  await page.getByTestId('import-commit').click();
  await expect(page.getByTestId('import-done')).toContainText('2 個を起動リストに取り込みました');
  await page.getByTestId('import-dialog').getByRole('button', { name: '閉じる' }).last().click();
  for (const id of IMPORTED) {
    await expect(page.getByTestId(`node-row-target:${id}`)).toContainText('取り込み元: roshanavi/demo_system.launch.py', { timeout: 10_000 });
  }
  for (const id of IMPORTED) await page.request.delete(`/api/targets/${id}`);
});
