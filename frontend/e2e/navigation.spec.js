import { test, expect } from './support/test.js'

test('首頁直接開轉錄頁；側欄沒有 Dashboard、Usage & Billing 與假的帳號資訊（#18）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/')

    await expect(page).toHaveURL(/\/transcribe$/)
    await expect(page.getByRole('heading', { name: 'New Transcription' })).toBeVisible()
    const sidebar = page.locator('.ant-layout-sider')
    await expect(sidebar.getByRole('link', { name: 'New Transcription' })).toBeVisible()
    await expect(sidebar.getByRole('link', { name: 'History' })).toBeVisible()
    await expect(sidebar.getByRole('link', { name: 'Settings' })).toBeVisible()
    await expect(sidebar.getByRole('link', { name: 'Dashboard' })).toHaveCount(0)
    await expect(sidebar.getByRole('link', { name: 'Usage & Billing' })).toHaveCount(0)
    await expect(sidebar.getByText('Free Plan')).toHaveCount(0)
})

test('Usage & Billing 頁拿掉入口後仍能直接開，頁首不提訂閱（#18）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/billing')

    await expect(page.getByRole('heading', { name: 'Usage & Billing' })).toBeVisible()
    await expect(page.getByText(/subscription/i)).toHaveCount(0)
})

test('沒有的頁面改開轉錄頁，不留空白：免安裝版的 /docs 不再是 API 文件（#16 Q4）', async ({ page, mockBackend }) => {
    await mockBackend()
    for (const path of ['/docs', '/redoc', '/no-such-page']) {
        await page.goto(path)

        await expect(page).toHaveURL(/\/transcribe$/)
        await expect(page.getByRole('heading', { name: 'New Transcription' })).toBeVisible()
    }
})
