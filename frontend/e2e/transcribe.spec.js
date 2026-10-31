import { test, expect, download } from './support/test.js'
import {
    GEMINI_UPLOAD_NOTICE, PROVIDERS, QUEUED_TEXT, SUBMISSION_FAILED_TEXT, TRANSCRIPTS, UPLOAD_LIMITS, readiness,
    reply, transcriptionMessages,
} from './support/backend.js'

// 內容不重要：音檔只經過假後端，不會被解碼
const AUDIO = { name: 'meeting.wav', mimeType: 'audio/wav', buffer: Buffer.from('RIFF0000WAVE') }

async function addAudio(page) {
    await page.locator('.ant-upload input[type=file]').setInputFiles(AUDIO)
    await expect(page.getByText(AUDIO.name)).toBeVisible()
}

test('處理模式預設是標準；選 Gemini 時仍可選 Flex 與批次（#18）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')

    await expect(page.getByLabel('處理模式')).toHaveValue('standard')
    await page.getByLabel('供應商').selectOption('google')
    await expect(page.getByLabel('處理模式')).toHaveValue('standard')
    await expect(page.getByRole('option', { name: /^Flex/ })).toBeEnabled()
    await expect(page.getByRole('option', { name: /^批次/ })).toBeEnabled()
})

test('選 Gemini 時說明音檔會上傳到 Google 並連到條款原文；選本機時不顯示（#231 Q6）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')

    await expect(page.getByLabel('供應商')).toHaveValue('local')
    await expect(page.getByText(/會上傳到 Google/)).toHaveCount(0)
    await expect(page.getByRole('link', { name: '條款原文' })).toHaveCount(0)

    await page.getByLabel('供應商').selectOption('google')

    await expect(page.getByText(/音檔與提示詞會上傳到 Google/)).toBeVisible()
    await expect(page.getByRole('link', { name: '條款原文' })).toHaveAttribute('href', GEMINI_UPLOAD_NOTICE.terms_url)
})

test('費用估算只給按 token 計費的模型：選本機時只顯示檔案數與大小（#18）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')
    await addAudio(page)

    // Gemini 按 token 計費：估算時長、處理時間與費用
    await page.getByLabel('供應商').selectOption('google')
    await expect(page.getByText('est.')).toBeVisible()

    await page.getByLabel('供應商').selectOption('local')

    await expect(page.getByText('est.')).toHaveCount(0)
    await expect(page.getByText(/~\d+ min/)).toHaveCount(0)
    await expect(page.getByText(/^1 files$/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start' })).toBeEnabled()
})

test('語言選單分官方支援與未驗證，沒有簡體中文；選了未驗證的語言，選單與檔案卡都標未驗證（ADR-0002、#14 Q2）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')
    await addAudio(page)

    // 選單是虛擬清單，只畫看得到的前幾列：Auto Detect、官方支援兩種、未驗證開頭的幾種
    await page.getByRole('combobox', { name: 'Language', exact: true }).click()
    const menu = page.locator('.ant-select-dropdown:visible')
    await expect(menu.locator('.ant-select-item').first()).toHaveText('Auto Detect')
    await expect(menu.locator('.ant-select-item-group')).toHaveText(['官方支援', '未驗證'])
    await expect(menu.locator('.ant-select-item').nth(1)).toHaveText('官方支援')
    await expect(menu.locator('.ant-select-item').nth(2)).toHaveText('Japanese')
    await expect(menu.locator('.ant-select-item').nth(3)).toHaveText('Chinese (Traditional)')
    await expect(menu.locator('.ant-select-item').nth(4)).toHaveText('未驗證')
    await expect(menu.getByText('Chinese (Simplified)')).toHaveCount(0)

    // 選了未驗證的語言：全域選單收起來的值與檔案卡的標籤都標出來，每檔設定的選單也一樣
    // （antd 另有一個看不到的無障礙區塊也寫選到的值，只數看得到的）
    const shown = (text) => page.getByText(text, { exact: true }).filter({ visible: true })
    await menu.locator('.ant-select-item-option[title="French"]').click()
    await expect(shown('French（未驗證）')).toHaveCount(2)
    await page.getByRole('button', { name: '每檔設定' }).click()
    await expect(shown('French（未驗證）')).toHaveCount(3)

    // 選回官方支援語言就不標。再打開時清單捲在選到的 French，先捲回頂端才畫得出 Japanese
    await page.getByRole('combobox', { name: 'Language', exact: true }).click()
    await menu.locator('.rc-virtual-list-holder').evaluate((el) => { el.scrollTop = 0 })
    await menu.locator('.ant-select-item-option[title="Japanese"]').click()
    await page.getByRole('button', { name: /Apply to All/ }).click()
    await expect(page.getByText(/未驗證/).filter({ visible: true })).toHaveCount(0)
    await expect(shown('Japanese')).toHaveCount(3)
})

