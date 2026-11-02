// Chromium 的 <track>：每種變體、Multi-Speaker 開關的 VTT 在每個時間點的畫面，並記下解析出的字幕。
// 用法：node chromium_shots.cjs <工作資料夾> <http 埠>（工作資料夾要先用 http 伺服器在那個埠提供）
// 輸出：<工作資料夾>/chromium/<變體>-<on|off>-vtt/NN.png 與 cues.json
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [root, port] = process.argv.slice(2);
const TIMES = JSON.parse(fs.readFileSync(path.join(root, 'times.json'), 'utf8'));

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 640, height: 360 } });
  console.log('Chromium', browser.version());
  for (const variant of ['utf8-lf', 'utf8bom-lf', 'utf8-crlf', 'utf8bom-crlf']) {
    for (const ms of ['on', 'off']) {
      const out = path.join(root, 'chromium', `${variant}-${ms}-vtt`);
      fs.mkdirSync(out, { recursive: true });
      const src = `/variants/${variant}/${ms}/subtitle-test.vtt`;
      await page.goto(`http://127.0.0.1:${port}/blank.html`);
      await page.setContent(`<!doctype html><style>body{margin:0;background:#000}video{width:640px;height:360px;display:block}</style>
        <video id="v" src="http://127.0.0.1:${port}/subtitle-test.webm" preload="auto" muted>
        <track id="t" kind="subtitles" srclang="zh" label="t" src="http://127.0.0.1:${port}${src}" default></video>`);
      await page.evaluate(() => new Promise((resolve) => {
        const v = document.getElementById('v');
        const t = document.getElementById('t');
        t.track.mode = 'showing';
        let n = 0;
        const done = () => { n += 1; if (n === 2) resolve(); };
        if (v.readyState >= 1) done(); else v.addEventListener('loadedmetadata', done, { once: true });
        if (t.readyState === 2 || t.readyState === 3) done(); else { t.addEventListener('load', done, { once: true }); t.addEventListener('error', done, { once: true }); }
      }));
      const cues = await page.evaluate(() => {
        const t = document.getElementById('t');
        return { readyState: t.readyState, cues: Array.from(t.track.cues || []).map((c) => [c.startTime, c.endTime, c.text]) };
      });
      fs.writeFileSync(path.join(out, 'cues.json'), JSON.stringify(cues, null, 1));
      for (let i = 0; i < TIMES.length; i += 1) {
        await page.evaluate((s) => new Promise((resolve) => {
          const v = document.getElementById('v');
          v.addEventListener('seeked', () => requestAnimationFrame(() => requestAnimationFrame(resolve)), { once: true });
          v.currentTime = s;
        }), TIMES[i][0]);
        await page.waitForTimeout(150);
        await page.screenshot({ path: path.join(out, `${String(i).padStart(2, '0')}.png`) });
      }
      console.log('done', variant, ms, 'cues', cues.cues.length, 'readyState', cues.readyState);
    }
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
