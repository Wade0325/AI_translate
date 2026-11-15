import { test, expect } from './support/test.js'
import { reply, transcriptionMessages } from './support/backend.js'

/** seconds 秒的無聲 WAV（8 kHz、單聲道、16 位元）：保留音檔的內容不重要，播放器要真的能播、能拖曳。 */
function silentWav(seconds) {
    const rate = 8000
    const data = rate * seconds * 2
    const wav = Buffer.alloc(44 + data)
    wav.write('RIFF', 0)
    wav.writeUInt32LE(36 + data, 4)
    wav.write('WAVEfmt ', 8)
    wav.writeUInt32LE(16, 16)
    wav.writeUInt16LE(1, 20)
    wav.writeUInt16LE(1, 22)
    wav.writeUInt32LE(rate, 24)
    wav.writeUInt32LE(rate * 2, 28)
    wav.writeUInt16LE(2, 32)
    wav.writeUInt16LE(16, 34)
    wav.write('data', 36)
    wav.writeUInt32LE(data, 40)
    return wav
}

/** 一字一個逐字時間，平均分在片段裡（漢字一字一詞，標點沒有逐字時間；和本機的對齊器一樣）。 */
function wordsOf(text, start, end) {
    const chars = Array.from(text).filter((c) => /[\p{L}\p{N}]/u.test(c))
    const step = (end - start) / chars.length
    return chars.map((c, i) => ({ text: c, start: start + i * step, end: start + (i + 1) * step }))
}

const segment = (seq, start, end, speaker, text, { words = true } = {}) => ({
    seg_key: `0.${String(seq).padStart(4, '0')}`, seq, start, end, speaker, text, text_alt: null,
    source: words ? 'aligned' : null, confidence: null, review_state: null,
    words: words ? wordsOf(text, start, end) : null,
})

/** GET /transcripts/<task_uuid> 的形狀（backend/app/schemas/schemas.py 的 TranscriptResponse）。 */
const transcript = (taskUuid, segments, fields = {}) => ({
    task_uuid: taskUuid, status: 'COMPLETED', original_filename: 'meeting.wav', audio_duration_seconds: 20.0,
    audio_available: true, correctable: true, uncorrectable_reason: null,
    segment_count: segments.length, segments, ...fields,
})

const MEETING = [
    segment(0, 0.5, 3.5, 'S0', '大家早安，今天先看進度。'),
    segment(1, 4.0, 7.5, 'S1', '前端的校正頁可以播放了。'),
    segment(2, 7.0, 9.0, 'S0', '等一下。'),
    segment(3, 10.0, 14.0, 'S1', '點一個字就從那個字開始。'),
]

/**
 * task-1 的保留音檔：和後端的 FileResponse 一樣支援 Range（只回整個檔時 Chromium 不讓播放器跳到別的時間）。
 * 假後端只回 JSON 與文字，所以另外攔；比假後端晚註冊的攔截先處理。
 */
async function serveAudio(page, seconds) {
    const wav = silentWav(seconds)
    await page.route('**/api/v1/transcripts/task-1/audio', (route) => {
        const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers().range ?? '')
        const headers = { 'Accept-Ranges': 'bytes' }
        if (!range) return route.fulfill({ status: 200, contentType: 'audio/wav', headers, body: wav })
        const start = Number(range[1])
        const end = range[2] ? Number(range[2]) : wav.length - 1
        return route.fulfill({
            status: 206, contentType: 'audio/wav', headers: { ...headers, 'Content-Range': `bytes ${start}-${end}/${wav.length}` },
            body: wav.subarray(start, end + 1),
        })
    })
}

/** 校正頁的假後端：任務 task-1 的片段與保留音檔，再加上 routes。 */
async function openCorrection(page, mockBackend, { segments = MEETING, fields = {}, seconds = 20, routes = {}, audio = true } = {}) {
    const backend = await mockBackend({
        routes: { 'GET /transcripts/task-1': transcript('task-1', segments, fields), ...routes },
    })
    if (audio) await serveAudio(page, seconds)
    await page.goto('/correction/task-1')
    return backend
}