test('Multi-Speaker 只有開關：沒有人數滑桿，也沒有 Timestamps 開關（#13 Q1、Q2）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')
    await addAudio(page)
    await expect(page.getByText('Single', { exact: true })).toBeVisible()

    // 全域與每檔設定都只有開關；打開也不會冒出人數滑桿，檔案卡的標籤只寫開或關
    await page.getByRole('switch', { name: 'Multi-Speaker', exact: true }).click()
    await page.getByRole('button', { name: '每檔設定' }).click()
    await expect(page.getByRole('switch', { name: '這個檔案的 Multi-Speaker' })).toBeChecked()

    await expect(page.getByText('Multi-speaker', { exact: true })).toBeVisible()
    await expect(page.getByRole('slider')).toHaveCount(0)
    await expect(page.getByText(/^(No )?timestamps$/i)).toHaveCount(0)
})

test('Multi-Speaker 預設關、記住上次：重新開頁還是上次的開關，送出的檔案照它（#13 Q1）', async ({ page, mockBackend }) => {
    const backend = await mockBackend({ routes: { 'POST /upload': { filename: 'meeting_1.wav' } } })
    await page.goto('/transcribe')
    const multiSpeaker = page.getByRole('switch', { name: 'Multi-Speaker', exact: true })

    // 第一次開頁是關；沒動過就不寫進儲存空間
    await expect(multiSpeaker).not.toBeChecked()
    expect(await page.evaluate(() => localStorage.getItem('ai_translate_last_multi_speaker'))).toBeNull()

    await multiSpeaker.click()
    await page.reload()

    await expect(multiSpeaker).toBeChecked()
    await addAudio(page)
    await expect(page.getByText('Multi-speaker', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Start' }).click()
    await expect(page.getByText('轉錄完成')).toBeVisible()
    expect(backend.transcriptionRequests).toEqual([expect.objectContaining({ multi_speaker: true })])

    // 關掉也記住
    await multiSpeaker.click()
    await page.reload()
    await expect(multiSpeaker).not.toBeChecked()
    expect(await page.evaluate(() => localStorage.getItem('ai_translate_last_multi_speaker'))).toBe('false')
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
    // 說話者人數是後端從轉錄結果算的，不是轉錄頁填的人數（#13 Q1）
    await expect(page.getByText('2 speaker(s)')).toBeVisible()

    await page.getByRole('button', { name: 'Download', exact: true }).hover()
    expect(await download(page, () => page.getByText('SRT (Subtitles)').click()))
        .toEqual({ filename: 'meeting.srt', text: TRANSCRIPTS.srt })
})

test('任務失敗時，檔案卡寫出原因、下一步與錯誤碼，可以前往設定頁處理（#24 門檻 4）', async ({ page, mockBackend }) => {
    const detail = '403 PERMISSION_DENIED: Your API key was reported as leaked.'
    await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
        transcribe: async (request, send) => {
            // 形狀照後端任務失敗時的狀態廣播：錯誤碼與細節和任務紀錄同名
            send({
                task_uuid: 'task-1', status_code: 'FAILED', status_text: `任務失敗: ${detail}`,
                file_uid: request.file_uid, error_code: 'GEMINI_KEY_REJECTED', error_message: detail,
            })
        },
    })
    await page.goto('/transcribe')

    await page.getByLabel('供應商').selectOption('google')
    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    const notice = page.getByTestId('failure-notice')
    await expect(notice.getByText('Gemini 不接受這把 API 金鑰')).toBeVisible()
    await expect(notice.getByText(/到設定頁的 Gemini 換一把可用的 API Key/)).toBeVisible()
    await expect(notice.getByText(`錯誤碼 GEMINI_KEY_REJECTED · ${detail}`)).toBeVisible()
    await expect(page.getByText('1 個任務失敗')).toBeVisible()
    // 失敗的檔案可以重新轉錄
    await expect(page.getByRole('button', { name: 'Start' })).toBeEnabled()

    await notice.getByRole('link', { name: '前往設定頁' }).click()
    await expect(page).toHaveURL(/\/settings$/)
})

