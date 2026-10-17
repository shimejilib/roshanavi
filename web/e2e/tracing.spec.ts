import { expect, test } from '@playwright/test';
import { fileURLToPath } from 'node:url';

// 詳細計測モード on the isolated lab-e2e: the demo talker / listener are C++ nodes the lab starts
// itself (after its init capture began), so the listener's receive side becomes 実測(トレース).
const SHOTS = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));

test('enable 詳細計測モード: the listener row is measured by the trace', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open');
  await page.getByTestId('tab-traffic').click();
  await expect(page.locator('tr[data-topic="/chatter"]')).toBeVisible({ timeout: 15_000 });
  try {
    const toggle = page.getByTestId('tracing-toggle').locator('input');
    await expect(toggle).toBeEnabled({ timeout: 10_000 });
    await toggle.click();
    const dialog = page.getByTestId('tracing-dialog');
    await expect(dialog).toContainText('計測されるノードの負荷');
    await expect(dialog).toContainText('roshanavi 側の負荷');
    await page.getByTestId('tracing-enable').click();
    await expect(dialog).toBeHidden({ timeout: 20_000 });
    await expect(page.getByTestId('tracing-status')).toContainText('詳細計測中', { timeout: 10_000 });

    await page.getByTestId('expand-/chatter').click();
    const listener = page.getByTestId('endpoint-/chatter-sub-/listener');
    await expect(listener).toContainText('実測(トレース)', { timeout: 20_000 });
    await expect(page.getByTestId('trace-/chatter-/listener')).toContainText('処理', { timeout: 10_000 });
    await expect(page.getByTestId('tracing-status')).toContainText('roshanavi の CPU');
    // >= 6 s of tracing: the traced rates equal the probe's 1.00 Hz (no 1.12 Hz start-up inflation)
    await expect(page.getByTestId('tracing-status')).toContainText(/詳細計測中 \((?:[6-9]|\d{2,}) 秒\)/, { timeout: 20_000 });
    await expect(page.getByTestId('trace-/chatter-/listener')).toContainText(/受信 1\.0\d Hz/, { timeout: 20_000 });
    await expect(page.getByTestId('trace-/chatter-/listener')).toContainText(/処理 1\.0\d Hz/);
    await page.screenshot({ path: `${SHOTS}traffic-tracing.png` });

    await page.getByTestId('traffic-view-node').click();
    await expect(page.getByTestId('node-traffic-/listener-sub-/chatter')).toContainText('実測(トレース)');
    await page.getByTestId('traffic-view-topic').click();

    await toggle.click(); // turning it off needs no confirmation
    await expect(page.getByTestId('tracing-status')).toBeHidden({ timeout: 20_000 });
    await expect(listener).toContainText('理論値', { timeout: 10_000 });
  } finally {
    await page.request.put('/api/tracing', { data: { enabled: false } });
  }
});
