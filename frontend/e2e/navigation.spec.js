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

test('Usage & Billing 頁與只有它用到的圖表套件 recharts，開那一頁才載入', async ({ page, mockBackend }) => {
    await mockBackend()
    const requested = []
    page.on('request', (request) => requested.push(new URL(request.url()).pathname))
    const billingModules = () => requested.filter((path) => /BillingPage|recharts/.test(path))

    await page.goto('/transcribe')
    // 畫面出來時，這一頁要用的模組都已經載入完
    await expect(page.getByRole('heading', { name: 'New Transcription' })).toBeVisible()
    expect(billingModules()).toEqual([])

    await page.goto('/billing')
    // 「Current Month Cost」是頁面自己的內容；頁首的標題在版面裡，頁面沒載入也會出現
    await expect(page.getByText('Current Month Cost')).toBeVisible()
    // 同一個比對規則這時抓得到這兩個模組：上面的「沒有載入」不是規則沒對上檔名
    expect(billingModules()).toEqual(expect.arrayContaining([
        expect.stringContaining('BillingPage'), expect.stringContaining('recharts'),
    ]))
})

test('直接開 Usage & Billing 頁，頁首和頁面內容同時出現，不先露出空的內容區', async ({ page, mockBackend }) => {
    await mockBackend()
    // 這一頁的模組晚半秒才到：畫面要是不等它就先畫出頁首，這半秒裡內容區是空的
    let delayed = false
    await page.route((url) => url.pathname.endsWith('/BillingPage.jsx'), async (route) => {
        delayed = true
        await new Promise((resolve) => setTimeout(resolve, 500))
        await route.continue()
    })
    await page.goto('/billing')

    await expect(page.getByRole('heading', { name: 'Usage & Billing' })).toBeVisible()
    // isVisible() 不等待：看的是頁首出現的這一刻，頁面內容是不是也已經在畫面上
    expect(await page.getByText('Current Month Cost').isVisible()).toBe(true)
    expect(delayed).toBe(true)
})

test('沒有的頁面改開轉錄頁，不留空白：免安裝版的 /docs 不再是 API 文件（#16 Q4）', async ({ page, mockBackend }) => {
    await mockBackend()
    for (const path of ['/docs', '/redoc', '/no-such-page']) {
        await page.goto(path)

        await expect(page).toHaveURL(/\/transcribe$/)
        await expect(page.getByRole('heading', { name: 'New Transcription' })).toBeVisible()
    }
})