test('失敗訊息沒帶錯誤碼時，檔案卡照狀態文字寫出原因', async ({ page, mockBackend }) => {
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

    await expect(page.getByTestId('failure-notice').getByText(reason)).toBeVisible()
    await expect(page.getByText('1 個任務失敗')).toBeVisible()
})

test('上傳被拒絕時，檔案卡寫出伺服器說的原因（#24 門檻 4）', async ({ page, mockBackend }) => {
    const detail = '檔案是空的（0 位元組），請確認檔案沒有損壞'
    await mockBackend({ routes: { 'POST /upload': reply(400, { detail }) } })
    await page.goto('/transcribe')

    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    const notice = page.getByTestId('failure-notice')
    await expect(notice.getByText('檔案沒有上傳成功')).toBeVisible()
    await expect(notice.getByText(`錯誤碼 UPLOAD_FAILED · ${detail}`)).toBeVisible()
})

const SUPPORTED = '（音檔可以用 MP3、WAV、M4A、FLAC；影片可以用 MP4、MOV、MKV、WebM、AVI、WMV、M4V、3GP、MPG、MPEG）'

test('上傳區照伺服器的清單列出音檔與影片格式、上限，說明影片只轉錄聲音（#258）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')

    await expect(page.getByText('音檔 MP3、WAV、M4A、FLAC，影片 MP4、MOV、MKV、WebM、AVI、WMV、M4V、3GP、MPG、MPEG（上限 2 GB）')).toBeVisible()
    await expect(page.getByText('影片會先在這台電腦抽出聲音，只轉錄聲音，畫面不會送出')).toBeVisible()
    await expect(page.locator('.ant-upload input[type=file]')).toHaveAttribute(
        'accept', '.mp3,.wav,.m4a,.flac,.mp4,.mov,.mkv,.webm,.avi,.wmv,.m4v,.3gp,.mpg,.mpeg')
})

test('影片可以直接加入並轉錄；瀏覽器沒給 MIME 類型也照副檔名收（#258）', async ({ page, mockBackend }) => {
    const backend = await mockBackend({ routes: { 'POST /upload': { filename: 'meeting_1.flac' } } })
    await page.goto('/transcribe')

    await page.locator('.ant-upload input[type=file]').setInputFiles([
        { name: 'meeting.mp4', mimeType: 'video/mp4', buffer: Buffer.from('ftypisom') },
        { name: 'interview.M4A', mimeType: '', buffer: Buffer.from('ftypM4A ') },
    ])
    await expect(page.getByText('meeting.mp4')).toBeVisible()
    await expect(page.getByText('interview.M4A')).toBeVisible()
    await page.getByRole('button', { name: 'Start' }).click()

    await expect(page.getByText('轉錄完成')).toHaveCount(2)
    expect(backend.requests.filter((r) => r.path === '/upload')).toHaveLength(2)
})

test('加入伺服器不收的格式時，當場說明不支援並列出可以用的格式', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')

    await page.locator('.ant-upload input[type=file]').setInputFiles({
        name: 'voice.ogg', mimeType: 'audio/ogg', buffer: Buffer.from('OggS'),
    })

    await expect(page.getByText(`不支援這種格式：voice.ogg${SUPPORTED}`)).toBeVisible()
    await expect(page.getByText('voice.ogg', { exact: true })).toHaveCount(0)
})

test('拖進不收的格式時也說明原因，不會默默沒反應（#258）', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.goto('/transcribe')

    const dropped = await page.evaluateHandle(() => {
        const transfer = new DataTransfer()
        transfer.items.add(new File(['%PDF-1.4'], 'slides.pdf', { type: 'application/pdf' }))
        return transfer
    })
    await page.locator('.ant-upload-drag .ant-upload-btn').dispatchEvent('drop', { dataTransfer: dropped })

    await expect(page.getByText(`不支援這種格式：slides.pdf${SUPPORTED}`)).toBeVisible()
})

