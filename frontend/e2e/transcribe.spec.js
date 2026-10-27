import { test, expect, download } from './support/test.js'
import { GEMINI_UPLOAD_NOTICE, PROVIDERS, TRANSCRIPTS, transcriptionMessages } from './support/backend.js'

// 內容不重要：音檔只經過假後端，不會被解碼
const AUDIO = { name: 'meeting.wav', mimeType: 'audio/wav', buffer: Buffer.from('RIFF0000WAVE') }

async function addAudio(page) {
    await page.locator('.ant-upload input[type=file]').setInputFiles(AUDIO)
    await expect(page.getByText(AUDIO.name)).toBeVisible()
}

test('處理模式預設是標準；Gemini 仍可選 Flex 與批次（#18）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')

    await expect(page.getByLabel('供應商')).toHaveValue('google')
    await expect(page.getByLabel('處理模式')).toHaveValue('standard')
    await expect(page.getByRole('option', { name: /^Flex/ })).toBeEnabled()
    await expect(page.getByRole('option', { name: /^批次/ })).toBeEnabled()
})

test('選 Gemini 時說明音檔會上傳到 Google 並連到條款原文；選本機時不顯示（#231 Q6）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')

    await expect(page.getByLabel('供應商')).toHaveValue('google')
    await expect(page.getByText(/音檔（含檔名）與提示詞會上傳到 Google/)).toBeVisible()
    await expect(page.getByRole('link', { name: '條款原文' })).toHaveAttribute('href', GEMINI_UPLOAD_NOTICE.terms_url)

    await page.getByLabel('供應商').selectOption('local')

    await expect(page.getByText(/會上傳到 Google/)).toHaveCount(0)
    await expect(page.getByRole('link', { name: '條款原文' })).toHaveCount(0)
})

test('費用估算只給按 token 計費的模型：選本機時只顯示檔案數與大小（#18）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')
    await addAudio(page)

    // Gemini 按 token 計費：估算時長、處理時間與費用
    await expect(page.getByText('est.')).toBeVisible()

    await page.getByLabel('供應商').selectOption('local')

    await expect(page.getByText('est.')).toHaveCount(0)
    await expect(page.getByText(/~\d+ min/)).toHaveCount(0)
    await expect(page.getByText(/^1 files$/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start' })).toBeEnabled()
})

test('選本機送出一個檔案，顯示處理中，完成後到結果頁下載 SRT', async ({ page, mockBackend }) => {
    // 假後端送出處理中之後先停住，等畫面上看到處理中才送完成
    let finish
    const finished = new Promise((resolve) => { finish = resolve })
    const backend = await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
        transcribe: async (request, send) => {
            const { processing, completed } = transcriptionMessages(request)
            send(processing)
            await finished
            send(completed)
        },
    })
    await page.goto('/transcribe')

    await page.getByLabel('供應商').selectOption('local')
    await page.getByLabel('模型').selectOption('moss-align')
    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    await expect(page.getByText('轉錄中...')).toBeVisible()
    finish()
    await expect(page.getByText('轉錄完成')).toBeVisible()
    // 先上傳，再用上傳拿到的伺服器檔名開任務；本機不吃提示詞與使用者文稿，送出時不帶
    expect(backend.requests.filter((r) => r.path === '/upload')).toHaveLength(1)
    expect(backend.transcriptionRequests).toEqual([
        expect.objectContaining({
            filename: 'meeting_1.wav',
            original_filename: AUDIO.name,
            provider: 'local',
            model: 'moss-align',
            prompt: null,
            user_supplied_text: null,
        }),
    ])

    // 從側欄換頁：轉錄頁的檔案清單只在這次瀏覽裡，重新載入就沒了
    await page.getByRole('link', { name: 'Result Viewer' }).click()
    await expect(page).toHaveURL(/\/result$/)
    await expect(page.getByText(AUDIO.name)).toBeVisible()

    await page.getByRole('button', { name: 'Download', exact: true }).hover()
    expect(await download(page, () => page.getByText('SRT (Subtitles)').click()))
        .toEqual({ filename: 'meeting.srt', text: TRANSCRIPTS.srt })
})