const audioState = (page) => page.locator('audio').evaluate((a) => ({ time: a.currentTime, paused: a.paused, rate: a.playbackRate }))
const row = (page, text) => page.locator('[data-index]', { hasText: text })
/** 那一列反白時找得到一個元素，沒有反白時是 0 個。 */
const highlight = (page, text) => row(page, text).locator('[data-active]')

test('History 只有能校正的任務有「校正」，點了開校正頁，網址帶任務 id', async ({ page, mockBackend }) => {
    const record = (task_uuid, original_filename, correctable) => ({
        task_uuid, request_timestamp: '2026-11-14T10:00:00', completed_at: '2026-11-14T10:03:00',
        status: 'COMPLETED', original_filename, audio_duration_seconds: 20.0, model_used: 'moss-align',
        source_language: 'zh-TW', total_tokens: 0, cost: 0.0, error_code: null, error_message: null,
        is_batch: false, session_id: 's', file_uid: 'f', service_tier_used: 'standard', tail_loss_from_seconds: null,
        correctable, has_corrections: false,
    })
    await mockBackend({
        routes: {
            'GET /history': {
                items: [record('task-1', 'meeting.wav', true), record('task-old', 'old.wav', false)],
                total: 2, page: 1, page_size: 10, total_pages: 1,
            },
            'GET /transcripts/task-1': transcript('task-1', MEETING),
        },
    })
    await serveAudio(page, 20)
    await page.goto('/history')

    await expect(page.getByRole('row', { name: 'old.wav' }).getByRole('link', { name: '校正' })).toHaveCount(0)
    await page.getByRole('row', { name: 'meeting.wav' }).getByRole('link', { name: '校正' }).click()

    await expect(page).toHaveURL(/\/correction\/task-1$/)
    await expect(page.getByRole('heading', { name: '校正' })).toBeVisible()
    await expect(page.getByText('meeting.wav')).toBeVisible()
    await expect(page.locator('[data-index]')).toHaveCount(MEETING.length)
    await expect(row(page, '大家早安')).toContainText('00:00')
    await expect(row(page, '大家早安')).toContainText('S0')

    // 重新整理之後還是同一頁
    await page.reload()
    await expect(row(page, '前端的校正頁')).toBeVisible()
})

test('點片段的時間從那個片段的開頭播放，正在唸的片段反白；點一個字從那個字開始播', async ({ page, mockBackend }) => {
    await openCorrection(page, mockBackend)

    await row(page, '點一個字').getByRole('button', { name: '00:10' }).click()
    await expect.poll(async () => (await audioState(page)).paused).toBe(false)
    const { time } = await audioState(page)
    expect(time).toBeGreaterThanOrEqual(10)
    expect(time).toBeLessThan(12)
    await expect(highlight(page, '點一個字')).toHaveCount(1)
    await expect(highlight(page, '大家早安')).toHaveCount(0)

    // 「進」是第一段的第 9 個字（標點不算）：0.5 + 8 × 0.3 = 2.9 秒
    await row(page, '大家早安').locator('.correction-word', { hasText: '進' }).click()
    const atWord = await audioState(page)
    expect(atWord.time).toBeGreaterThanOrEqual(2.89)
    expect(atWord.time).toBeLessThan(3.2)
    await expect(row(page, '大家早安').locator('.correction-word-active')).toHaveText(/進|度/)
    // 標點沒有逐字時間，不能點
    await expect(row(page, '大家早安').locator('.correction-word', { hasText: '，' })).toHaveCount(0)
})

test('不同說話者重疊時兩段一起反白', async ({ page, mockBackend }) => {
    await openCorrection(page, mockBackend)

    // 第二段（4.0 到 7.5）和第三段（7.0 到 9.0）重疊：從第三段的開頭播，兩段都在唸
    await row(page, '等一下').getByRole('button', { name: '00:07' }).click()
    await page.getByRole('button', { name: '暫停' }).click()
    await expect(page.locator('[data-active]')).toHaveCount(2)
    await expect(highlight(page, '前端的校正頁')).toHaveCount(1)
    await expect(highlight(page, '等一下')).toHaveCount(1)
})