test('超過伺服器的大小上限時，當場說明檔案太大（#258）', async ({ page, mockBackend }) => {
    // 上限改成 1 MB：測試裡不必做出 2 GB 的檔案
    await mockBackend({ routes: { 'GET /upload/limits': { ...UPLOAD_LIMITS, max_bytes: 1024 ** 2 } } })
    await page.goto('/transcribe')

    await page.locator('.ant-upload input[type=file]').setInputFiles({
        name: 'long.wav', mimeType: 'audio/wav', buffer: Buffer.alloc(1.5 * 1024 ** 2),
    })

    await expect(page.getByText('檔案太大：long.wav（1.5 MB，上限 1 MB）')).toBeVisible()
    await expect(page.getByText('long.wav', { exact: true })).toHaveCount(0)
})

test('讀不到格式清單時照樣可以加入檔案，交給伺服器上傳時檢查（#258）', async ({ page, mockBackend }) => {
    const detail = '不支援這種檔案格式（.ogg）。可以上傳的音檔：MP3、WAV、M4A、FLAC；影片：MP4、MOV、MKV、WebM、AVI、WMV、M4V、3GP、MPG、MPEG'
    await mockBackend({
        routes: { 'GET /upload/limits': reply(500, { detail: 'Internal Server Error' }), 'POST /upload': reply(400, { detail }) },
    })
    await page.goto('/transcribe')

    await page.locator('.ant-upload input[type=file]').setInputFiles({
        name: 'voice.ogg', mimeType: 'audio/ogg', buffer: Buffer.from('OggS'),
    })
    await expect(page.getByText('voice.ogg')).toBeVisible()
    await page.getByRole('button', { name: 'Start' }).click()

    await expect(page.getByTestId('failure-notice').getByText(`錯誤碼 UPLOAD_FAILED · ${detail}`)).toBeVisible()
})

test('排在別的任務後面時，檔案卡顯示排隊中，輪到時接著顯示進度（#24 門檻 4）', async ({ page, mockBackend }) => {
    // 假後端送出排隊中之後先停住，等畫面上看到排隊中才開始
    let start
    const started = new Promise((resolve) => { start = resolve })
    await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
        transcribe: async (request, send) => {
            const { queued, processing, completed } = transcriptionMessages(request)
            send(queued)
            await started
            send(processing)
            send(completed)
        },
    })
    await page.goto('/transcribe')

    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    await expect(page.getByText(QUEUED_TEXT)).toBeVisible()
    start()
    await expect(page.getByText('轉錄完成')).toBeVisible()
})

test('伺服器還沒回應就關掉連線時，檔案卡顯示提交失敗，可以重新轉錄（#24 門檻 4）', async ({ page, mockBackend }) => {
    await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
        transcribe: async (request, send, close) => close(),
    })
    await page.goto('/transcribe')

    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    const notice = page.getByTestId('failure-notice')
    await expect(notice.getByText('任務沒有送出')).toBeVisible()
    await expect(notice.getByText('錯誤碼 SUBMIT_FAILED · 伺服器還沒回應，連線就中斷了')).toBeVisible()
    await expect(page.getByText('1 個任務失敗')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start' })).toBeEnabled()
})

/** 一個之後才會放行的關卡：open() 之前，等它的地方都停住。 */
function gate() {
    let open
    const opened = new Promise((resolve) => { open = resolve })
    return { opened, open }
}

test('排隊中之後連線斷了：檔案卡寫出連線中斷，不再停在排隊中；接回之後接著顯示進度與結果（#280）', async ({ page, mockBackend }) => {
    let messages
    const reconnected = gate()
    const backend = await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
        transcribe: async (request, send, close) => {
            messages = transcriptionMessages(request)
            send(messages.queued)
            close()
        },
        // 接回時任務還在排隊；等畫面上看到連線中斷，才回狀態、之後輪到它轉完
        reattach: async (task, send) => {
            await reconnected.opened
            send(messages.queued)
            send(messages.processing)
            send(messages.completed)
        },
    })
    await page.goto('/transcribe')

    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    const notice = page.getByTestId('connection-notice')
    await expect(notice.getByText('和伺服器的連線中斷了')).toBeVisible()
    await expect(notice.getByText(/連線中斷不會停止任務，不必重新轉錄/)).toBeVisible()
    await expect(page.getByText('連線中斷，正在重新連線...')).toBeVisible()
    await expect(page.getByText(QUEUED_TEXT)).toHaveCount(0)
    // 接回的是同一個檔案送出的同一個任務
    expect(backend.reattachments).toEqual([{ file_uid: messages.queued.file_uid, task_uuid: messages.queued.task_uuid }])

    reconnected.open()
    await expect(page.getByText('轉錄完成')).toBeVisible()
    await expect(notice).toHaveCount(0)
    await expect(page.getByText('1 個任務已完成')).toBeVisible()
})

