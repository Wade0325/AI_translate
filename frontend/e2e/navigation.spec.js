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
    // 「Current Month Cost」是頁面自己的內容；頁首的標題是版面畫的，證明不了這一頁的模組載入了
    await expect(page.getByText('Current Month Cost')).toBeVisible()
    // 同一個比對規則這時抓得到這兩個模組：上面的「沒有載入」不是規則沒對上檔名
    expect(billingModules()).toEqual(expect.arrayContaining([
        expect.stringContaining('BillingPage'), expect.stringContaining('recharts'),
    ]))
})

test('直接開 Usage & Billing 頁，等這一頁載入完才一次畫出整個畫面，不先畫出空的內容區或載入中的畫面', async ({ page, mockBackend }) => {
    await mockBackend()
    const apiRequests = []
    page.on('request', (request) => {
        const { pathname } = new URL(request.url())
        if (pathname.startsWith('/api/')) apiRequests.push(pathname)
    })
    // 這一頁的模組晚半秒才到：畫面要是不等它就先畫，這半秒裡看得到沒有內容的畫面
    let apiRequestsBeforePageLoaded = null
    await page.route((url) => url.pathname.endsWith('/BillingPage.jsx'), async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 500))
        apiRequestsBeforePageLoaded = [...apiRequests]
        await route.continue()
    })
    await page.goto('/billing')

    await expect(page.getByRole('heading', { name: 'Usage & Billing' })).toBeVisible()
    // isVisible() 不等待：看的是頁首出現的這一刻，頁面內容是不是也已經在畫面上
    expect(await page.getByText('Current Month Cost').isVisible()).toBe(true)
    // <Suspense> 包在版面外層時頁首和內容也同時出現，上面那一行分不出來，內容卻一樣晚約 0.2 秒。
    // 分得出來的是：React 先畫了載入中的畫面，app 就會在這一頁的模組到之前向後端要資料
    expect(apiRequestsBeforePageLoaded).toEqual([])
    // 同一份記錄這時有東西：上面的「沒有」不是沒記到
    await expect.poll(() => apiRequests).not.toEqual([])
})

test('沒有的頁面改開轉錄頁，不留空白：免安裝版的 /docs 不再是 API 文件（#16 Q4）', async ({ page, mockBackend }) => {
    await mockBackend()
    for (const path of ['/docs', '/redoc', '/no-such-page']) {
        await page.goto(path)

        await expect(page).toHaveURL(/\/transcribe$/)
        await expect(page.getByRole('heading', { name: 'New Transcription' })).toBeVisible()
    }
})
