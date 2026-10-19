import { expect, test, type Locator, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { CHATTER_KIND_LABEL, clickElement } from './helpers';

// In-app tours: every tour is followed the way a learner would, by its own instructions and
// through the `data-tour` marks, so a UI change that breaks a tour fails here. Each tour must also
// finish and remove what it created.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const STORAGE_KEY = 'roshanavi.tour.v1';

// These specs start from an empty browser storage (the other specs start with the welcome card dismissed).
test.use({ storageState: { cookies: [], origins: [] } });
test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));

const LEFTOVER_TARGETS = ['dummy_hello', 'tour_qos_pub', 'tour_qos_sub', 'tour_chatter_src', 'tour_shout', 'shout', 'dummy_hello-2'];
const LEFTOVER_SCENARIOS = ['project:tour_scenario.yaml'];

async function cleanUp(page: Page) {
  for (const id of LEFTOVER_TARGETS) await page.request.delete(`/api/targets/${id}`);
  for (const id of LEFTOVER_SCENARIOS) await page.request.delete(`/api/scenarios/${encodeURIComponent(id)}`);
  await page.request.delete('/api/scenario-record?discard=true');
}
test.beforeEach(({ page }) => cleanUp(page));
test.afterEach(({ page }) => cleanUp(page));

const popover = (page: Page) => page.locator('.driver-popover.rn-tour');
const mark = (page: Page, name: string): Locator => page.locator(`[data-tour="${name}"]:visible`).first();
const progressOf = async (page: Page) => (await popover(page).locator('.driver-popover-progress-text').textContent()) ?? '';

/** The tour is on the step with this title (the instruction the learner reads). */
async function onStep(page: Page, title: string, body?: string) {
  await expect(popover(page).locator('.driver-popover-title')).toHaveText(title, { timeout: 30_000 });
  if (body) await expect(popover(page).locator('.driver-popover-description')).toContainText(body);
}