test('斷線期間任務完成了：接回之後顯示結果，Result 頁看得到也下載得到（#280）', async ({ page, mockBackend }) => {
    let messages
    await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
        transcribe: async (request, send, close) => {
            messages = transcriptionMessages(request)
            send(messages.queued)
            send(messages.processing)
            close()
        },
        // 伺服器照任務紀錄補上結束時的宣告，和完成時廣播的一樣帶著結果
        reattach: async (task, send) => send({ ...messages.completed, status_text: '任務完成' }),
    })
    await page.goto('/transcribe')

    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    await expect(page.getByText('任務完成', { exact: true })).toBeVisible()
    await expect(page.getByTestId('connection-notice')).toHaveCount(0)
    await expect(page.getByText('1 個任務已完成')).toBeVisible()

    // 結果和連線沒斷時一樣：Result 頁看得到、下載得到
    await page.getByRole('link', { name: 'Result Viewer' }).click()
    await expect(page.getByText('2 speaker(s)')).toBeVisible()
    await page.getByRole('button', { name: 'Download', exact: true }).hover()
    expect(await download(page, () => page.getByText('SRT (Subtitles)').click()))
        .toEqual({ filename: 'meeting.srt', text: TRANSCRIPTS.srt })
})

test('連不上伺服器時說明要重新開啟 Mimiji；重新開啟之後自動接回，任務沒做完就顯示要重新轉錄（#280）', async ({ page, mockBackend }) => {
    let messages
    const restarted = gate()
    let attempts = 0
    await mockBackend({
        routes: { 'POST /upload': { filename: 'meeting_1.wav' } },
        transcribe: async (request, send, close) => {
            messages = transcriptionMessages(request)
            send(messages.queued)
            send(messages.processing)
            close()
        },
        reattach: async (task, send, close) => {
            attempts += 1
            // 第一次：伺服器已經停了，一則都沒回就斷了
            if (attempts === 1) return close()
            // 之後：重新開啟了。免安裝模式重新啟動時，伺服器上已經沒有這個任務
            await restarted.opened
            send({
                ...messages.processing,
                status_code: 'FAILED',
                status_text: '任務失敗: 伺服器上已經沒有這個任務：任務還沒做完，應用程式就關閉或重新啟動了',
                error_code: 'INTERRUPTED',
                error_message: '伺服器上已經沒有這個任務：任務還沒做完，應用程式就關閉或重新啟動了',
            })
        },
    })
    await page.goto('/transcribe')

    await addAudio(page)
    await page.getByRole('button', { name: 'Start' }).click()

    const notice = page.getByTestId('connection-notice')
    await expect(notice.getByText('連不上伺服器，Mimiji 可能已經關閉')).toBeVisible()
    await expect(notice.getByText(/請重新開啟 Mimiji（免安裝版是 AI_Translate.exe/)).toBeVisible()
    await expect(notice.getByRole('link', { name: '任務頁' })).toHaveAttribute('href', '/tasks')
    await expect(notice.getByRole('link', { name: '歷史紀錄' })).toHaveAttribute('href', '/history')
    await expect(page.getByText('連線中斷，連不上伺服器')).toBeVisible()
    await expect(page.getByText('轉錄中...')).toHaveCount(0)

    restarted.open()
    const failure = page.getByTestId('failure-notice')
    await expect(failure.getByText('應用程式在處理途中關閉了')).toBeVisible()
    await expect(failure.getByText('任務沒有做完，重新轉錄一次即可。')).toBeVisible()
    await expect(notice).toHaveCount(0)
    await expect(page.getByText('1 個任務失敗')).toBeVisible()
})

