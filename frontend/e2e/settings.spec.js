import { test, expect } from './support/test.js'
import { GEMINI_UPLOAD_NOTICE, GOOGLE_CONFIG, LOCAL_DATA, MASKED_KEY, PROVIDERS, reply } from './support/backend.js'

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

test('About 顯示版本號與新版本的下載頁連結，app 自己不連到 GitHub', async ({ page, mockBackend }) => {
    const external = []
    page.on('request', (request) => {
        const { hostname } = new URL(request.url())
        if (hostname !== '127.0.0.1' && hostname !== 'localhost') external.push(request.url())
    })
    await mockBackend({ routes: { 'GET /version': { version: 'v0.1.0-beta.1' } } })
    await page.goto('/settings')

    const about = providerCard(page, 'About')
    await expect(about.getByText('v0.1.0-beta.1')).toBeVisible()
    const releases = about.getByRole('link', { name: 'GitHub Releases' })
    await expect(releases).toHaveAttribute('href', 'https://github.com/Wade0325/AI_translate/releases')
    // 在新分頁開，不帶 referrer；點了才連外
    await expect(releases).toHaveAttribute('target', '_blank')
    await expect(releases).toHaveAttribute('rel', 'noopener noreferrer')
    // 沒有任何對 GitHub 的請求
    expect(external.filter((url) => new URL(url).hostname.endsWith('github.com'))).toEqual([])
})

test('讀不到版本號時照樣顯示下載頁連結', async ({ page, mockBackend }) => {
    await mockBackend({ routes: { 'GET /version': reply(500, { detail: '壞掉了' }) } })
    await page.goto('/settings')

    const about = providerCard(page, 'About')
    await expect(about.getByText('讀不到')).toBeVisible()
    await expect(about.getByRole('link', { name: 'GitHub Releases' })).toBeVisible()
})

/** 「資料與隱私」卡片上的保留音檔：retained 蓋過假後端預設的那一份。 */
const localData = (retained, extra = {}) => ({
    ...LOCAL_DATA, ...extra, retained_audio: { ...LOCAL_DATA.retained_audio, ...retained },
})

/** 畫面送出的「刪除全部保留音檔」請求。 */
const deleteRequests = (backend) => backend.requests.filter((r) => r.method === 'DELETE')

test('資料與隱私：說明保留音檔留多久、放在哪，確認後立即刪除全部（#231 Q1）', async ({ page, mockBackend }) => {
    let current = localData({ file_count: 2, total_bytes: 3 * 1024 * 1024 })
    const backend = await mockBackend({
        routes: {
            'GET /local-data': () => current,
            'DELETE /local-data/retained-audio': () => {
                current = localData({ file_count: 0, total_bytes: 0 })
                return { deleted: 2, failed: 0 }
            },
        },
    })
    await page.goto('/settings')

    const card = providerCard(page, '資料與隱私')
    await expect(card.getByText(/上傳超過 30 天的，在下次開啟 app 時刪除/)).toBeVisible()
    await expect(card.getByText('/app/audio_store')).toBeVisible()
    await expect(card.getByText('目前保留 2 個音檔，共 3.0 MB')).toBeVisible()
    // Docker 模式沒有單一的資料夾，不說明 data 資料夾
    await expect(card.getByText('資料放在哪')).toHaveCount(0)

    // 刪除不可逆：先確認才送出
    await card.getByRole('button', { name: '立即刪除全部保留音檔' }).click()
    await expect(page.getByText('刪除全部保留音檔？')).toBeVisible()
    expect(deleteRequests(backend)).toEqual([])
    await page.getByRole('button', { name: /^刪\s*除$/ }).click()

    await expect(page.getByText('已刪除 2 個保留音檔')).toBeVisible()
    await expect(card.getByText('目前保留 0 個音檔，共 0 MB')).toBeVisible()
    await expect(card.getByRole('button', { name: '立即刪除全部保留音檔' })).toBeDisabled()
    expect(deleteRequests(backend).map((r) => r.path)).toEqual(['/local-data/retained-audio'])
})

test('資料與隱私：取消確認就不刪；有刪不掉的照實說', async ({ page, mockBackend }) => {
    const backend = await mockBackend({
        routes: {
            'GET /local-data': localData({ file_count: 3, total_bytes: 10 }),
            'DELETE /local-data/retained-audio': { deleted: 2, failed: 1 },
        },
    })
    await page.goto('/settings')

    const card = providerCard(page, '資料與隱私')
    await card.getByRole('button', { name: '立即刪除全部保留音檔' }).click()
    await page.getByRole('button', { name: /^取\s*消$/ }).click()
    expect(deleteRequests(backend)).toEqual([])

    await card.getByRole('button', { name: '立即刪除全部保留音檔' }).click()
    await page.getByRole('button', { name: /^刪\s*除$/ }).click()
    await expect(page.getByText('已刪除 2 個保留音檔；1 個正在使用中，沒刪掉，請稍後再試')).toBeVisible()
})