/** A screenshot once the highlight and popover have stopped moving (the move takes 250 ms). */
async function shot(page: Page, name: string) {
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}${name}.png` });
}

const next = (page: Page) => popover(page).getByRole('button', { name: '次へ' }).click();

async function startFromSettings(page: Page, id: string) {
  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open', { timeout: 20_000 });
  await page.getByTestId('tour-welcome-later').click();
  await mark(page, 'settings').click();
  await page.getByTestId(`tour-start-${id}`).click();
}

async function expectCompleted(page: Page, id: string) {
  await expect(popover(page)).toHaveCount(0);
  const stored = await page.evaluate((key) => JSON.parse(window.localStorage.getItem(key) ?? '{}'), STORAGE_KEY);
  expect(stored.completed).toContain(id);
  expect(stored.run).toBeNull();
}

async function targetIds(page: Page): Promise<string[]> {
  const body = (await (await page.request.get('/api/targets')).json()) as { targets: { id: string }[] };
  return body.targets.map((tg) => tg.id);
}

test('first launch asks once; later it is only in ⚙ 設定', async ({ page }) => {
  await page.goto('/');
  const card = page.locator('[data-tour="welcome"]');
  await expect(card).toContainText('チュートリアルを始めますか?');
  await shot(page, 'tour-welcome');
  await page.getByTestId('tour-welcome-later').click();
  await expect(card).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open', { timeout: 20_000 });
  await expect(card).toHaveCount(0);
  await mark(page, 'settings').click();
  for (const name of ['画面の見方', 'はじめての入力ノード', '届かない原因を見つけて直す', '関数ノードを作る', 'シナリオを記録する']) {
    await expect(page.locator('.tour-settings')).toContainText(name);
  }
  await expect(page.getByTestId('tour-item-overview')).toHaveAttribute('data-done', 'false');
});

test('画面の見方: eleven steps, nothing to operate; Esc pauses, a reload and 続ける resume', async ({ page }) => {
  await startFromSettings(page, 'overview');
  await onStep(page, '画面の見方');
  expect(await progressOf(page)).toBe('1 / 11');
  await next(page);
  // The pub/sub primer (docs/design/wiring.md §5) opens on the map for this step only.
  await onStep(page, 'しくみの 1 枚絵');
  await expect(page.locator('.driver-active-element[data-tour="primer"]')).toHaveCount(1);
  await expect(page.getByTestId('primer')).toContainText('名前付きのトピック');
  await shot(page, 'tour-primer');
  await next(page);
  await expect(page.getByTestId('primer')).toHaveCount(0);
  await onStep(page, '通信マップ');
  await expect(page.locator('.driver-active-element[data-tour="map"]')).toHaveCount(1);
  await shot(page, 'tour-overview');

  // Keyboard only: the 次へ button has the focus, so Enter goes on (and back is 戻る).
  await page.keyboard.press('Enter');
  await onStep(page, '凡例');
  await popover(page).getByRole('button', { name: '戻る' }).click();
  await onStep(page, '通信マップ');

  // Esc pauses; the pill brings it back after a reload, at the same step.
  await page.keyboard.press('Escape');
  await expect(popover(page)).toHaveCount(0);
  await expect(page.locator('[data-tour="paused"]')).toContainText('画面の見方');
  await page.reload();
  await expect(page.locator('[data-tour="paused"]')).toBeVisible();
  await page.getByTestId('tour-resume').click();
  await onStep(page, '通信マップ');

  for (const title of ['凡例', '診断パネル', '最終更新', 'トラフィック']) {
    await next(page);
    await onStep(page, title);
  }
  await next(page);
  await onStep(page, 'トピック別 / ノード別');
  await expect(page.getByTestId('tab-traffic')).toHaveAttribute('aria-selected', 'true'); // switched by the tour
  await next(page);
  await onStep(page, 'ノード一覧');
  await expect(page.getByTestId('tab-nodes')).toHaveAttribute('aria-selected', 'true');
  await next(page);
  await onStep(page, '⚙ 設定');
  await next(page);
  await onStep(page, 'おしまい', 'docs/design/ui.md');
  await popover(page).getByRole('button', { name: '終わる' }).click();
  await expectCompleted(page, 'overview');
  await page.getByTestId('app-settings').click();
  await expect(page.getByTestId('tour-item-overview')).toHaveAttribute('data-done', 'true');
});

test('はじめての入力ノード: kind → /hello → value → create → click node and topic → clean up', async ({ page }) => {
  await startFromSettings(page, 'firstInput');
  await onStep(page, '入力ノードを作る');
  await mark(page, 'create-input').click();
  await onStep(page, 'データの種類');
  await expect(mark(page, 'input-type-kind')).toHaveValue('string');
  await next(page);
  await onStep(page, 'トピック名');
  await mark(page, 'input-topic').fill('/hello');
  await onStep(page, '送る中身');
  await shot(page, 'tour-first-input');
  await next(page);
  await onStep(page, '作成');
  await mark(page, 'input-submit').click();
  await onStep(page, 'ノードをクリック');
  await expect(page.getByTestId('graph-outline').locator('[data-id="n:/dummy_hello"]')).toHaveCount(1);
  await page.waitForTimeout(1500); // the map's layout animation
  await clickElement(page, 'n:/dummy_hello');
  await onStep(page, 'トピックをクリック');
  await clickElement(page, 't:/hello');
  await onStep(page, '流れているデータ');
  await expect(page.getByTestId('echo-body')).toContainText('hello', { timeout: 15_000 });
  await next(page);
  await onStep(page, 'できました', 'docs/design/nodes.md');
  expect(await targetIds(page)).toContain('dummy_hello');
  await popover(page).getByRole('button', { name: '片づけて終わる' }).click();
  await expectCompleted(page, 'firstInput');
  await expect.poll(() => targetIds(page)).not.toContain('dummy_hello');
});

test('届かない原因を見つけて直す: red dashed edge → reason → send as RELIABLE → edge is normal → clean up', async ({ page }) => {
  await startFromSettings(page, 'qosFix');
  await onStep(page, '赤い破線');
  await expect(page.locator('[data-tour="diag-item"][data-tour-topic="/tour_qos"]')).toContainText('BEST_EFFORT');
  await shot(page, 'tour-qos-fix');
  await next(page);
  await onStep(page, '理由を探す');
  await page.locator('[data-tour="diag-item"][data-tour-topic="/tour_qos"]').click();
  await onStep(page, '理由を読む');
  await expect(page.getByTestId('detail-title')).toHaveText('/tour_qos');
  await next(page);
  await onStep(page, '送り手を選ぶ');
  await expect(page.getByTestId('graph-outline').locator('[data-id="n:/tour_qos_pub"]')).toHaveCount(1);
  await page.waitForTimeout(1500); // the map's layout animation
  await clickElement(page, 'n:/tour_qos_pub');
  await onStep(page, '編集を開く');
  await mark(page, 'node-edit').click();
  await onStep(page, 'RELIABLE で送り直す');
  await mark(page, 'input-submit').click();
  await onStep(page, '届くようになりました', 'docs/design/map-and-traffic.md');
  const graph = await (await page.request.get('/api/graph')).json();
  expect(graph.diagnostics.filter((d: { code: string; topic: string }) => d.code === 'qos_incompatible' && d.topic === '/tour_qos')).toHaveLength(0);
  expect(await targetIds(page)).toEqual(expect.arrayContaining(['tour_qos_pub', 'tour_qos_sub']));
  await expect(popover(page).getByRole('button', { name: '残して終わる' })).toHaveCount(0); // nothing worth keeping
  await popover(page).getByRole('button', { name: '片づけて終わる' }).click();
  await expectCompleted(page, 'qosFix');
  await expect.poll(() => targetIds(page)).not.toEqual(expect.arrayContaining(['tour_qos_pub']));
  await expect.poll(() => targetIds(page)).not.toEqual(expect.arrayContaining(['tour_qos_sub']));
});

test('関数ノードを作る: shout on /chatter → /shouted, the echo is upper-case → clean up', async ({ page }) => {
  await startFromSettings(page, 'functionNode');
  await onStep(page, '関数ノードを作る');
  await mark(page, 'create-function').click();
  await onStep(page, 'モジュールを選ぶ');
  await mark(page, 'function-module').selectOption('roshanavi_examples.logic');
  await onStep(page, '関数を選ぶ');
  await expect(mark(page, 'function-name').locator('option')).toContainText(['shout(text: str) -> str']);
  await mark(page, 'function-name').selectOption('shout');
  await onStep(page, '入力のトピック');
  await mark(page, 'function-input-0-topic').fill('/chatter');
  await onStep(page, '出力のトピック');
  await mark(page, 'function-output-topic').fill('/shouted');
  await shot(page, 'tour-function-node');
  await onStep(page, '作成');
  await mark(page, 'function-submit').click();
  await expect(page.getByTestId('echo-body')).toContainText('HELLO WORLD', { timeout: 30_000 });
  await onStep(page, 'できました', 'docs/design/nodes.md');
  const before = await targetIds(page);
  expect(before).toContain('shout');
  await popover(page).getByRole('button', { name: '片づけて終わる' }).click();
  await expectCompleted(page, 'functionNode');
  await expect.poll(() => targetIds(page)).not.toContain('shout');
});

test('シナリオを記録する: record → save → run → passed → clean up', async ({ page }) => {
  await startFromSettings(page, 'scenario');
  await onStep(page, '準備しています');
  await onStep(page, 'シナリオタブ');
  await mark(page, 'tab-scenarios').click();
  await onStep(page, '記録して作る');
  await mark(page, 'scn-record-open').click();
  await onStep(page, '見張るトピック');
  await mark(page, 'scn-watch-/tour_out').check();
  await onStep(page, '記録を始める');
  await mark(page, 'scn-rec-start').click();
  await onStep(page, 'お試し送信へ');
  await mark(page, 'tab-inject').click();
  await onStep(page, '送り先');
  await mark(page, 'inject-topic').fill('/tour_in');
  await expect(page.getByTestId('inject-type-detected')).toContainText(CHATTER_KIND_LABEL);
  await onStep(page, '送る内容');
  await mark(page, 'inject-yaml').fill('data: "hello scenario"');
  await onStep(page, '送る');
  await mark(page, 'inject-start').click();
  await onStep(page, 'シナリオタブに戻る');
  await mark(page, 'tab-scenarios').click();
  await onStep(page, '返ってきたデータ');
  await shot(page, 'tour-scenario');
  await page.locator('[data-tour="scn-tl-msg"][data-topic="/tour_out"]:visible').first().click();
  await onStep(page, 'これが来るはず');
  await mark(page, 'scn-expect-this').click();
  await onStep(page, '期待を追加');
  await expect(page.getByTestId('scn-pick-value-data')).toHaveValue('HELLO SCENARIO!');
  await mark(page, 'scn-pick-add').click();
  await onStep(page, '記録を止める');
  await mark(page, 'scn-rec-stop').click();
  await onStep(page, '名前をつける');
  await mark(page, 'scn-rec-name').fill('tour_scenario');
  await next(page);
  await onStep(page, '保存');
  await mark(page, 'scn-rec-save').click();
  await onStep(page, '実行');
  await page.locator('[data-tour="scn-run"][data-scn-id="project:tour_scenario.yaml"]').click();
  await expect(page.getByTestId('scn-result')).toHaveAttribute('data-status', 'passed', { timeout: 30_000 });
  await onStep(page, 'できました', 'docs/design/scenarios.md');
  await popover(page).getByRole('button', { name: '片づけて終わる' }).click();
  await expectCompleted(page, 'scenario');
  await expect.poll(() => targetIds(page)).not.toContain('tour_shout');
  const scenarios = (await (await page.request.get('/api/scenarios')).json()) as { items: { id: string }[] };
  expect(scenarios.items.map((i) => i.id)).not.toContain('project:tour_scenario.yaml');
});

test('a do-step can be skipped, and 戻る goes back', async ({ page }) => {
  await startFromSettings(page, 'firstInput');
  await onStep(page, '入力ノードを作る');
  await popover(page).getByRole('button', { name: 'この手順を飛ばす' }).click();
  await onStep(page, 'データの種類');
  await popover(page).getByRole('button', { name: '戻る' }).click();
  await onStep(page, '入力ノードを作る');
  // Pause and quit from the pill: nothing was created, nothing is left.
  await page.keyboard.press('Escape');
  await page.getByTestId('tour-quit').click();
  await expect(page.locator('[data-tour="paused"]')).toHaveCount(0);
  const stored = await page.evaluate((key) => JSON.parse(window.localStorage.getItem(key) ?? '{}'), STORAGE_KEY);
  expect(stored.run).toBeNull();
  expect(stored.completed).toEqual([]);
});

test('a target that is not on the screen: the step is centered with a note, and can be skipped', async ({ page }) => {
  await startFromSettings(page, 'firstInput');
  await onStep(page, '入力ノードを作る');
  await expect(popover(page).locator('.driver-popover-description')).not.toContainText('見つかりません');
  await page.evaluate(() => {
    (document.querySelector('[data-tour="create-input"]') as HTMLElement).style.display = 'none';
  });
  await expect(popover(page).locator('.driver-popover-description')).toContainText('いまの画面に見つかりません');
  await expect(page.locator('.driver-active-element[data-tour="create-input"]')).toHaveCount(0);
  await popover(page).getByRole('button', { name: 'この手順を飛ばす' }).click();
  await onStep(page, 'データの種類');
  await page.keyboard.press('Escape');
  await page.getByTestId('tour-quit').click();
});

test.describe('dark mode', () => {
  test.use({ colorScheme: 'dark' });
  test('the popover follows the app theme', async ({ page }) => {
    await startFromSettings(page, 'overview');
    await onStep(page, '画面の見方');
    const colors = await popover(page).evaluate((el) => {
      const style = window.getComputedStyle(el);
      return { background: style.backgroundColor, text: style.color };
    });
    expect(colors.background).toBe('rgb(17, 24, 39)'); // --surface in dark
    expect(colors.text).toBe('rgb(229, 231, 235)');
    await shot(page, 'tour-dark');
    await page.keyboard.press('Escape');
    await page.getByTestId('tour-quit').click();
  });
});