test('整批沒有送出時，這批的檔案都標成失敗（#24 門檻 4）', async ({ page, mockBackend }) => {
    const uploads = []
    await mockBackend({
        routes: { 'POST /upload': () => ({ filename: `upload_${uploads.push(1)}.wav` }) },
        batch: async (request, send, close) => {
            // 沒有 file_uid：整批沒有派送；原因只記在 log，所以只有錯誤碼沒有細節
            send({
                client_id: request.batch_id, status_code: 'FAILED', status_text: SUBMISSION_FAILED_TEXT,
                error_code: 'SUBMIT_FAILED', error_message: null,
            })
            close()
        },
    })
    await page.goto('/transcribe')
    await page.getByLabel('供應商').selectOption('google')
    await page.getByLabel('處理模式').selectOption('batch')

    await page.locator('.ant-upload input[type=file]').setInputFiles([
        AUDIO, { ...AUDIO, name: 'interview.wav' },
    ])
    await expect(page.getByText('interview.wav')).toBeVisible()
    await page.getByRole('button', { name: 'Start' }).click()

    await expect(page.getByTestId('failure-notice').getByText('任務沒有送出')).toHaveCount(2)
    await expect(page.getByText('錯誤碼 SUBMIT_FAILED', { exact: true })).toHaveCount(2)
    await expect(page.getByText('2 個任務失敗')).toBeVisible()
})

/** 選 Gemini 的批次模式，加入兩個檔案後按 Start。 */
async function startBatchOfTwo(page) {
    await page.goto('/transcribe')
    await page.getByLabel('供應商').selectOption('google')
    await page.getByLabel('處理模式').selectOption('batch')
    await page.locator('.ant-upload input[type=file]').setInputFiles([
        AUDIO, { ...AUDIO, name: 'interview.wav' },
    ])
    await expect(page.getByText('interview.wav')).toBeVisible()
    await page.getByRole('button', { name: 'Start' }).click()
}

/** 批次送出時每個檔案的進度（檔案層級，形狀照後端的廣播）。 */
const uploadProgress = (request) => request.files.map((file, index) => ({
    client_id: request.batch_id, batch_id: request.batch_id, task_uuid: `task-${file.file_uid}`,
    status_code: 'PROCESSING', status_text: `前處理與上傳 (${index + 1}/2): ${file.original_filename}`,
    file_uid: file.file_uid,
}))

test('批次送出後連線斷了：檔案卡寫出連線中斷，不再停在原本的進度；接回之後改成批次等待（#286）', async ({ page, mockBackend }) => {
    let submitted
    const reconnected = gate()
    const backend = await mockBackend({
        routes: {
            'POST /upload': { filename: 'upload.wav' },
            // 任務頁的批次清單：這一批送出給供應商了，還在等結果
            'GET /batch/tasks': () => (submitted ? [{
                batch_id: submitted.batch_id, status: 'POLLING', file_count: 2, is_alive: true,
                created_at: null, elapsed_seconds: 0, files: [], session_id: submitted.session_id, recoverable: false,
            }] : []),
        },
        // 上傳到一半時連線斷了
        batch: async (request, send, close) => {
            submitted = request
            uploadProgress(request).forEach(send)
            close()
        },
        // 接回時批次還在上傳；等畫面上看到連線中斷，才回狀態、之後送出給供應商
        batchReattach: async (batchId, send) => {
            await reconnected.opened
            send({ client_id: batchId, status_code: 'PROCESSING', status_text: '重新連上了，批次還在處理中...' })
            send({
                client_id: batchId, batch_id: batchId, task_uuid: 'run-1', status_code: 'BATCH_SUBMITTED',
                status_text: '批次已送出給 Gemini，共 2 個檔案，等待處理中...',
            })
        },
    })
    await startBatchOfTwo(page)

    const notices = page.getByTestId('connection-notice')
    await expect(notices.getByText('和伺服器的連線中斷了')).toHaveCount(2)
    await expect(notices.getByText(/連線中斷不會停止任務，不必重新轉錄/)).toHaveCount(2)
    await expect(page.getByText('連線中斷，正在重新連線...')).toHaveCount(2)
    await expect(page.getByText(/前處理與上傳/)).toHaveCount(0)
    // 接回的是畫面送出的同一批
    expect(backend.batchReattachments).toEqual([submitted.batch_id])

    // 和連線沒斷時一樣：檔案卡改成批次等待，結果到任務頁取回
    reconnected.open()
    await expect(page.getByText('批次已送出給 Gemini，共 2 個檔案，等待處理中...')).toHaveCount(2)
    await expect(notices).toHaveCount(0)
    await expect(page.getByText(/批次已送出，可繼續其他操作/)).toBeVisible()
})

