import { test, expect, downloadedText } from './support/test.js'
import { TRANSCRIPTS } from './support/backend.js'

// 內容不重要：音檔只經過假後端，不會被解碼
const AUDIO = { name: 'meeting.wav', mimeType: 'audio/wav', buffer: Buffer.from('RIFF0000WAVE') }

async function addAudio(page) {
    await page.locator('.ant-upload input[type=file]').setInputFiles(AUDIO)
    await expect(page.getByText(AUDIO.name)).toBeVisible()
}

test('選本機送出一個檔案，完成後到結果頁下載 SRT', async ({ page, mockBackend }) => {
    const backend = await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
    })
    await page.goto('/transcribe')

    await page.getByLabel('供應商').selectOption('local')
    await expect(page.getByLabel('模型')).toHaveValue('moss-align')
    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    await expect(page.getByText('轉錄完成')).toBeVisible()
    // 先上傳，再用上傳拿到的伺服器檔名開任務；本機不吃提示詞與使用者文稿，送出時不帶
    expect(backend.requests.filter((r) => r.path === '/upload')).toHaveLength(1)
    expect(backend.transcriptions).toEqual([
        expect.objectContaining({
            filename: 'meeting_1.wav',
            original_filename: AUDIO.name,
            provider: 'local',
            model: 'moss-align',
            prompt: null,
            original_text: null,
        }),
    ])

    // 從側欄換頁：轉錄頁的檔案清單只在這次瀏覽裡，重新載入就沒了
    await page.getByRole('link', { name: 'Result Viewer' }).click()
    await expect(page).toHaveURL(/\/result$/)
    await expect(page.getByText(AUDIO.name)).toBeVisible()

    await page.getByRole('button', { name: 'Download', exact: true }).hover()
    const downloading = page.waitForEvent('download')
    await page.getByText('SRT (Subtitles)').click()
    const download = await downloading
    expect(download.suggestedFilename()).toBe('meeting.srt')
    expect(await downloadedText(download)).toBe(TRANSCRIPTS.srt)
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
    // 失敗的檔案可以再送一次
    await expect(page.getByRole('button', { name: 'Start' })).toBeEnabled()
})
