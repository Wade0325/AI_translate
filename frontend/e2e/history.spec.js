import { test, expect, download } from './support/test.js'
import { TRANSCRIPTS, reply } from './support/backend.js'

/** 校正後版本的 SRT：第一句改過文字。 */
const CORRECTED_SRT = TRANSCRIPTS.srt.replace('測試的第一句', '校正過的第一句')

const RECORDS = [
    {
        task_uuid: 'task-1', request_timestamp: '2026-10-20T10:00:00', completed_at: '2026-10-20T10:03:00',
        status: 'COMPLETED', original_filename: 'meeting.wav', audio_duration_seconds: 300.0,
        model_used: 'moss-align', source_language: 'zh-TW', total_tokens: 0, cost: 0.0,
        error_code: null, error_message: null, is_batch: false, session_id: 'session-1', file_uid: 'file-1',
        service_tier_used: 'standard', tail_loss_from_seconds: null, correctable: true, has_corrections: false,
    },
    {
        task_uuid: 'task-2', request_timestamp: '2026-10-21T09:00:00', completed_at: null,
        status: 'FAILED', original_filename: 'interview.mp3', audio_duration_seconds: null,
        model_used: 'gemini-3.5-flash', source_language: 'ja-JP', total_tokens: 1200, cost: 0.0042,
        error_code: 'GEMINI_UNAVAILABLE', error_message: '503 UNAVAILABLE: The model is overloaded.',
        is_batch: false, session_id: 'session-2', file_uid: 'file-2',
        service_tier_used: 'standard', tail_loss_from_seconds: null, correctable: false, has_corrections: false,
    },
]

const HISTORY_ROUTES = {
    'GET /history': { items: RECORDS, total: 2, page: 1, page_size: 10, total_pages: 1 },
    'GET /history/stats': {
        total_tasks: 2, completed_tasks: 1, failed_tasks: 1, success_rate: 50.0, total_cost: 0.0042,
        total_tokens: 1200, total_audio_duration_seconds: 300.0, avg_processing_time_seconds: 180.0,
    },
}

/** 任務紀錄表格裡檔名是 filename 的那一列。 */
const recordRow = (page, filename) => page.getByRole('row', { name: filename })

/** 已完成那一列的下載選單：滑過下載按鈕才會展開。 */
async function openDownloadMenu(page, filename) {
    await recordRow(page, filename).getByRole('button', { name: 'download' }).hover()
}

/** 展開的下載選單（側欄的導覽也是 menu，要分開）。 */
const downloadMenu = (page) => page.locator('.ant-dropdown-menu').filter({ visible: true })

test('列出任務紀錄，從已完成的那一列下載 SRT', async ({ page, mockBackend }) => {
    const backend = await mockBackend({
        routes: { ...HISTORY_ROUTES, 'GET /history/task-1/download/srt': TRANSCRIPTS.srt },
    })
    await page.goto('/history')

    await expect(recordRow(page, 'meeting.wav')).toContainText('完成')
    await expect(recordRow(page, 'interview.mp3')).toContainText('失敗')
    await expect(page.getByText('50.0%')).toBeVisible()
    expect(backend.requests.find((r) => r.path === '/history').query).toEqual({ page: '1', page_size: '10' })
    // 失敗的任務沒有轉錄結果，不能下載
    await expect(recordRow(page, 'interview.mp3').getByRole('button', { name: 'download' })).toHaveCount(0)

    await openDownloadMenu(page, 'meeting.wav')
    expect(await download(page, () => page.getByRole('menuitem', { name: 'SRT' }).click()))
        .toEqual({ filename: 'meeting.srt', text: TRANSCRIPTS.srt })
})

test('有校正的任務：下載選單分成校正後版本與原始轉錄，原始轉錄的檔名多一段 .original（#346）', async ({ page, mockBackend }) => {
    const corrected = { ...RECORDS[0], has_corrections: true }
    const backend = await mockBackend({
        routes: {
            ...HISTORY_ROUTES,
            'GET /history': { items: [corrected, RECORDS[1]], total: 2, page: 1, page_size: 10, total_pages: 1 },
            // 形狀照後端：version=original 給原始轉錄，其他（預設）給校正後版本
            'GET /history/task-1/download/srt': ({ query }) => (
                query.version === 'original' ? TRANSCRIPTS.srt : CORRECTED_SRT),
        },
    })
    await page.goto('/history')

    await openDownloadMenu(page, 'meeting.wav')
    const menu = downloadMenu(page)
    await expect(menu.getByText('校正後版本')).toBeVisible()
    await expect(menu.getByText('原始轉錄')).toBeVisible()
    // 兩組都有四種輸出格式
    await expect(menu.getByRole('menuitem')).toHaveText(['LRC', 'SRT', 'VTT', 'TXT', 'LRC', 'SRT', 'VTT', 'TXT'])

    expect(await download(page, () => menu.getByRole('menuitem', { name: 'SRT' }).first().click()))
        .toEqual({ filename: 'meeting.srt', text: CORRECTED_SRT })
    await expect(page.getByText('已下載 SRT 檔')).toBeVisible()

    await openDownloadMenu(page, 'meeting.wav')
    expect(await download(page, () => menu.getByRole('menuitem', { name: 'SRT' }).last().click()))
        .toEqual({ filename: 'meeting.original.srt', text: TRANSCRIPTS.srt })
    await expect(page.getByText('已下載原始轉錄的 SRT 檔')).toBeVisible()

    expect(backend.requests.filter((r) => r.path === '/history/task-1/download/srt').map((r) => r.query))
        .toEqual([{ version: 'corrected' }, { version: 'original' }])
})

