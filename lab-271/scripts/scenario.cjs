// 字幕格式驗收（#271）：在免安裝模式的 app 用假供應商轉錄測試影片兩次（Multi-Speaker 開、關），
// 再從結果頁下載四種輸出格式，存到 <輸出資料夾>/on 與 /off。
// 用法：node scenario.cjs <埠> <影片> <輸出資料夾>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [port, video, outDir] = process.argv.slice(2);
const FORMATS = [['srt', 'SRT (Subtitles)'], ['vtt', 'VTT (WebVTT)'], ['lrc', 'LRC (Lyrics)'], ['txt', 'TXT (Plain Text)']];

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, acceptDownloads: true, locale: 'zh-TW', timezoneId: 'Asia/Taipei' });
  const page = await context.newPage();
  const shot = (name) => page.screenshot({ path: path.join(outDir, `${name}.png`) });

  const transcribe = async (multiSpeaker, done) => {
    await page.getByRole('link', { name: 'New Transcription' }).click();
    await page.getByLabel('供應商').selectOption('fake');
    await page.getByLabel('處理模式').selectOption('standard');
    const sw = page.getByRole('switch', { name: 'Multi-Speaker', exact: true });
    if ((await sw.getAttribute('aria-checked')) !== String(multiSpeaker)) await sw.click();
    await page.locator('input[type=file]:not([accept=".txt,.srt,.vtt,.lrc"])').first().setInputFiles([video]);
    await page.getByRole('button', { name: 'Start' }).click();
    await page.getByText(new RegExp(`✓ ${done} 完成`)).waitFor({ timeout: 120000 });
  };

  await page.goto(`http://127.0.0.1:${port}/transcribe`);
  await transcribe(true, 1);
  await shot('1-transcribe-on');
  await transcribe(false, 2);
  await shot('2-transcribe-off');

  await page.getByRole('link', { name: 'Result Viewer' }).click();
  await page.getByText('2 completed').waitFor();
  await shot('3-result');
  // 結果頁的檔案卡依完成順序排列：第一張是 Multi-Speaker 開，第二張是關
  for (const [index, label] of [[0, 'on'], [1, 'off']]) {
    fs.mkdirSync(path.join(outDir, label), { recursive: true });
    for (const [fmt, item] of FORMATS) {
      await page.getByRole('button', { name: 'Download', exact: true }).nth(index).hover();
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.locator('.ant-dropdown:visible').getByText(item, { exact: true }).click(),
      ]);
      const target = path.join(outDir, label, download.suggestedFilename());
      await download.saveAs(target);
      console.log(label, fmt, download.suggestedFilename(), fs.statSync(target).size, 'bytes');
      await page.mouse.move(1270, 850);
      await page.waitForTimeout(600);
    }
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
