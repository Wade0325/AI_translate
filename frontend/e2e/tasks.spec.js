import { test, expect } from './support/test.js'

/** GET /history/active 的一筆：24 小時內的單檔任務，形狀照後端的 HistoryLogResponse。 */
const singleTask = (fields) => ({
    task_uuid: 'task-1', request_timestamp: '2026-10-31T10:00:00', completed_at: '2026-10-31T10:01:00',
    status: 'FAILED', original_filename: 'meeting.wav', audio_duration_seconds: null,
    model_used: 'gemini-3.5-flash', source_language: 'zh-TW', total_tokens: 0, cost: 0.0,
    error_code: null, error_message: null, is_batch: false, session_id: 'session-1', file_uid: 'file-1',
    service_tier_used: 'standard',
    ...fields,
})

test('失敗的單檔任務在任務頁寫出原因，滑過去看下一步與錯誤碼（#24 門檻 4）', async ({ page, mockBackend }) => {
    await mockBackend({
        routes: {
            'GET /history/active': [singleTask({
                error_code: 'GEMINI_QUOTA', error_message: '429 RESOURCE_EXHAUSTED: Resource has been exhausted.',
            })],
        },
    })
    await page.goto('/tasks')

    const reason = page.getByText('Gemini 的用量達到上限')
    await expect(reason).toBeVisible()

    await reason.hover()
    const tooltip = page.getByRole('tooltip')
    await expect(tooltip).toContainText('等幾分鐘再重新轉錄')
    await expect(tooltip).toContainText('錯誤碼 GEMINI_QUOTA · 429 RESOURCE_EXHAUSTED: Resource has been exhausted.')
})

test('這個版本之前失敗、沒有錯誤碼的任務，照紀錄的原因顯示', async ({ page, mockBackend }) => {
    await mockBackend({
        routes: { 'GET /history/active': [singleTask({ error_message: '轉錄失敗: [[分段 1 失敗]]' })] },
    })
    await page.goto('/tasks')

    await expect(page.getByText('轉錄失敗: [[分段 1 失敗]]')).toBeVisible()
})
