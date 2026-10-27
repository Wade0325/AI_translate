import { defineConfig, devices } from '@playwright/test'

/**
 * 瀏覽器測試（#51）：用 Playwright 的 Chromium 開 Vite dev server，跑主要頁面。
 *
 * 後端整個不啟動：/api 的請求與 WebSocket 都由 e2e/support/backend.js 在瀏覽器裡 mock，
 * 對外的連線一律擋掉、算測試失敗，所以不需要網路、資料庫或任何供應商。
 *
 * 執行：npx playwright install chromium（第一次）之後 npm run test:browser；
 * 或從 repo 根目錄 python tools/check.py playwright。
 */

// 固定一個少用的埠；被占用時直接失敗，不會接到別的 dev server
const PORT = 5179

export default defineConfig({
    testDir: './e2e',
    // CI 上禁止留下 test.only
    forbidOnly: !!process.env.CI,
    // 不重試：mock 的後端沒有不穩定的來源，失敗就是真的失敗
    retries: 0,
    reporter: 'list',
    use: {
        baseURL: `http://127.0.0.1:${PORT}`,
        // 日期與時間的顯示依時區而定：和 vitest 一樣固定用台北時間
        timezoneId: 'Asia/Taipei',
        locale: 'zh-TW',
        trace: 'retain-on-failure',
    },
    projects: [
        { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    ],
    webServer: {
        // 只綁本機：vite.config.js 的 server.host 會開放給區域網路，測試不需要
        command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${PORT} --strictPort`,
        url: `http://127.0.0.1:${PORT}`,
        reuseExistingServer: false,
        timeout: 60_000,
        // /api 的 proxy 不指向後端預設的 8000：萬一有請求沒被 mock 攔到，也接不到開發者本機
        // 正在跑的後端（和它的資料庫），只會連線失敗
        env: { VITE_PROXY_TARGET: 'http://127.0.0.1:9' },
    },
})
