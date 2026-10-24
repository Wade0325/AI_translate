import { readFile } from 'node:fs/promises'
import { test as base, expect } from '@playwright/test'
import { mockBackend } from './backend.js'

/**
 * 瀏覽器測試共用的 test：多一個 mockBackend(options) 換上假後端（見 ./backend.js）。
 *
 * 每個測試結束時檢查兩件事，任一項不成立就算失敗：
 *   - 畫面沒有打假後端沒設定的端點：新端點要在 backend.js 或測試裡給回應，不會默默拿到 404
 *   - 頁面沒有丟出未處理的例外
 */
export const test = base.extend({
    mockBackend: async ({ page }, use) => {
        const backends = []
        const pageErrors = []
        page.on('pageerror', (error) => pageErrors.push(error.message))

        await use(async (options) => {
            const backend = await mockBackend(page, options)
            backends.push(backend)
            return backend
        })

        for (const backend of backends) {
            expect(backend.unhandled, '畫面打了假後端沒有設定回應的端點').toEqual([])
        }
        expect(pageErrors, '頁面丟出未處理的例外').toEqual([])
    },
})

export { expect }

/** 下載下來的檔案內容（UTF-8 文字）。 */
export async function downloadedText(download) {
    return readFile(await download.path(), 'utf8')
}
