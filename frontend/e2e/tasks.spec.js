import { test, expect } from './support/test.js'

/** GET /history/active 的一筆：24 小時內的單檔任務，形狀照後端的 HistoryLogResponse。 */
const singleTask = (fields) => ({
    task_uuid: 'task-1', request_timestamp: '2026-10-31T10:00:00', completed_at: '2026-10-31T10:01:00',
    status: 'FAILED', original_filename: 'meeting.wav', audio_duration_seconds: null,
    model_used: 'gemini-3.5-flash', source_language: 'zh-TW', total_tokens: 0, cost: 0.0,
    error_code: null, error_message: null, is_batch: false, session_id: 'session-1', file_uid: 'file-1',
    service_tier_used: 'standard', tail_loss_from_seconds: null,
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

test('完成的單檔任務可能掉尾時，任務頁寫出從哪裡起可能沒有轉錄到（#257）', async ({ page, mockBackend }) => {
    await mockBackend({
        routes: {
            'GET /history/active': [
                singleTask({ status: 'COMPLETED', total_tokens: 1200, cost: 0.01, tail_loss_from_seconds: 3000.4 }),
                singleTask({
                    task_uuid: 'task-2', file_uid: 'file-2', original_filename: 'whole.wav',
                    status: 'COMPLETED', total_tokens: 900, cost: 0.01, tail_loss_from_seconds: null,
                }),
            ],
        },
    })
    await page.goto('/tasks')

    const hint = page.getByText('從 50:00 起可能沒有轉錄到')
    await expect(hint).toHaveCount(1)
    await hint.hover()
    await expect(page.getByRole('tooltip')).toContainText('請聽一下原音檔的這一段')
})

test('取回的批次結果可能掉尾時，檔案下面寫出從哪裡起可能沒有轉錄到（#257）', async ({ page, mockBackend }) => {
    const completed = (seconds) => ({ transcripts: { srt: '1\n', vtt: '', lrc: '', txt: '' }, tail_loss_from_seconds: seconds })
    await mockBackend({
        routes: {
            'GET /batch/tasks': [{
                batch_id: 'batch-1', status: 'COMPLETED', file_count: 2, is_alive: false,
                created_at: '2026-10-31T10:00:00', elapsed_seconds: 600, session_id: 'session-1', recoverable: false,
                files: [
                    { file_uid: 'a', original_filename: 'stopped.wav' },
                    { file_uid: 'b', original_filename: 'whole.wav' },
                ],
            }],
            'POST /batch/batch-1/recover': {
                batch_id: 'batch-1',
                files: [
                    { file_uid: 'a', original_filename: 'stopped.wav', status: 'COMPLETED', result: completed(3000.4) },
                    { file_uid: 'b', original_filename: 'whole.wav', status: 'COMPLETED', result: completed(null) },
                ],
            },
        },
    })
    await page.goto('/tasks')
    await page.getByRole('button', { name: '取回結果' }).click()

    await expect(page.getByText('stopped.wav')).toBeVisible()
    await expect(page.getByText('whole.wav')).toBeVisible()
    const hint = page.getByText('從 50:00 起可能沒有轉錄到')
    await expect(hint).toHaveCount(1)
    await hint.hover()
    await expect(page.getByRole('tooltip')).toContainText('請聽一下原音檔的這一段')
})
