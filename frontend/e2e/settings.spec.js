import { test, expect } from './support/test.js'
import { GOOGLE_CONFIG, MASKED_KEY, PROVIDERS, reply } from './support/backend.js'

/** 設定頁上某個供應商的卡片。 */
const providerCard = (page, label) => page.locator('.ant-card').filter({ hasText: label })

/** 畫面送出的「儲存供應商設定」請求。 */
const saveRequests = (backend) => backend.requests.filter((r) => r.method === 'POST' && r.path === '/setting/models')

test('金鑰欄位只顯示遮罩值；沒改金鑰就儲存時，送回的是遮罩值', async ({ page, mockBackend }) => {
    const backend = await mockBackend({
        routes: { 'POST /setting/models': { success: true } },
    })
    await page.goto('/settings')

    const gemini = providerCard(page, 'Gemini')
    await expect(gemini.getByPlaceholder('API Key')).toHaveValue(MASKED_KEY)
    // 本機不用金鑰，沒有金鑰欄位
    await expect(providerCard(page, '本機').getByPlaceholder('API Key')).toHaveCount(0)

    await gemini.getByRole('textbox').last().fill('請保留說話者標記')
    await gemini.getByRole('button', { name: 'Save' }).click()

    await expect(page.getByText('設定保存成功！')).toBeVisible()
    // 後端收到遮罩值時保留資料庫裡原本的金鑰（#10，由 tests 的 test_api_key_masking.py 涵蓋）
    expect(saveRequests(backend)).toEqual([
        expect.objectContaining({
            body: expect.objectContaining({ provider: 'google', apiKeys: [MASKED_KEY], prompt: '請保留說話者標記' }),
        }),
    ])
})

test('輸入新金鑰儲存後，欄位換成後端回的遮罩值，明文不留在畫面上', async ({ page, mockBackend }) => {
    const newKey = 'AIzaSyNEWKEY000000abcd'
    const newMasked = 'AIza**************abcd'
    let stored = MASKED_KEY
    const backend = await mockBackend({
        routes: {
            'GET /setting/models/google': () => ({ ...GOOGLE_CONFIG, apiKeys: [stored] }),
            'POST /setting/models': () => {
                stored = newMasked
                return { success: true }
            },
        },
    })
    await page.goto('/settings')

    const keyField = providerCard(page, 'Gemini').getByPlaceholder('API Key')
    await keyField.fill(newKey)
    await providerCard(page, 'Gemini').getByRole('button', { name: 'Save' }).click()

    await expect(keyField).toHaveValue(newMasked)
    // 明文只送一次，給後端存起來
    expect(saveRequests(backend).map((r) => r.body.apiKeys)).toEqual([[newKey]])
    const fieldValues = await page.locator('input').evaluateAll((inputs) => inputs.map((input) => input.value))
    expect(fieldValues).not.toContain(newKey)
})

test('儲存失敗時顯示後端的原因，修改還留著', async ({ page, mockBackend }) => {
    await mockBackend({
        routes: { 'POST /setting/models': reply(500, { detail: '資料庫被鎖住，請稍後再試' }) },
    })
    await page.goto('/settings')

    const gemini = providerCard(page, 'Gemini')
    await gemini.getByRole('textbox').last().fill('請保留說話者標記')
    await gemini.getByRole('button', { name: 'Save' }).click()

    await expect(page.getByText('後端保存失敗: 資料庫被鎖住，請稍後再試')).toBeVisible()
    await expect(gemini.getByText('Unsaved changes')).toBeVisible()
    await expect(gemini.getByRole('textbox').last()).toHaveValue('請保留說話者標記')
})

test('金鑰只有一個欄位：舊版存了多把時只顯示第一把，儲存時只送第一把', async ({ page, mockBackend }) => {
    const secondKey = 'AIza********9999'
    const backend = await mockBackend({
        routes: {
            'GET /setting/models/google': { ...GOOGLE_CONFIG, apiKeys: [MASKED_KEY, secondKey] },
            'POST /setting/models': { success: true },
        },
    })
    await page.goto('/settings')

    const gemini = providerCard(page, 'Gemini')
    await expect(gemini.getByPlaceholder('API Key')).toHaveCount(1)
    await expect(gemini.getByPlaceholder('API Key')).toHaveValue(MASKED_KEY)
    await expect(gemini.getByRole('button', { name: /Add API Key/ })).toHaveCount(0)

    await gemini.getByRole('textbox').last().fill('請保留說話者標記')
    await gemini.getByRole('button', { name: 'Save' }).click()

    await expect(page.getByText('設定保存成功！')).toBeVisible()
    // 後端只用第一把（#19）；第二把以後從來沒被用過，存檔時拿掉
    expect(saveRequests(backend).map((r) => r.body.apiKeys)).toEqual([[MASKED_KEY]])
})

test('清空金鑰欄位後儲存，送出空清單，後端就刪掉金鑰', async ({ page, mockBackend }) => {
    const backend = await mockBackend({
        routes: { 'POST /setting/models': { success: true } },
    })
    await page.goto('/settings')

    const gemini = providerCard(page, 'Gemini')
    await gemini.getByPlaceholder('API Key').fill('')
    await gemini.getByRole('button', { name: 'Save' }).click()

    await expect(page.getByText('設定保存成功！')).toBeVisible()
    expect(saveRequests(backend).map((r) => r.body.apiKeys)).toEqual([[]])
})

test('設定頁沒有 Default Model 與 Notifications；本機的 Test Connection 測預設模型', async ({ page, mockBackend }) => {
    // 本機有兩個模型，資料庫裡舊版設定頁存的是第二個：測試照樣測預設的第一個
    const model = (id) => ({ ...PROVIDERS[1].models[0], model: id, label: id })
    const twoLocalModels = PROVIDERS.map((p) => p.provider !== 'local' ? p : {
        ...p, models: [model('moss-align'), model('vibevoice-qwen3-asr')],
    })
    const backend = await mockBackend({
        routes: {
            'GET /providers': twoLocalModels,
            'GET /setting/models/local': { provider: 'Local', apiKeys: [], model: 'vibevoice-qwen3-asr', prompt: null },
            'POST /setting/test': { success: true, message: '本機已就緒：顯卡 測試用顯卡，moss-align 的模型權重都已下載' },
        },
    })
    await page.goto('/settings')

    await expect(providerCard(page, '本機')).toBeVisible()
    await expect(page.getByText('Default Model')).toHaveCount(0)
    await expect(page.getByText('Notifications')).toHaveCount(0)
    await expect(page.getByText('Weekly Usage Report')).toHaveCount(0)

    await providerCard(page, '本機').getByRole('button', { name: 'Test Connection' }).click()

    await expect(page.getByText('本機已就緒')).toBeVisible()
    expect(backend.requests.filter((r) => r.path === '/setting/test').map((r) => r.body))
        .toEqual([{ provider: 'local', apiKeys: [], model: 'moss-align' }])
})