test('沒有校正的任務：下載選單和以前一樣只有四種輸出格式，沒有原始轉錄那一組（#346）', async ({ page, mockBackend }) => {
    await mockBackend({ routes: HISTORY_ROUTES })
    await page.goto('/history')

    await openDownloadMenu(page, 'meeting.wav')
    const menu = downloadMenu(page)
    await expect(menu.getByRole('menuitem')).toHaveText(['LRC', 'SRT', 'VTT', 'TXT'])
    await expect(menu.getByText('原始轉錄')).toHaveCount(0)
    await expect(menu.getByText('校正後版本')).toHaveCount(0)
})

test('失敗的那一列在檔名下面寫出原因，滑過去看下一步與錯誤碼（#24 門檻 4）', async ({ page, mockBackend }) => {
    await mockBackend({ routes: HISTORY_ROUTES })
    await page.goto('/history')

    const reason = recordRow(page, 'interview.mp3').getByText('Gemini 暫時無法服務')
    await expect(reason).toBeVisible()
    // 完成的那一列沒有失敗原因
    await expect(recordRow(page, 'meeting.wav').getByText('Gemini 暫時無法服務')).toHaveCount(0)

    await reason.hover()
    const tooltip = page.getByRole('tooltip')
    await expect(tooltip).toContainText('已經自動重試過幾次')
    await expect(tooltip).toContainText('錯誤碼 GEMINI_UNAVAILABLE · 503 UNAVAILABLE: The model is overloaded.')
})

test('可能掉尾的完成任務在檔名下面寫出從哪裡起可能沒有轉錄到，滑過去看下一步（#257）', async ({ page, mockBackend }) => {
    // 批次的結果只在這裡看得到：轉錄頁的檔案卡沒有批次的轉錄結果
    const stopped = { ...RECORDS[0], tail_loss_from_seconds: 3000.4, is_batch: true }
    await mockBackend({
        routes: {
            ...HISTORY_ROUTES,
            'GET /history': { items: [stopped, RECORDS[1]], total: 2, page: 1, page_size: 10, total_pages: 1 },
        },
    })
    await page.goto('/history')

    const hint = recordRow(page, 'meeting.wav').getByText('從 50:00 起可能沒有轉錄到')
    await expect(hint).toBeVisible()
    // 失敗的那一列沒有轉錄結果，也就沒有掉尾的提示
    await expect(recordRow(page, 'interview.mp3').getByText(/可能沒有轉錄到/)).toHaveCount(0)

    await hint.hover()
    await expect(page.getByRole('tooltip')).toContainText('只是音樂或環境音就不必理會')
})

test('完成的任務沒有掉尾時，不寫可能沒有轉錄到（#257）', async ({ page, mockBackend }) => {
    await mockBackend({ routes: HISTORY_ROUTES })
    await page.goto('/history')

    await expect(recordRow(page, 'meeting.wav')).toContainText('完成')
    await expect(page.getByText(/可能沒有轉錄到/)).toHaveCount(0)
})

test('成功率照後端算的數字顯示：處理中與已取消的任務不算進分母', async ({ page, mockBackend }) => {
    await mockBackend({
        routes: {
            ...HISTORY_ROUTES,
            // 4 筆裡 1 完成、1 失敗，另外 2 筆處理中或已取消：成功率是 1 /（1＋1）
            'GET /history/stats': { ...HISTORY_ROUTES['GET /history/stats'], total_tasks: 4, success_rate: 50.0 },
        },
    })
    await page.goto('/history')

    await expect(page.getByText('50.0%')).toBeVisible()
    await expect(page.getByText('1 完成 / 1 失敗')).toBeVisible()
})

test('下載失敗時顯示後端的原因', async ({ page, mockBackend }) => {
    await mockBackend({
        routes: {
            ...HISTORY_ROUTES,
            'GET /history/task-1/download/srt': reply(404, { detail: '找不到這個任務的轉錄結果' }),
        },
    })
    await page.goto('/history')

    await openDownloadMenu(page, 'meeting.wav')
    await page.getByRole('menuitem', { name: 'SRT' }).click()

    await expect(page.getByText('找不到這個任務的轉錄結果')).toBeVisible()
})