test('還沒派送就斷線的批次，不會被當成已經送出或已經完成（#286）', async ({ page, mockBackend }) => {
    const backend = await mockBackend({
        routes: { 'POST /upload': { filename: 'upload.wav' } },
        // 請求送出之後、伺服器回應之前連線就斷了
        batch: async (request, send, close) => close(),
        // 伺服器上沒有這個批次（沒有批次紀錄，也沒有收到它）
        batchReattach: async (batchId, send) => send({
            client_id: batchId, status_code: 'FAILED',
            status_text: '批次沒有送出: 伺服器上沒有這個批次，批次沒有送出：可能是送出時連線就中斷了，或應用程式關閉了',
            error_code: 'SUBMIT_FAILED',
            error_message: '伺服器上沒有這個批次，批次沒有送出：可能是送出時連線就中斷了，或應用程式關閉了',
        }),
    })
    await startBatchOfTwo(page)

    await expect(page.getByTestId('failure-notice').getByText('任務沒有送出')).toHaveCount(2)
    await expect(page.getByText(/^錯誤碼 SUBMIT_FAILED · 伺服器上沒有這個批次/)).toHaveCount(2)
    await expect(page.getByText('2 個任務失敗')).toBeVisible()
    await expect(page.getByText(/批次已送出|批次結果已儲存/)).toHaveCount(0)
    expect(backend.batchReattachments).toHaveLength(1)
})

test('批次上傳時連不上伺服器：說明要重新開啟 Mimiji；重新開啟之後自動接回，沒送出的檔案標成失敗（#286）', async ({ page, mockBackend }) => {
    const restarted = gate()
    let submitted
    let attempts = 0
    await mockBackend({
        routes: { 'POST /upload': { filename: 'upload.wav' } },
        batch: async (request, send, close) => {
            submitted = request
            uploadProgress(request).forEach(send)
            close()
        },
        batchReattach: async (batchId, send, close) => {
            attempts += 1
            // 第一次：伺服器已經停了，一則都沒回就斷了
            if (attempts === 1) return close()
            // 之後：重新開啟了。免安裝模式啟動時，上傳時停住的批次記成失敗，每個檔案照任務紀錄補上
            await restarted.opened
            for (const progress of uploadProgress(submitted)) {
                send({
                    ...progress, status_code: 'FAILED', status_text: '任務失敗: 上傳時服務停止了，批次沒有送出',
                    error_code: 'INTERRUPTED', error_message: '上傳時服務停止了，批次沒有送出',
                })
            }
        },
    })
    await startBatchOfTwo(page)

    const notices = page.getByTestId('connection-notice')
    await expect(notices.getByText('連不上伺服器，Mimiji 可能已經關閉')).toHaveCount(2)
    await expect(notices.getByText(/請重新開啟 Mimiji（免安裝版是 AI_Translate.exe/)).toHaveCount(2)
    await expect(notices.first().getByRole('link', { name: '任務頁' })).toHaveAttribute('href', '/tasks')
    await expect(page.getByText('連線中斷，連不上伺服器')).toHaveCount(2)

    restarted.open()
    const failures = page.getByTestId('failure-notice')
    await expect(failures.getByText('應用程式在處理途中關閉了')).toHaveCount(2)
    await expect(page.getByText(/上傳時服務停止了，批次沒有送出/)).toHaveCount(2)
    await expect(notices).toHaveCount(0)
    await expect(page.getByText('2 個任務失敗')).toBeVisible()
})

const NO_GPU = '這台電腦沒有可用的 NVIDIA 顯卡，本機轉錄不能用，可以改用 Gemini'

