import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// データの種類: beginners pick what they send (文字列, 数値 ...), never a ROS type name.
// 詳細設定モード (⚙ 設定, remembered by the browser) lists ROS types grouped: common first.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const INPUT_ID = 'e2e_kind_input';
const TOPIC = '/e2e_kind_text';

async function setAdvanced(page: Page, on: boolean) {
  await page.getByTestId('app-settings').click();
  const box = page.getByTestId('advanced-mode');
  if ((await box.isChecked()) !== on) await box.click();
  await page.getByTestId('app-settings').click();
}

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterEach(async ({ page }) => {
  await page.request.delete(`/api/targets/${INPUT_ID}`);
});

test('create an input node of kind 文字列 without seeing any ROS type', async ({ page }) => {
  await page.goto('/');
  await setAdvanced(page, false);
  await page.getByTestId('create-input').click();
  const dialog = page.getByTestId('create-input-dialog');
  await dialog.getByTestId('input-topic').fill(TOPIC);
  await expect(dialog).toContainText('新しいトピックです');
  const kind = dialog.getByTestId('input-type-kind');
  await expect(kind.locator('option')).toContainText(['文字列', '数値 (小数)', '整数', 'ON / OFF', '数値の並び', 'JSON (複数の値をまとめて)', '画像', '音声', 'バイト列 (生データ)']);
  // A number shows a value field, no YAML; then back to text.
  await kind.selectOption('float');
  await expect(dialog.getByTestId('input-text')).toHaveValue('1.5');
  await expect(dialog.getByTestId('input-yaml')).toHaveCount(0);
  await kind.selectOption('string');
  await expect(dialog.getByTestId('input-text')).toHaveValue('hello');
  await dialog.getByTestId('input-text').fill('kind check');
  await dialog.getByTestId('input-name').fill(INPUT_ID);
  await dialog.getByTestId('input-rate').fill('2');
  await expect(dialog).not.toContainText('std_msgs');
  await expect(dialog).not.toContainText('/msg/');
  await page.screenshot({ path: `${SHOTS}data-kind-picker.png` });
  await dialog.getByTestId('input-submit').click();
  await expect(dialog).toHaveCount(0);

  await expect(page.getByTestId('detail-title')).toHaveText(TOPIC);
  await expect(page.getByTestId('echo-body')).toContainText('kind check', { timeout: 20_000 });
  const project = await (await page.request.get('/api/project')).json();
  const saved = project.project.dummies.find((d: { id: string }) => d.id === INPUT_ID);
  expect(saved).toMatchObject({ kind: 'string', type: 'std_msgs/msg/String', payload: { data: 'kind check' } });

  // The same topic now exists: the dialog shows what it carries instead of a picker.
  await page.getByTestId('create-input').click();
  await page.getByTestId('create-input-dialog').getByTestId('input-topic').fill(TOPIC);
  await expect(page.getByTestId('input-type-detected')).toContainText('このトピックは 文字列 (std_msgs/String) です', { timeout: 10_000 });
  await expect(page.getByTestId('input-type-kind')).toHaveCount(0);
  await page.keyboard.press('Escape');
});

test('詳細設定モード lists ROS types common-first and is remembered', async ({ page }) => {
  await page.goto('/');
  await setAdvanced(page, true);
  await page.reload();
  await page.getByTestId('app-settings').click();
  await expect(page.getByTestId('advanced-mode')).toBeChecked();
  await page.getByTestId('app-settings').click();
  await page.getByTestId('create-input').click();
  const dialog = page.getByTestId('create-input-dialog');
  await dialog.getByTestId('input-topic').fill('/e2e_kind_raw');
  const raw = dialog.getByTestId('input-type-raw-type');
  await expect(raw.locator('optgroup').first()).toHaveAttribute('label', 'よく使う型');
  await expect(raw.locator('optgroup').first().locator('option').first()).toHaveText('std_msgs/msg/String');
  await dialog.getByTestId('input-type-raw-search').fill('twist');
  await expect(raw.locator('optgroup').first().locator('option').first()).toHaveText('geometry_msgs/msg/Twist');
  await raw.selectOption('geometry_msgs/msg/Twist');
  await expect(dialog.getByTestId('input-type-kind')).toHaveValue('message');
  await expect(dialog.getByTestId('input-yaml')).toHaveValue(/linear:/, { timeout: 10_000 });
  await page.keyboard.press('Escape');
  await setAdvanced(page, false);
});