test('播放列：播放與暫停、目前時間與總長、播放速度', async ({ page, mockBackend }) => {
    await openCorrection(page, mockBackend)

    await expect(page.getByLabel('目前時間與總長')).toHaveText('00:00 / 00:20')
    await page.getByRole('button', { name: '播放' }).click()
    await expect.poll(async () => (await audioState(page)).paused).toBe(false)
    await page.getByRole('button', { name: '暫停' }).click()
    await expect.poll(async () => (await audioState(page)).paused).toBe(true)

    await page.getByLabel('播放速度').click()
    await page.getByTitle('1.5 倍').click()
    expect((await audioState(page)).rate).toBe(1.5)
})

test('Gemini 的片段沒有逐字時間：只標出片段，沒有可以點的字', async ({ page, mockBackend }) => {
    const gemini = MEETING.map((s) => ({ ...segment(s.seq, s.start, null, s.speaker, s.text, { words: false }) }))
    await openCorrection(page, mockBackend, { segments: gemini })

    await row(page, '前端的校正頁').getByRole('button', { name: '00:04' }).click()
    // 沒有結束時間的片段一直標到下一段開始
    await expect(highlight(page, '前端的校正頁')).toHaveCount(1)
    await expect(page.locator('.correction-word')).toHaveCount(0)
})

test('保留音檔已經不在時，播放列換成一句說明，文字照樣看得到', async ({ page, mockBackend }) => {
    // 第一段從 0 秒開始（Gemini 常見）：沒有在播放，就不能反白它
    const fromZero = [segment(0, 0, 3.5, 'S0', '大家早安，今天先看進度。'), ...MEETING.slice(1)]
    const backend = await mockBackend({
        routes: { 'GET /transcripts/task-1': transcript('task-1', fromZero, { audio_available: false }) },
    })
    await page.goto('/correction/task-1')

    await expect(page.getByRole('status')).toHaveText('保留音檔已經不在，無法播放；文字照樣看得到')
    await expect(page.getByRole('button', { name: '播放' })).toHaveCount(0)
    await expect(row(page, '大家早安')).toBeVisible()
    // 時間與字不能點，也不去要音檔
    await expect(page.locator('[data-index] button')).toHaveCount(0)
    await expect(page.locator('.correction-word')).toHaveCount(0)
    expect(backend.requests.map((r) => r.path)).not.toContain('/transcripts/task-1/audio')
    // 沒有正在唸的片段：不反白，捲動之後也沒有「回到正在播放的片段」
    await expect(page.locator('[data-active]')).toHaveCount(0)
    await page.getByLabel('片段列表').hover()
    await page.mouse.wheel(0, 300)
    await expect(page.getByRole('button', { name: '回到正在播放的片段' })).toHaveCount(0)
})

test('打開之後保留音檔才讀不到時，播放列也換成一句說明', async ({ page, mockBackend }) => {
    await openCorrection(page, mockBackend, {
        audio: false,
        routes: { 'GET /transcripts/task-1/audio': reply(404, { detail: '音檔已不存在（未保留或已超過保留期限）' }) },
    })

    await expect(page.getByRole('status')).toHaveText('保留音檔無法播放；文字照樣看得到')
    await expect(row(page, '大家早安')).toBeVisible()
})

test.describe('直接開不能校正的任務的網址：寫一句說明，不出錯', () => {
    for (const [name, response, message] of [
        ['任務不存在', reply(404, { detail: '找不到此任務紀錄' }), '找不到這個任務，可能已經在 History 刪掉了。'],
        ['還沒完成', transcript('task-1', [], { status: 'PROCESSING', correctable: false, uncorrectable_reason: 'not_completed' }),
            '這個任務還沒完成，完成之後才能校正。'],
        ['沒有片段', transcript('task-1', [], { correctable: false, uncorrectable_reason: 'no_segments' }),
            '這個任務沒有可以逐段校正的片段：轉錄結果是空的，或是較早版本轉錄、只存了整份轉錄結果的任務。'],
        ['轉錄並翻譯的任務', transcript('task-1', MEETING, { correctable: false, uncorrectable_reason: 'with_translation' }),
            '這個任務是轉錄並翻譯，翻譯過的結果不能校正。'],
    ]) {
        test(name, async ({ page, mockBackend }) => {
            await mockBackend({ routes: { 'GET /transcripts/task-1': response } })
            await page.goto('/correction/task-1')

            await expect(page.getByText(message)).toBeVisible()
            await expect(page.locator('[data-index]')).toHaveCount(0)
            await expect(page.locator('audio')).toHaveCount(0)
            await expect(page.getByRole('link', { name: '回到 History' })).toBeVisible()
        })
    }
})