test('任務失敗時，檔案卡顯示後端的失敗原因', async ({ page, mockBackend }) => {
    const reason = '找不到 NVIDIA 顯示卡，本機轉錄無法執行'
    await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
        transcribe: async (request, send) => {
            send({ task_uuid: 'task-1', status_code: 'FAILED', status_text: reason, file_uid: request.file_uid })
        },
    })
    await page.goto('/transcribe')

    await page.getByLabel('供應商').selectOption('local')
    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    await expect(page.getByText(reason)).toBeVisible()
    await expect(page.getByText('1 個任務失敗')).toBeVisible()
    // 失敗的檔案可以重新轉錄
    await expect(page.getByRole('button', { name: 'Start' })).toBeEnabled()
})

/** 供應商清單，但 Gemini 的模型吃使用者文稿（#66 修好之後的樣子）。 */
const GEMINI_TAKES_USER_TEXT = PROVIDERS.map((p) => p.provider !== 'google' ? p : {
    ...p,
    models: p.models.map((m) => ({ ...m, capabilities: { ...m.capabilities, accepts_user_text: true } })),
})

test('沒有模型吃使用者文稿時，檔案卡不提供附加使用者文稿的按鈕', async ({ page, mockBackend }) => {
    // #66 修好之前使用者文稿到不了任務，#13 Q4 定案先隱藏入口
    await mockBackend()
    await page.goto('/transcribe')
    await addAudio(page)

    for (const provider of ['google', 'local']) {
        await page.getByLabel('供應商').selectOption(provider)
        await expect(page.getByRole('button', { name: '附加使用者文稿' })).toHaveCount(0)
    }
})

test('所選的模型吃使用者文稿時，附加的使用者文稿隨請求送出', async ({ page, mockBackend }) => {
    const backend = await mockBackend({
        routes: { 'GET /providers': GEMINI_TAKES_USER_TEXT, 'POST /upload': { filename: 'meeting_1.wav' } },
    })
    await page.goto('/transcribe')
    await page.getByLabel('供應商').selectOption('google')
    // 假後端只模擬單檔任務
    await page.getByLabel('處理模式').selectOption('standard')
    await addAudio(page)

    await page.getByRole('button', { name: '附加使用者文稿' }).click()
    const dialog = page.getByRole('dialog', { name: '附加使用者文稿' })
    await dialog.getByRole('textbox').fill('おはよう。')
    // antd 在兩個中文字的按鈕字中間插一個空格
    await dialog.getByRole('button', { name: /^保\s*存$/ }).click()
    await page.getByRole('button', { name: 'Start' }).click()

    await expect(page.getByText('轉錄完成')).toBeVisible()
    expect(backend.transcriptionRequests).toEqual([
        expect.objectContaining({ provider: 'google', user_supplied_text: 'おはよう。' }),
    ])
})

test('去靜音與切點預覽是開發者工具：沒開時檔案卡沒有按鈕', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')
    await addAudio(page)

    await expect(page.getByRole('button', { name: '去靜音與切點預覽' })).toHaveCount(0)
})

/** 開了開發者工具、預覽回一個語音佔比 60%（低於門檻）的音檔。 */
const VAD_PREVIEW_ROUTES = {
    'GET /vad/enabled': { enabled: true },
    'POST /upload': { filename: 'meeting_1.wav' },
    'POST /vad/test': {
        success: true, task_id: 'abc', original_filename: AUDIO.name, artifact_dir: null, error: null,
        speech_extraction: {
            success: true, speech_ratio: 0.6, speech_duration_seconds: 3.0, total_duration_seconds: 5.0,
            segment_count: 1, would_use_speech_only: true, segments: [{ start: 0.5, end: 3.5 }],
            segments_truncated: false,
        },
        split: { success: true, split_point_seconds: 2.5, part1_duration_seconds: 2.5, part2_duration_seconds: 2.5 },
    },
}

