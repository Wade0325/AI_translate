import { test, expect, download } from './support/test.js'
import { TRANSCRIPTS, reply } from './support/backend.js'

const RECORDS = [
    {
        task_uuid: 'task-1', request_timestamp: '2026-10-20T10:00:00', completed_at: '2026-10-20T10:03:00',
        status: 'COMPLETED', original_filename: 'meeting.wav', audio_duration_seconds: 300.0,
        model_used: 'moss-align', source_language: 'zh-TW', total_tokens: 0, cost: 0.0,
        error_message: null, is_batch: false, session_id: 'session-1', file_uid: 'file-1',
        service_tier_used: 'standard',
    },
    {
        task_uuid: 'task-2', request_timestamp: '2026-10-21T09:00:00', completed_at: null,
        status: 'FAILED', original_filename: 'interview.mp3', audio_duration_seconds: null,
        model_used: 'gemini-3.5-flash', source_language: 'ja-JP', total_tokens: 1200, cost: 0.0042,
        error_message: '請求逾時', is_batch: false, session_id: 'session-2', file_uid: 'file-2',
        service_tier_used: 'standard',
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

test('列出任務紀錄，從已完成的那一列下載 SRT', async ({ page, mockBackend }) => {
    const backend = await mockBackend({
        routes: { ...HISTORY_ROUTES, 'GET /history/task-1/download/srt': TRANSCRIPTS.srt },
    })
    await page.goto('/history')

    await expect(recordRow(page, 'meeting.wav')).toContainText('完成')
    await expect(recordRow(page, 'interview.mp3')).toContainText('失敗')
    await expect(page.getByText('60.0%')).toBeVisible()
    expect(backend.requests.find((r) => r.path === '/history').query).toEqual({ page: '1', page_size: '10' })
    // 失敗的任務沒有轉錄結果，不能下載
    await expect(recordRow(page, 'interview.mp3').getByRole('button', { name: 'download' })).toHaveCount(0)

    await openDownloadMenu(page, 'meeting.wav')
    expect(await download(page, () => page.getByRole('menuitem', { name: 'SRT' }).click()))
        .toEqual({ filename: 'meeting.srt', text: TRANSCRIPTS.srt })
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
