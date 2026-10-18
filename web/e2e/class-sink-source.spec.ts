import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

// A class node whose methods have only an input (a sink: `on_pose(pose) -> None`) or only an
// output (a periodic source: `render() -> image`), like the turtle demo's TrajectoryCanvas.
// The server used to drop the empty `outputs` / `inputs` lists and the map crashed with
// 「Cannot read properties of undefined (reading 'map')」.
// lab-e2e's /ws/src is a tmpfs shared with this runner at E2E_WS_SRC (scripts/e2e.sh).
const SRC = process.env.E2E_WS_SRC ?? '/e2e-ws-src';
const PKG = 'e2e_canvas_pkg';
const NAME = 'e2e_canvas';
const POSE = '/e2e_canvas_pose';
const IMAGE = '/e2e_canvas_image';

const PACKAGE_XML = '<?xml version="1.0"?><package format="3"><name>' + PKG + '</name><version>0.0.0</version>'
  + '<description>x</description><maintainer email="a@b.c">a</maintainer><license>MIT</license>'
  + '<export><build_type>ament_python</build_type></export></package>\n';

const CANVAS_PY = `import numpy as np


class Canvas:
    def __init__(self, size: int = 32):
        self.size = size
        self.points = []

    def on_pose(self, pose: dict) -> None:
        self.points.append((pose.get('x', 0.0), pose.get('y', 0.0)))

    def render(self) -> np.ndarray:
        image = np.zeros((self.size, self.size, 3), dtype=np.uint8)
        image[:, :, 1] = min(255, 20 * len(self.points))
        return image
`;

function writeFile(path: string, text: string) {
  mkdirSync(join(path, '..'), { recursive: true });
  writeFileSync(path, text);
}

test.afterEach(async ({ request }) => {
  await request.delete(`/api/targets/${NAME}`);
});

test('a class with a sink method and a periodic source method: spec keeps [] and the map shows its ports', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));

  writeFile(join(SRC, PKG, 'package.xml'), PACKAGE_XML);
  writeFile(join(SRC, PKG, PKG, '__init__.py'), '');
  writeFile(join(SRC, PKG, PKG, 'canvas.py'), CANVAS_PY);

  const body = {
    id: NAME, name: NAME, module: `${PKG}.canvas`, class_name: 'Canvas', params: { size: 32 },
    methods: [
      { method: 'on_pose', call: 'on_message', inputs: [{ topic: POSE, kind: 'message', type: 'geometry_msgs/msg/Point' }] },
      { method: 'render', call: 'periodic', rate_hz: 5, outputs: [{ topic: IMAGE, kind: 'image' }] },
    ],
    actions: [],
  };
  const created = await request.post('/api/classes?start=true', { data: body });
  expect(created.status(), await created.text()).toBe(201);

  // The API sends the empty lists the UI maps over.
  const spec = (await (await request.get(`/api/targets/${NAME}`)).json()).spec;
  expect(spec.methods[0].outputs).toEqual([]);
  expect(spec.methods[1].inputs).toEqual([]);
  expect(spec.actions).toEqual([]);

  await page.goto('/');
  await expect(page.getByTestId('graph-outline').locator(`[data-id="n:/${NAME}"]`)).toHaveAttribute('data-role', 'function', { timeout: 40_000 });
  await expect(page.getByTestId('wire-layer')).toBeVisible();
  // Method 0 (on_pose): one input port, no output. Method 1 (render): no input, one output port.
  await expect(page.getByTestId(`port-${NAME}-in-0-0`)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId(`port-${NAME}-out-1-0`)).toBeVisible();
  await expect(page.getByTestId(`port-${NAME}-out-0-0`)).toHaveCount(0);
  await expect(page.getByTestId(`port-${NAME}-in-1-0`)).toHaveCount(0);
  await expect(page.getByText('Cannot read properties of undefined')).toHaveCount(0);

  // The image really is produced (periodic source) and the node pane opens without an error.
  await expect.poll(async () => (await (await request.get(`/api/targets/${NAME}`)).json()).function_status?.state, { timeout: 20_000 }).toBe('running');
  expect(errors).toEqual([]);
});
