import { expect, test } from '@playwright/test';
import { fileURLToPath } from 'node:url';

// F-02: ~200 map elements with flowing particles must stay smooth.
// /ws/live is replaced by a synthetic graph (no ROS needed beyond serving the UI).
const SHOTS = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
const PIPELINES = 20; // each: src -> /in_i -> proc_i -> /out_i -> sink_i  (5 vertices + 4 edges)
const QOS = { reliability: 'reliable', durability: 'volatile', depth: 10 };

function syntheticFrame(withGraph: boolean): string {
  const nodes: unknown[] = [];
  const topics: unknown[] = [];
  const edges: unknown[] = [];
  const traffic: unknown[] = [];
  const now = Date.now() / 1000;
  for (let i = 0; i < PIPELINES; i += 1) {
    for (const n of [`/src_${i}`, `/proc_${i}`, `/sink_${i}`]) nodes.push({ id: n, name: n.slice(1), namespace: '/', role: 'other' });
    for (const tp of [`/in_${i}`, `/out_${i}`]) {
      topics.push({ name: tp, types: ['std_msgs/msg/String'] });
      const hz = 1 + (i % 10) * 10;
      traffic.push({
        topic: tp, type: 'std_msgs/msg/String', status: 'ok', monitored: true, collapsed: false,
        hz, hz_basis: 'source', hz_recv: hz, hz_source: hz, bytes_per_sec: hz * 1000, avg_size: 1000,
        jitter_ms: 1, jitter_recv_ms: 1, dropped: 0, drop_ratio: 0, latency_ms: 1, last_seen: now,
        total_count: 100, recent_count: hz, history: [hz],
      });
    }
    edges.push({ node: `/src_${i}`, topic: `/in_${i}`, dir: 'pub', qos: QOS });
    edges.push({ node: `/proc_${i}`, topic: `/in_${i}`, dir: 'sub', qos: QOS });
    edges.push({ node: `/proc_${i}`, topic: `/out_${i}`, dir: 'pub', qos: QOS });
    edges.push({ node: `/sink_${i}`, topic: `/out_${i}`, dir: 'sub', qos: QOS });
  }
  const graph = withGraph ? { graph: { nodes, topics, edges, diagnostics: [], hash: 'synthetic' } } : {};
  return JSON.stringify({ traffic, jobs: [], ...graph });
}

test('200 elements with particles keep a smooth frame rate', async ({ page }) => {
  await page.routeWebSocket(/\/ws\/live$/, (ws) => {
    ws.send(syntheticFrame(true));
    const timer = setInterval(() => ws.send(syntheticFrame(false)), 1000);
    ws.onClose(() => clearInterval(timer));
  });
  await page.goto('/');
  await expect(page.getByTestId('graph-outline').locator('li')).toHaveCount(PIPELINES * 9, { timeout: 10_000 });
  await page.waitForTimeout(1500);
  const fps = await page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        let frames = 0;
        const start = performance.now();
        const loop = (now: number) => {
          frames += 1;
          if (now - start < 3000) requestAnimationFrame(loop);
          else resolve((frames * 1000) / (now - start));
        };
        requestAnimationFrame(loop);
      }),
  );
  test.info().annotations.push({ type: 'fps', description: fps.toFixed(1) });
  await page.screenshot({ path: `${SHOTS}graph-200-elements.png` });
  expect(fps).toBeGreaterThan(30);
});