test('開了開發者工具時，預覽一個檔案並顯示找到的切點', async ({ page, mockBackend }) => {
    const backend = await mockBackend({ routes: VAD_PREVIEW_ROUTES })
    await page.goto('/transcribe')
    await addAudio(page)

    await page.getByRole('button', { name: '去靜音與切點預覽' }).click()

    const dialog = page.getByRole('dialog', { name: '去靜音與切點預覽' })
    await expect(dialog.getByText('去靜音（speech_only）')).toBeVisible()
    await expect(dialog.getByText('2.5s').first()).toBeVisible()
    // 預設的供應商是 Gemini，它的模型去靜音
    await expect(dialog.getByText('正式轉錄會使用 speech_only.wav')).toBeVisible()
    expect(backend.requests.find((r) => r.path === '/vad/test').body)
        .toEqual({ filename: 'meeting_1.wav', original_filename: AUDIO.name, include_split: true })
})

test('預覽依所選的模型說明正式轉錄：本機的模型不去靜音，切在靜音的正中間', async ({ page, mockBackend }) => {
    await mockBackend({ routes: VAD_PREVIEW_ROUTES })
    await page.goto('/transcribe')
    await page.getByLabel('供應商').selectOption('local')
    await addAudio(page)

    await page.getByRole('button', { name: '去靜音與切點預覽' }).click()

    const dialog = page.getByRole('dialog', { name: '去靜音與切點預覽' })
    await expect(dialog.getByText('所選的模型不去靜音：正式轉錄用原檔，分段轉錄時切在靜音的正中間'))
        .toBeVisible()
    await expect(dialog.getByText('正式轉錄會使用 speech_only.wav')).toHaveCount(0)
})

test('轉錄頁記住上次選的供應商與模型：重新開頁還是同一組，存的只有名稱', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')

    // 第一次開頁照供應商清單的順序，用第一個供應商的預設模型
    await expect(page.getByLabel('供應商')).toHaveValue('google')
    await expect(page.getByLabel('模型')).toHaveValue('gemini-3.5-flash')

    await page.getByLabel('供應商').selectOption('local')
    await expect(page.getByLabel('模型')).toHaveValue('moss-align')
    await page.reload()

    await expect(page.getByLabel('供應商')).toHaveValue('local')
    await expect(page.getByLabel('模型')).toHaveValue('moss-align')
    expect(await page.evaluate(() => ({ ...localStorage })))
        .toEqual({ ai_translate_last_selection: JSON.stringify({ provider: 'local', model: null }) })
})

test('上次選的供應商已經不在清單上時，退回清單上的第一個', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.addInitScript(() => {
        // eslint-disable-next-line no-restricted-syntax -- 測試先放一組已經不在清單上的供應商與模型名稱，不是金鑰
        localStorage.setItem('ai_translate_last_selection', JSON.stringify({ provider: 'openai', model: 'whisper-1' }))
    })
    await page.goto('/transcribe')

    await expect(page.getByLabel('供應商')).toHaveValue('google')
    await expect(page.getByLabel('模型')).toHaveValue('gemini-3.5-flash')
})

test('「編輯 API」只有一個金鑰欄位，保存時只送這一把', async ({ page, mockBackend }) => {
    const newKey = 'AIzaSyNEWKEY000000abcd'
    const backend = await mockBackend({
        routes: {
            'GET /setting/models/google': { provider: 'Google', apiKeys: ['AIza********wxyz', 'AIza********9999'], model: 'gemini-3.5-flash', prompt: null },
            'POST /setting/models': { success: true },
        },
    })
    await page.goto('/transcribe')

    await page.getByRole('button', { name: '編輯 API' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByPlaceholder('API Key')).toHaveCount(1)
    await expect(dialog.getByPlaceholder('API Key')).toHaveValue('AIza********wxyz')

    await dialog.getByPlaceholder('API Key').fill(newKey)
    // antd 會在兩個字的中文按鈕中間加空白：「保 存」
    await dialog.getByRole('button', { name: '保 存' }).click()

    await expect(page.getByText('設定保存成功！')).toBeVisible()
    expect(backend.requests.filter((r) => r.method === 'POST' && r.path === '/setting/models').map((r) => r.body.apiKeys))
        .toEqual([[newKey]])
})