test('上千個片段只畫看得到的那幾列，捲到底看得到最後一段', async ({ page, mockBackend }) => {
    const many = Array.from({ length: 2000 }, (_, i) => segment(i, i * 3.6, i * 3.6 + 3, `S${i % 2}`, `第 ${i + 1} 句`))
    await openCorrection(page, mockBackend, { segments: many, fields: { audio_duration_seconds: 7200 } })

    await expect(row(page, '第 1 句')).toBeVisible()
    expect(await page.locator('[data-index]').count()).toBeLessThan(60)

    await page.getByLabel('片段列表').evaluate((list) => { list.scrollTop = list.scrollHeight })
    await expect(row(page, '第 2000 句')).toBeVisible()
    expect(await page.locator('[data-index]').count()).toBeLessThan(60)
})

test('跟著播放：使用者自己捲走時不搶回去，按「回到正在播放的片段」才捲回來', async ({ page, mockBackend }) => {
    // 每段 0.2 秒：播放一下子就換好幾段
    const many = Array.from({ length: 400 }, (_, i) => segment(i, i * 0.2, i * 0.2 + 0.2, 'S0', `第 ${i + 1} 句`))
    await openCorrection(page, mockBackend, { segments: many, seconds: 80, fields: { audio_duration_seconds: 80 } })

    // 從第 200 段開始播：列表跟著捲過去
    await page.getByLabel('片段列表').evaluate((list) => { list.scrollTop = list.scrollHeight / 2 })
    await row(page, '第 200 句').getByRole('button').click()
    await expect(page.locator('[data-active]')).toBeInViewport()
    await expect(page.getByRole('button', { name: '回到正在播放的片段' })).toHaveCount(0)

    // 自己用滾輪捲到最上面：不再跟著播放
    const list = page.getByLabel('片段列表')
    await list.hover()
    for (let i = 0; i < 20; i += 1) await page.mouse.wheel(0, -2000)
    await expect(row(page, '第 1 句')).toBeVisible()
    await page.waitForTimeout(800)
    await expect(row(page, '第 1 句')).toBeVisible()
    await expect(page.locator('[data-active]')).not.toBeInViewport()

    await page.getByRole('button', { name: '回到正在播放的片段' }).click()
    await expect(page.locator('[data-active]')).toBeInViewport()
    await expect(page.getByRole('button', { name: '回到正在播放的片段' })).toHaveCount(0)
})

test('Result 頁完成的檔案卡有「校正」；回上一頁時這次完成的檔案還在', async ({ page, mockBackend }) => {
    await mockBackend({
        routes: {
            'POST /upload': { filename: 'meeting_1.wav' },
            'GET /transcripts/task-1': transcript('task-1', MEETING),
        },
        // 任務 id 固定成 task-1，校正頁才有固定的端點可以接
        transcribe: async (request, send) => {
            const { processing, completed } = transcriptionMessages(request)
            send({ ...processing, task_uuid: 'task-1' })
            send({ ...completed, task_uuid: 'task-1', result: { ...completed.result, task_uuid: 'task-1' } })
        },
    })
    await serveAudio(page, 20)
    await page.goto('/transcribe')
    await page.getByLabel('供應商').selectOption('local')
    await page.locator('.ant-upload input[type=file]').setInputFiles([
        { name: 'meeting.wav', mimeType: 'audio/wav', buffer: Buffer.from('RIFF0000WAVE') },
    ])
    await page.getByRole('button', { name: 'Start' }).click()
    await expect(page.getByText('轉錄完成')).toBeVisible()
    await page.getByRole('link', { name: 'Result Viewer' }).click()

    await page.getByRole('link', { name: '校正' }).click()
    await expect(page).toHaveURL(/\/correction\/task-1$/)
    await expect(row(page, '大家早安')).toBeVisible()

    await page.goBack()
    await expect(page.getByText('1 completed')).toBeVisible()
})
