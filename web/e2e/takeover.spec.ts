import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

// Launch takeover (docs/design/integration.md): a package's launch file is taken over, its
// nodes become targets; editing the launch file shows 「launch ファイルが変更されました」 and the
// re-import adds the new node. Node list: delete with confirmation, then 「元に戻す」.
// lab-e2e's /ws/src is a tmpfs shared with this runner at E2E_WS_SRC (scripts/e2e.sh); the
// build button uses --symlink-install, so the installed launch file is the edited one.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const SRC = process.env.E2E_WS_SRC ?? '/e2e-ws-src';
const PKG = 'e2e_takeover';
const DUMMY = 'e2e-del';

const LAUNCH = (extra: string) => `from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package='demo_nodes_cpp', executable='talker', name='e2e_tk_talker',
             remappings=[('chatter', '/e2e_tk_chatter')]),
${extra}    ])
`;
const LISTENER = `        Node(package='demo_nodes_cpp', executable='listener', name='e2e_tk_listener',
             remappings=[('chatter', '/e2e_tk_chatter')]),
`;

function writePackage() {
  const root = join(SRC, PKG);
  mkdirSync(join(root, 'launch'), { recursive: true });
  mkdirSync(join(root, 'resource'), { recursive: true });
  mkdirSync(join(root, PKG), { recursive: true });
  writeFileSync(join(root, 'package.xml'), `<?xml version="1.0"?><package format="3"><name>${PKG}</name>`
    + '<version>0.0.0</version><description>x</description><maintainer email="a@b.c">a</maintainer>'
    + '<license>MIT</license><export><build_type>ament_python</build_type></export></package>\n');
  writeFileSync(join(root, 'resource', PKG), '');
  writeFileSync(join(root, PKG, '__init__.py'), '');
  writeFileSync(join(root, 'setup.cfg'), `[develop]\nscript_dir=$base/lib/${PKG}\n[install]\ninstall_scripts=$base/lib/${PKG}\n`);
  writeFileSync(join(root, 'setup.py'), `from glob import glob\nfrom setuptools import setup\n\nsetup(name='${PKG}', version='0.0.0', packages=['${PKG}'],\n`
    + `      data_files=[('share/ament_index/resource_index/packages', ['resource/${PKG}']),\n`
    + `                  ('share/${PKG}', ['package.xml']), ('share/${PKG}/launch', glob('launch/*.launch.py'))])\n`);
  writeFileSync(join(root, 'launch', 'pair.launch.py'), LAUNCH(''));
}

async function build(request: APIRequestContext) {
  // The new package must be found first (the workspace scan is cached).
  expect((await request.post('/api/workspace/refresh')).ok()).toBeTruthy();
  const started = await request.post('/api/build', { data: { package: PKG, restart_running: false } });
  expect(started.ok(), await started.text()).toBeTruthy();
  await expect.poll(async () => ((await (await request.get('/api/build')).json()) as { state: string }).state,
    { timeout: 120_000 }).toBe('succeeded');
}

async function takeoverTargets(request: APIRequestContext): Promise<string[]> {
  const body = (await (await request.get('/api/takeover')).json()) as { targets: string[] };
  return body.targets;
}

async function openNodes(page: Page) {
  await page.goto('/');
  await page.getByTestId('tab-nodes').click();
  await expect(page.getByTestId('node-table')).toBeVisible();
}

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterAll(async ({ request }) => {
  for (const id of [...(await takeoverTargets(request)), DUMMY]) await request.delete(`/api/targets/${id}`);
});

test('the launch file changes -> banner -> diff -> re-import adds the node', async ({ page, request }) => {
  test.setTimeout(240_000);
  writePackage();
  await build(request);
  const start = await request.post('/api/takeover/start', { data: { package: PKG, launch_file: 'pair.launch.py', mode: 'node' } });
  expect(start.status(), await start.text()).toBe(202);
  await expect.poll(async () => ((await (await request.get('/api/takeover')).json()) as { state: string }).state,
    { timeout: 60_000 }).toBe('ready');
  await openNodes(page);
  await expect(page.getByTestId('node-row-/e2e_tk_talker')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('takeover-changed-banner')).toHaveCount(0);

  // Edit the launch file as an editor would (the install copy is a symlink to it).
  const file = join(SRC, PKG, 'launch', 'pair.launch.py');
  writeFileSync(file, readFileSync(file, 'utf-8').replace(LAUNCH(''), LAUNCH(LISTENER)));
  const banner = page.getByTestId('takeover-changed-banner');
  await expect(banner).toContainText('launch ファイルが変更されました。取り込み直しますか?', { timeout: 30_000 });
  await page.screenshot({ path: `${SHOTS}takeover-changed-banner.png` });
  await page.getByTestId('takeover-show-diff').click();
  const dialog = page.getByTestId('takeover-diff-dialog');
  await expect(dialog.getByTestId('takeover-added')).toContainText('/e2e_tk_listener');
  await expect(dialog).toContainText('pair.launch.py');
  await page.screenshot({ path: `${SHOTS}takeover-diff.png` });
  await dialog.getByTestId('takeover-apply').click();
  await expect(page.getByTestId('takeover-applied')).toContainText('追加 1');
  await expect(banner).toHaveCount(0);
  await expect(page.getByTestId('node-row-/e2e_tk_listener')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('node-row-/e2e_tk_talker')).toBeVisible();
});

test('delete with confirmation, then undo restores and restarts it', async ({ page, request }) => {
  const created = await request.post('/api/dummies?start=true', {
    data: { id: DUMMY, name: 'e2e_del_dummy', topic: '/e2e_del', type: 'std_msgs/msg/String', mode: 'periodic', payload: { data: 'x' }, rate_hz: 2 },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  await openNodes(page);
  const row = page.getByTestId('node-row-/e2e_del_dummy');
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('node-check-/external_talker')).toBeDisabled();
  await page.getByTestId('node-check-/e2e_del_dummy').check();
  await page.getByTestId('nodes-bulk-delete').click();
  const confirm = page.getByTestId('confirm-dialog');
  await expect(confirm).toContainText(DUMMY);
  await expect(confirm).toContainText('削除すると止まります');
  await expect(confirm).toContainText('ソースコード・パッケージ・パラメータファイル・録画は消えません');
  await page.screenshot({ path: `${SHOTS}node-list-delete.png` });
  await page.getByTestId('confirm-ok').click();
  await expect(page.getByTestId('nodes-delete-message')).toContainText('1 件を削除しました');
  await expect.poll(async () => (await request.get(`/api/targets/${DUMMY}`)).status()).toBe(404);
  await expect(row).toHaveCount(0, { timeout: 20_000 });
  await page.getByTestId('nodes-undo-delete').click();
  await expect(page.getByTestId('nodes-delete-message')).toContainText('元に戻しました (1 件)');
  await expect.poll(async () => ((await (await request.get(`/api/targets/${DUMMY}`)).json()) as { status: string }).status,
    { timeout: 20_000 }).toMatch(/running|starting/);
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('nodes-undo-delete')).toHaveCount(0);
});