test('沒有可用的顯卡時仍預設本機：說明原因、停用 Start，按「改用 Gemini」才切換並記住（#11 Q1）', async ({ page, mockBackend }) => {
    const backend = await mockBackend({
        routes: { 'GET /setting/local-models/readiness': readiness({ ready: false, reason: 'no_gpu', message: NO_GPU }) },
    })
    await page.goto('/transcribe')
    await addAudio(page)

    await expect(page.getByLabel('供應商')).toHaveValue('local')
    await expect(page.getByText(NO_GPU)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start' })).toBeDisabled()
    expect(backend.requests.find((r) => r.path === '/setting/local-models/readiness').query)
        .toEqual({ model: 'moss-align' })

    // 會上傳音檔的供應商要使用者自己選，不自動切換
    await page.getByRole('button', { name: '改用 Gemini' }).click()

    await expect(page.getByLabel('供應商')).toHaveValue('google')
    await expect(page.getByText(NO_GPU)).toHaveCount(0)
    await expect(page.getByText(/音檔與提示詞會上傳到 Google/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start' })).toBeEnabled()

    await page.reload()
    await expect(page.getByLabel('供應商')).toHaveValue('google')
})

test('選的本機模型缺模型權重時，停用 Start 並指向設定頁', async ({ page, mockBackend }) => {
    const message = '本機模型權重尚未下載完成，請至 Settings 頁面下載（缺少: OpenMOSS-Team/MOSS-Transcribe-Diarize）'
    await mockBackend({
        routes: { 'GET /setting/local-models/readiness': readiness({ ready: false, reason: 'missing_weights', message }) },
    })
    await page.goto('/transcribe')
    await addAudio(page)

    await expect(page.getByText(message)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start' })).toBeDisabled()
    await expect(page.getByRole('button', { name: '改用 Gemini' })).toHaveCount(0)

    await page.getByRole('link', { name: '到設定頁下載' }).click()
    await expect(page).toHaveURL(/\/settings$/)
})

test('顯卡記憶體低於最低需求只提示，照樣可以按 Start（#11 Q2）', async ({ page, mockBackend }) => {
    const notice = '顯卡記憶體 8 GB 沒有測過（建議 16 GB、至少 12 GB）。長音檔會切成約 26 分鐘一段，各段的說話者編號比較容易對不上'
    await mockBackend({
        routes: { 'GET /setting/local-models/readiness': readiness({ vram_notice: notice }) },
    })
    await page.goto('/transcribe')
    await addAudio(page)

    await expect(page.getByText(notice)).toBeVisible()
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
    // Gemini 的模型去靜音
    await page.getByLabel('供應商').selectOption('google')
    await addAudio(page)

    await page.getByRole('button', { name: '去靜音與切點預覽' }).click()

    const dialog = page.getByRole('dialog', { name: '去靜音與切點預覽' })
    await expect(dialog.getByText('去靜音（speech_only）')).toBeVisible()
    await expect(dialog.getByText('2.5s').first()).toBeVisible()
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

    // 第一次開頁照供應商清單的順序，用第一個供應商（本機）的預設模型
    await expect(page.getByLabel('供應商')).toHaveValue('local')
    await expect(page.getByLabel('模型')).toHaveValue('moss-align')

    await page.getByLabel('供應商').selectOption('google')
    await expect(page.getByLabel('模型')).toHaveValue('gemini-3.5-flash')
    await page.reload()

    await expect(page.getByLabel('供應商')).toHaveValue('google')
    await expect(page.getByLabel('模型')).toHaveValue('gemini-3.5-flash')
    expect(await page.evaluate(() => ({ ...localStorage })))
        .toEqual({ ai_translate_last_selection: JSON.stringify({ provider: 'google', model: null }) })
})

test('上次選的供應商已經不在清單上時，退回清單上的第一個', async ({ page, mockBackend }) => {
    await mockBackend()
    await page.addInitScript(() => {
        // eslint-disable-next-line no-restricted-syntax -- 測試先放一組已經不在清單上的供應商與模型名稱，不是金鑰
        localStorage.setItem('ai_translate_last_selection', JSON.stringify({ provider: 'openai', model: 'whisper-1' }))
    })
    await page.goto('/transcribe')

    await expect(page.getByLabel('供應商')).toHaveValue('local')
    await expect(page.getByLabel('模型')).toHaveValue('moss-align')
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
    await page.getByLabel('供應商').selectOption('google')

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
