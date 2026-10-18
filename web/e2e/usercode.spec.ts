import { expect, test } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { clickElement } from './helpers';

// Where function / class node code comes from (docs/design/user-code.md): the 「コードの場所」 panel
// explains a folder that is not found, 「ひな形を作る」 makes a package that runs right away, and
// editing its logic.py (here: the test writes the file, like an editor would) changes the output.
// lab-e2e's /ws/src is a tmpfs shared with this runner at E2E_WS_SRC (scripts/e2e.sh).
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const SRC = process.env.E2E_WS_SRC ?? '/e2e-ws-src';
const LAB_SRC = '/ws/src';
const PKG = 'e2e_logic';
const FN = 'e2e_logic_fn';
const CV = 'e2e_cv_fn';

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));
test.afterAll(async ({ request }) => {
  for (const id of [FN.replace(/_/g, '-'), CV.replace(/_/g, '-'), FN, CV]) await request.delete(`/api/targets/${id}`);
});

function writeFile(path: string, text: string) {
  mkdirSync(join(path, '..'), { recursive: true });
  writeFileSync(path, text);
}

test('not-found reason, scaffold, edit the logic -> the output changes; missing library hint', async ({ page }) => {
  // A ROS package whose Python folder has no __init__.py: not a candidate, and the panel says why.
  writeFile(join(SRC, 'e2e_noinit_pkg', 'package.xml'),
    '<?xml version="1.0"?><package format="3"><name>e2e_noinit_pkg</name><version>0.0.0</version>'
    + '<description>x</description><maintainer email="a@b.c">a</maintainer><license>MIT</license>'
    + '<export><build_type>ament_python</build_type></export></package>\n');
  writeFile(join(SRC, 'e2e_noinit_pkg', 'e2e_noinit_pkg', 'logic.py'), 'def f(text: str) -> str:\n    return text\n');

  await page.goto('/');
  await expect(page.getByTestId('graph-outline').locator('[data-id="t:/chatter"]')).toHaveCount(1, { timeout: 20_000 });
  await page.getByTestId('create-function').click();
  const dialog = page.getByTestId('create-function-dialog');
  const panel = dialog.getByTestId('code-locations');
  await expect(panel.getByTestId('code-summary')).toContainText('ワークスペース', { timeout: 10_000 });
  if (!(await panel.evaluate((el) => (el as HTMLDetailsElement).open))) await panel.locator('summary').click();
  const noInit = panel.locator('[data-testid="code-problem"][data-code="no_init"]');
  await expect(noInit).toContainText(`${LAB_SRC}/e2e_noinit_pkg/e2e_noinit_pkg`);
  await expect(noInit).toContainText('__init__.py');
  await expect(panel.getByTestId('code-place-here')).toContainText(`${LAB_SRC}/<パッケージ名>/<パッケージ名>/logic.py`);
  await expect(panel.getByTestId('code-python')).toContainText('python3');
  await page.setViewportSize({ width: 1440, height: 1500 });
  await page.screenshot({ path: `${SHOTS}user-code-locations.png` });

  // 「ひな形を作る」: the dialog switches to the generated function.
  await panel.getByTestId('scaffold-name').fill('Bad-Name');
  await panel.getByTestId('scaffold-submit').click();
  await expect(panel.getByTestId('scaffold-result')).toContainText('小文字');
  await panel.getByTestId('scaffold-name').fill(PKG);
  await panel.getByTestId('scaffold-submit').click();
  await expect(panel.getByTestId('scaffold-result')).toContainText(`${LAB_SRC}/${PKG}`, { timeout: 10_000 });
  await expect(dialog.getByTestId('function-module')).toHaveValue(`${PKG}.logic`);
  await expect(dialog.getByTestId('function-name')).toHaveValue('convert', { timeout: 10_000 });
  await expect(dialog.getByTestId('function-signature')).toContainText('convert(text: str) -> str');
  await page.screenshot({ path: `${SHOTS}user-code-scaffold.png` });
  await page.setViewportSize({ width: 1440, height: 900 });

  await dialog.getByTestId('function-node-name').fill(FN);
  await dialog.getByTestId('function-input-0-topic').fill('/chatter');
  await dialog.getByTestId('function-output-topic').fill('/e2e_logic_out');
  await dialog.getByTestId('function-submit').click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId('detail-title')).toHaveText('/e2e_logic_out');
  await expect(page.getByTestId('echo-body')).toContainText('HELLO WORLD', { timeout: 30_000 });

  // Edit logic.py as an editor would: the running node reloads it, no restart, no build.
  const logic = join(SRC, PKG, PKG, 'logic.py');
  const source = readFileSync(logic, 'utf-8');
  expect(source).toContain('return text.upper()');
  writeFileSync(logic, source.replace('return text.upper()', "return 'edited: ' + text"));
  await expect(page.getByTestId('echo-body')).toContainText('edited: Hello World', { timeout: 20_000 });

  // A function that needs a library this Python does not have (OpenCV): the node pane says which
  // one and how to add it (① package.xml + rosdep, ② venv). roshanavi never runs pip.
  writeFile(join(SRC, PKG, PKG, 'vision.py'), 'import cv2\n\n\ndef edges(text: str) -> str:\n    return text\n');
  const body = {
    id: CV, name: CV, module: `${PKG}.vision`, function: 'edges',
    inputs: [{ topic: '/chatter', kind: 'string' }], output: { topic: '/e2e_cv_out', kind: 'string' },
  };
  expect((await page.request.post('/api/functions?start=true', { data: body })).status()).toBe(201);
  await expect(page.getByTestId('graph-outline').locator(`[data-id="n:/${CV}"]`)).toHaveAttribute('data-role', 'function', { timeout: 30_000 });
  await expect.poll(async () => (await (await page.request.get(`/api/targets/${CV}`)).json()).function_status?.state, { timeout: 20_000 }).toBe('import_error');
  await page.waitForTimeout(1500); // layout animation
  await clickElement(page, `n:/${CV}`);
  const dep = page.getByTestId('dep-panel');
  await expect(dep.getByTestId('dep-missing')).toContainText('cv2', { timeout: 15_000 });
  await expect(dep.getByTestId('dep-python')).toContainText('python3');
  await expect(dep.getByTestId('dep-route-venv')).toContainText('--system-site-packages');
  await expect(dep.getByTestId('dep-route-rosdep')).toContainText(/python3-opencv|rosdep/);
  // The node pane's status: the error, which Python runs the node, and the two routes.
  await expect(dep.getByTestId('dep-after')).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 2200 });   // the whole status panel fits
  await page.getByTestId('function-status').screenshot({ path: `${SHOTS}user-code-dependency.png` });
  await page.setViewportSize({ width: 1440, height: 900 });
});
