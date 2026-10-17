import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Run via scripts/e2e.sh (isolated lab-e2e + demo-e2e). Chromium runs with a fake mic / camera.
const SHOTS = fileURLToPath(new URL('../../docs/images/', import.meta.url));
// Under scripts/e2e.sh this is a volume shared with lab-e2e (mounted at its /data/e2e).
const DATA = process.env.E2E_MEDIA_DIR ? `${process.env.E2E_MEDIA_DIR}/` : fileURLToPath(new URL('../../data/e2e/', import.meta.url));

/** A short VP8 clip recorded in the browser (MediaRecorder on an animated canvas). */
async function makeClip(page: Page): Promise<Buffer> {
  const base64 = await page.evaluate(async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 320;
    canvas.height = 240;
    const ctx = canvas.getContext('2d')!;
    const recorder = new MediaRecorder(canvas.captureStream(10), { mimeType: 'video/webm;codecs=vp8' });
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    const done = new Promise((resolve) => (recorder.onstop = resolve));
    recorder.start();
    for (let i = 0; i < 20; i += 1) {
      ctx.fillStyle = `hsl(${i * 18}, 80%, 50%)`;
      ctx.fillRect(0, 0, 320, 240);
      ctx.fillStyle = '#fff';
      ctx.font = '48px sans-serif';
      ctx.fillText(`frame ${i}`, 40, 130);
      await new Promise((r) => setTimeout(r, 100));
    }
    recorder.stop();
    await done;
    const bytes = new Uint8Array(await new Blob(chunks).arrayBuffer());
    let text = '';
    for (const b of bytes) text += String.fromCharCode(b);
    return btoa(text);
  });
  return Buffer.from(base64, 'base64');
}

async function openTopic(page: Page, topic: string) {
  await page.getByTestId('tab-traffic').click();
  const row = page.locator(`tr[data-topic="${topic}"]`);
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.click();
  await expect(page.getByTestId('detail-title')).toHaveText(topic);
}

test('browser microphone -> topic, visible on the map and as a waveform', async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.goto('/');
  await page.getByTestId('tab-inject').click();
  const panel = page.getByTestId('capture-panel');
  await panel.getByTestId('capture-topic').fill('/e2e_mic');
  await panel.getByTestId('capture-type').selectOption('std_msgs/msg/Int16MultiArray');
  await panel.getByTestId('capture-start').click();
  await expect(panel.getByTestId('capture-status')).toContainText(/送信中: [1-9]/, { timeout: 15_000 });
  await expect(panel.getByTestId('capture-level')).toBeVisible();
  await panel.screenshot({ path: `${SHOTS}capture-panel.png` });

  await page.getByTestId('tab-graph').click();
  await expect(page.getByTestId('graph-outline').locator('li[data-id^="e:pub:dummy:"][data-id$=":/e2e_mic"]')).toHaveCount(1, { timeout: 15_000 });

  await openTopic(page, '/e2e_mic');
  const wave = page.getByTestId('audio-waveform');
  await expect(wave).toHaveAttribute('data-received', '16000', { timeout: 10_000 });
  await page.waitForTimeout(800);
  await page.locator('.detail-pane').screenshot({ path: `${SHOTS}audio-waveform.png` });

  await page.getByTestId('tab-inject').click();
  await panel.getByTestId('capture-stop').click();
  await expect(panel.getByTestId('capture-start')).toBeVisible();
});

test('video file -> sensor_msgs/Image, shown in the image viewer', async ({ page }) => {
  await page.goto('/');
  mkdirSync(DATA, { recursive: true });
  writeFileSync(`${DATA}clip.webm`, await makeClip(page));

  await page.getByTestId('tab-inject').click();
  await page.getByTestId('inject-topic').fill('/e2e_cam/image_raw');
  await page.getByLabel('メディアファイル (画像・動画・音声)').check();
  await page.getByTestId('inject-type-kind').selectOption('image');
  await page.getByTestId('media-source').selectOption('e2e/clip.webm');
  await page.getByTestId('media-rate').fill('10');
  await page.getByLabel('最後まで送ったら繰り返す').check();
  await page.getByLabel('幅').fill('320');
  await page.screenshot({ path: `${SHOTS}inject-media.png` });
  await page.getByTestId('inject-start').click();
  await expect(page.getByRole('status')).toContainText('開始しました');

  await openTopic(page, '/e2e_cam/image_raw');
  const img = page.getByTestId('image-viewer');
  await expect(img).toBeVisible({ timeout: 15_000 });
  await expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBe(320);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${SHOTS}image-viewer.png` });

  await page.getByTestId('tab-inject').click();
  const running = page.getByTestId('job').filter({ hasText: '/e2e_cam/image_raw' }).filter({ hasText: '実行中' });
  await running.getByRole('button', { name: '停止' }).click();
  await expect(running).toHaveCount(0, { timeout: 5_000 });
});

test('inject file list refreshes on focus and with the reload button (#3)', async ({ page }) => {
  await page.goto('/');
  mkdirSync(DATA, { recursive: true });
  await page.getByTestId('tab-inject').click();
  await page.getByLabel('ファイルから順に (JSONL / CSV)').check();
  const stamp = Date.now();
  // A file that appears after the list was first loaded shows up when the user comes back to the page...
  writeFileSync(`${DATA}late-a-${stamp}.jsonl`, '{"data":"a"}\n');
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page.locator('option', { hasText: `e2e/late-a-${stamp}.jsonl` })).toHaveCount(1, { timeout: 10_000 });
  // ...or when they press the reload button.
  writeFileSync(`${DATA}late-b-${stamp}.jsonl`, '{"data":"b"}\n');
  await page.getByTestId('inject-files-reload').click();
  await expect(page.locator('option', { hasText: `e2e/late-b-${stamp}.jsonl` })).toHaveCount(1, { timeout: 10_000 });
});

test('record /chatter, see it in the list, delete it', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('tab-recordings').click();
  await page.getByTestId('rec-topic-/chatter').check();
  await page.getByTestId('rec-name').fill('e2e');
  await page.getByTestId('rec-start').click();
  await expect(page.getByTestId('rec-active')).toContainText('録画中', { timeout: 10_000 });
  await page.waitForTimeout(5000);
  await page.getByTestId('rec-stop').click();
  const row = page.locator('[data-testid^="recording-"]').filter({ hasText: '_e2e' }).first();
  await expect(row).toContainText('/chatter', { timeout: 15_000 });
  await expect(page.getByTestId('rec-start')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}recordings.png` });
  const name = (await row.locator('td').first().textContent()) ?? '';
  await row.getByRole('button', { name: '削除' }).click();
  await expect(page.getByTestId('confirm-dialog')).toContainText(name);
  await page.getByTestId('confirm-ok').click();
  await expect(page.getByTestId(`recording-${name}`)).toHaveCount(0, { timeout: 10_000 });
});
