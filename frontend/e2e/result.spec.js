import { readFile } from 'node:fs/promises'
import JSZip from 'jszip'
import { test, expect, download } from './support/test.js'
import { TRANSCRIPTS, transcriptionMessages } from './support/backend.js'

// 內容不重要：音檔只經過假後端，不會被解碼。前兩個主檔名相同，打包時換成 .srt 會撞名
const audio = (name) => ({ name, mimeType: 'audio/wav', buffer: Buffer.from('RIFF0000WAVE') })
const AUDIO = [audio('a.mp3'), audio('a.wav'), audio('b.wav'), audio('c.wav')]

/** 各音檔完成時帶的轉錄結果：b.wav 沒有 SRT；c.wav 沒有轉錄結果（和批次模式完成的檔案一樣，要到 History 頁面下載） */
const TRANSCRIPTS_OF = {
    'a.mp3': { ...TRANSCRIPTS, srt: TRANSCRIPTS.srt.replaceAll('測試', 'a.mp3 ') },
    'a.wav': { ...TRANSCRIPTS, srt: TRANSCRIPTS.srt.replaceAll('測試', 'a.wav ') },
    'b.wav': { ...TRANSCRIPTS, srt: '' },
    'c.wav': null,
}

/** 用本機轉錄完四個音檔，換到結果頁。 */
async function transcribeAll(page, mockBackend) {
    await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
        transcribe: async (request, send) => {
            const { processing, completed } = transcriptionMessages(request)
            send(processing)
            send({ ...completed, result: { ...completed.result, transcripts: TRANSCRIPTS_OF[request.original_filename] } })
        },
    })
    await page.goto('/transcribe')
    await page.getByLabel('供應商').selectOption('local')
    await page.locator('.ant-upload input[type=file]').setInputFiles(AUDIO)
    await page.getByRole('button', { name: 'Start' }).click()
    await expect(page.getByText('轉錄完成')).toHaveCount(AUDIO.length)

    await page.getByRole('link', { name: 'Result Viewer' }).click()
    await expect(page).toHaveURL(/\/result$/)
    await expect(page.getByText(`${AUDIO.length} completed`)).toBeVisible()
}

/** 點下載選單裡的一種格式，回傳下載的 ZIP 的檔名與裡面每個檔案的內容。 */
async function downloadZip(page, action) {
    const [file] = await Promise.all([page.waitForEvent('download'), action()])
    const zip = await JSZip.loadAsync(await readFile(await file.path()))
    const entries = {}
    for (const name of Object.keys(zip.files)) entries[name] = await zip.file(name).async('string')
    return { filename: file.suggestedFilename(), entries }
}

/** 第 n 個檔案卡（照上傳的順序）的下載選單，選一種格式；等選單收起來，下一次才不會點到正在收的那個。 */
async function pickFileFormat(page, n, label) {
    await page.getByRole('button', { name: 'Download', exact: true }).nth(n).hover()
    await page.getByText(label).filter({ visible: true }).click()
    await page.mouse.move(0, 0)
    await expect(page.locator('.ant-dropdown-menu').filter({ visible: true })).toHaveCount(0)
}

test('打包下載：主檔名相同的音檔各自一個檔，沒內容的不打包，訊息照實際打包的數目說', async ({ page, mockBackend }) => {
    await transcribeAll(page, mockBackend)

    await page.getByRole('button', { name: /Download All/ }).hover()
    const zip = await downloadZip(page, () => page.getByText('SRT (All files)').click())

    // 日期是本地日期（playwright.config.js 固定台北時間）
    expect(zip.filename).toMatch(/^transcripts_SRT_\d{4}-\d{2}-\d{2}\.zip$/)
    expect(zip.entries).toEqual({
        'a.mp3.srt': TRANSCRIPTS_OF['a.mp3'].srt,
        'a.wav.srt': TRANSCRIPTS_OF['a.wav'].srt,
    })
    await expect(page.getByText(
        '已下載 2 個 SRT 檔的壓縮包；b.wav 沒有 SRT 內容；c.wav 的轉錄結果請到 History 頁面下載',
    )).toBeVisible()
})

test('單檔下載：沒有內容時提示原因，不存出內容是 undefined 或空白的檔', async ({ page, mockBackend }) => {
    await transcribeAll(page, mockBackend)
    const downloads = []
    page.on('download', (d) => downloads.push(d.suggestedFilename()))

    // 有內容的照常下載
    expect(await download(page, () => pickFileFormat(page, 0, 'SRT (Subtitles)')))
        .toEqual({ filename: 'a.srt', text: TRANSCRIPTS_OF['a.mp3'].srt })

    await pickFileFormat(page, 2, 'SRT (Subtitles)')
    await expect(page.getByText('b.wav 沒有 SRT 內容')).toBeVisible()

    await pickFileFormat(page, 3, 'TXT (Plain Text)')
    await expect(page.getByText('c.wav 的轉錄結果請到 History 頁面下載')).toBeVisible()

    expect(downloads).toEqual(['a.srt'])
})