test('資料與隱私：免安裝版說明 data 資料夾裡哪些是個人資料，以及日誌檔（#231 Q5、Q7）', async ({ page, mockBackend }) => {
    await mockBackend({
        routes: {
            'GET /local-data': localData({ retention_days: 0, folder: 'D:\\AI_Translate\\data\\audio_store' },
                { data_folder: 'D:\\AI_Translate\\data' }),
        },
    })
    await page.goto('/settings')

    const card = providerCard(page, '資料與隱私')
    await expect(card.getByText(/不會自動刪除/)).toBeVisible()
    await expect(card.getByText('D:\\AI_Translate\\data', { exact: true })).toBeVisible()
    await expect(card.getByText(/任務紀錄、轉錄結果與 API 金鑰/)).toBeVisible()
    await expect(card.getByText(/日誌檔，回報問題時附上；不含原檔名、提示詞與轉錄內容/)).toBeVisible()
    await expect(card.getByText(/先關掉 app，再刪掉 models 以外的項目/)).toBeVisible()
})

test('Gemini 的卡片說明音檔會上傳到 Google，並連到條款原文；本機沒有（#231 Q6）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/settings')

    const gemini = providerCard(page, 'Gemini')
    await expect(gemini.getByText(/音檔與提示詞會上傳到 Google/)).toBeVisible()
    const terms = gemini.getByRole('link', { name: '條款原文' })
    await expect(terms).toHaveAttribute('href', GEMINI_UPLOAD_NOTICE.terms_url)
    await expect(terms).toHaveAttribute('rel', 'noopener noreferrer')
    await expect(providerCard(page, '本機').getByRole('link', { name: '條款原文' })).toHaveCount(0)
})

/**
 * 免安裝模式的本機模型權重狀態（GET /setting/local-models/status）：8 GB 的顯卡，預設模型的權重都
 * 已下載。fields 蓋過其中的欄位。
 */
const localStatus = (fields) => ({
    standalone: true, gpu_available: true, gpu_name: 'NVIDIA GeForce RTX 4060', gpu_vram_gb: 8.0,
    gpu_problem: null, vram_notice: null, hf_home: 'data/models/hf_cache', default_model: 'moss-align',
    required_size_gb: 3.7, optional_size_gb: 20.8,
    models: [
        { repo_id: 'OpenMOSS-Team/MOSS-Transcribe-Diarize', downloaded: true, required: true, used_by: ['moss-align', 'moss-qwen3-asr'] },
        { repo_id: 'Qwen/Qwen3-ForcedAligner-0.6B-hf', downloaded: true, required: true, used_by: ['moss-align', 'moss-qwen3-asr', 'vibevoice-qwen3-asr'] },
    ],
    all_downloaded: true, optional_downloaded: true,
    download: { state: 'idle', target: null, repo_index: 0, repo_count: 2, current_repo: null, progress_pct: null, error: null },
    ...fields,
})

test('本機卡片顯示顯卡與記憶體；低於最低需求時提示（#11 Q2）', async ({ page, mockBackend }) => {
    const notice = '顯卡記憶體 8 GB 沒有測過（建議 16 GB、至少 12 GB）。長音檔會切成約 26 分鐘一段，各段的說話者編號比較容易對不上'
    await mockBackend({ routes: { 'GET /setting/local-models/status': localStatus({ vram_notice: notice }) } })
    await page.goto('/settings')

    const local = providerCard(page, 'Local Models')
    await expect(local.getByText('GPU: NVIDIA GeForce RTX 4060（8 GB）')).toBeVisible()
    await expect(local.getByText(notice)).toBeVisible()
})

test('本機卡片說明顯卡太舊、本機轉錄不支援，也不能下載模型權重（#11 Q4）', async ({ page, mockBackend }) => {
    const problem = '這張顯卡（NVIDIA GeForce GTX 1080）太舊，本機轉錄不支援：GTX 10 系列以前的 NVIDIA 顯卡都用不了，可以改用 Gemini'
    await mockBackend({
        routes: {
            'GET /setting/local-models/status': localStatus({
                gpu_available: false, gpu_name: 'NVIDIA GeForce GTX 1080', gpu_problem: problem,
                models: localStatus({}).models.map((m) => ({ ...m, downloaded: false })),
                all_downloaded: false,
            }),
        },
    })
    await page.goto('/settings')

    const local = providerCard(page, 'Local Models')
    await expect(local.getByText(problem)).toBeVisible()
    await expect(local.getByRole('button', { name: /下載模型權重/ })).toBeDisabled()
})
