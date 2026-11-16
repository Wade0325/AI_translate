import { readFile } from 'node:fs/promises'
import { test as base, expect } from '@playwright/test'
import { mockBackend } from './backend.js'

/**
 * antd 的彈出元件（Popconfirm 與 Popover、Dropdown 的選單、Select 的下拉清單、Modal、Tooltip）打開與收起時有一段縮放的
 * 動畫（rc-motion 的 appear、enter、leave）。動畫中有幾段位置會連著好幾格畫面不動：先以原本的大小量位置，接著縮成 0，
 * 再從 0.8 倍開始放大，而放大的頭幾格常常停在 0.8 倍。Playwright 看到連著兩格位置相同就算「穩定」，照當時的位置點下去；
 * 按鈕接著放大移開時，按下（pointerdown）在按鈕上、放開（pointerup）卻落在旁邊，click 事件送到外框，按鈕的 onClick
 * 沒有跑。Playwright 只檢查第一個事件有沒有點在按鈕上，所以照樣回報點到了（CI 忙時按下與放開之間跑過一格畫面就會這樣：
 * correction-search.spec.js 按了確認框的「全部取代」卻沒送出請求）。
 *
 * 所以測試裡這些元件動畫時只淡入淡出、不縮放：從量好位置的那一格起，按鈕就在最後的位置，點下去一定點在按鈕上。
 * 動畫照樣跑完（只是 transform 被蓋掉），元件打開、收起的時機和平常一樣。用到新的彈出元件時加進這份清單。
 */
const STEADY_POPUPS = `
:is(.ant-popover, .ant-dropdown, .ant-select-dropdown, .ant-modal, .ant-tooltip):is(
    [class*="-appear"], [class*="-enter"], [class*="-leave"]
) {
    transform: none !important;
}
`

/**
 * 瀏覽器測試共用的 test：多一個 mockBackend(options) 換上假後端（見 ./backend.js）；每一頁都套上 STEADY_POPUPS。
 *
 * 每個測試結束時檢查三件事，任一項不成立就算失敗：
 *   - 畫面沒有打假後端沒設定的端點或 WebSocket：新端點要在 backend.js 或測試裡給回應，
 *     不會默默拿到 404
 *   - 畫面沒有向本機以外要資源（ADR-0005）
 *   - 頁面沒有丟出未處理的例外
 */
export const test = base.extend({
    page: async ({ page }, use) => {
        // 每次載入頁面（含重新整理）都在頁面自己的程式之前加上去；彈出元件都是畫面跑起來之後才打開
        await page.addInitScript((css) => {
            const style = document.createElement('style')
            style.textContent = css
            const add = () => document.head.append(style)
            if (document.head) add()
            else document.addEventListener('DOMContentLoaded', add, { once: true })
        }, STEADY_POPUPS)
        await use(page)
    },
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
            expect(backend.unhandled, '畫面打了假後端沒有設定回應的端點或 WebSocket').toEqual([])
            expect(backend.external, '畫面向本機以外要了資源').toEqual([])
        }
        expect(pageErrors, '頁面丟出未處理的例外').toEqual([])
    },
})

export { expect }

/** 做 action（例如點下載選單裡的一種格式），回傳它觸發的下載：建議的檔名與內容（UTF-8 文字）。 */
export async function download(page, action) {
    const [file] = await Promise.all([page.waitForEvent('download'), action()])
    return { filename: file.suggestedFilename(), text: await readFile(await file.path(), 'utf8') }
}
