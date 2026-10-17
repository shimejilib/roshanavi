import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Requires `docker compose up -d lab demo`. Starts nodes from the Launcher tab,
// checks their roles on the map, then stops and removes everything it created.
const SHOTS = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
const CREATED = ['e2e_talker', 'e2e_listener', 'e2e_dummy'];

async function cleanup(page: Page) {
  for (const id of CREATED) await page.request.delete(`/api/targets/${id}`);
}

async function addRun(page: Page, exe: string, name: string, mine: boolean) {
  await page.getByTestId('launcher-search').fill('demo_nodes_cpp');
  await page.getByTestId(`pick-run-demo_nodes_cpp-${exe}`).click();
  await page.getByTestId('target-form-name').fill(name);
  // Own topic, so this test never disturbs the demo's /chatter (smoke test runs in parallel).
  const remaps = page.getByTestId('target-form-remaps');
  await remaps.getByRole('button', { name: '+ 行を追加' }).click();
  await remaps.getByPlaceholder('元').fill('chatter');
  await remaps.getByPlaceholder('先').fill('/e2e_chatter');
  if (!mine) await page.getByTestId('target-form-mine').uncheck();
  await page.getByTestId('target-form-submit').click();
  await expect(page.getByTestId(`target-status-${name}`)).toHaveAttribute('data-status', /starting|running/, { timeout: 10_000 });
}

test.beforeEach(async ({ page }) => cleanup(page));
test.afterEach(async ({ page }) => cleanup(page));

test('start talker from the Launcher, see it as "mine" on the map, stop it', async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.goto('/');
  await page.getByTestId('tab-launcher').click();
  await expect(page.getByTestId('pkg-roshanavi')).toContainText('ワークスペース');

  await addRun(page, 'talker', 'e2e_talker', true);
  await expect(page.getByTestId('log-body')).toContainText('Publishing', { timeout: 15_000 });
  await expect(page.getByTestId('project-dirty')).toHaveAttribute('data-dirty', 'true');
  await addRun(page, 'listener', 'e2e_listener', false);
  await page.getByTestId('target-e2e_talker').getByRole('button', { name: 'ログ' }).click();
  await expect(page.getByTestId('target-e2e_talker')).toContainText('確実', { timeout: 15_000 });
  await page.screenshot({ path: `${SHOTS}launcher.png` });

  // A persistent dummy node made from a running inject job.
  await page.getByTestId('tab-inject').click();
  await page.getByTestId('inject-topic').fill('/e2e_cmd');
  await page.getByTestId('inject-type').fill('std_msgs/msg/String');
  await expect(page.getByTestId('inject-yaml')).toHaveValue(/data:/);
  await page.getByLabel('周期的に').check();
  await page.getByLabel('周期 (Hz)').fill('2');
  await page.getByTestId('inject-start').click();
  const job = page.getByTestId('job').filter({ hasText: '/e2e_cmd' }).filter({ hasText: '実行中' });
  await job.getByTestId('job-persist').click();
  await job.getByTestId('persist-name').fill('e2e_dummy');
  await job.getByTestId('persist-submit').click();
  await expect(page.getByTestId('dummy-e2e_dummy')).toContainText(/起動中|実行中/, { timeout: 10_000 });

  await page.getByTestId('tab-graph').click();
  const outline = page.getByTestId('graph-outline');
  await expect(outline.locator('[data-id="n:/e2e_talker"]')).toHaveAttribute('data-role', 'mine', { timeout: 20_000 });
  await expect(outline.locator('[data-id="n:/e2e_listener"]')).toHaveAttribute('data-role', 'dependency', { timeout: 20_000 });
  await expect(outline.locator('[data-id="n:/e2e_dummy"]')).toHaveAttribute('data-role', 'dummy', { timeout: 20_000 });

  await page.waitForTimeout(2500); // layout animation + particles
  await page.screenshot({ path: `${SHOTS}graph-roles.png` });

  // Right pane for the node: target, process status, mapping confidence, quick actions.
  await page.getByTestId('tab-traffic').click();
  await page.locator('tr[data-topic="/e2e_chatter"]').click();
  await page.getByRole('button', { name: '/e2e_talker', exact: true }).click();
  await expect(page.getByTestId('detail-title')).toHaveText('/e2e_talker');
  await expect(page.getByTestId('node-launcher')).toContainText('e2e_talker');
  await expect(page.getByTestId('node-launcher')).toContainText('確実');
  await page.getByTestId('tab-graph').click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}graph-node-launcher.png` });

  await page.getByTestId('node-logs').click();
  await expect(page.getByTestId('log-viewer')).toContainText('e2e_talker');
  await page.getByTestId('target-stop-e2e_talker').click();
  await expect(page.getByTestId('target-status-e2e_talker')).toHaveAttribute('data-status', 'stopped', { timeout: 15_000 });
  await page.getByTestId('tab-graph').click();
  await expect(outline.locator('[data-id="n:/e2e_talker"]')).toHaveCount(0, { timeout: 20_000 });
});
