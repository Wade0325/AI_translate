import { test, expect, download } from './support/test.js'
import { TRANSCRIPTS, reply } from './support/backend.js'
import {
    MEETING, audioState, correctionsBackend, openCorrection, row, rowAt, segment,
} from './support/correction.js'

/**
 * 校正頁：改文字、刪掉與還原片段（#348）。假後端照 ADR 0011 記下每次校正（support/correction.js 的
 * correctionsBackend），重新整理之後讀到的就是存過的內容。
 */

const PATCH = 'PATCH /transcripts/task-1/segments/:seg_key'
/** 送出的校正（PATCH）：[片段鍵, body]。 */
const patches = (backend) => backend.requests.filter((r) => r.method === 'PATCH')
    .map((r) => [r.path.split('/').pop(), r.body])
/** 正在改的那一列的文字框。 */
const editor = (page) => page.getByLabel('片段的文字')
/** 點一列的文字開始改。 */
const startEditing = (page, index) => rowAt(page, index).locator('.correction-text').click()

/** 沒有逐字時間的片段（Gemini）：點文字只開始改，不會跳播。 */
const GEMINI = MEETING.map((s) => segment(s.seq, s.start, s.end, s.speaker, s.text, { words: false }))

test('點文字就改，按 Enter 存成一次校正；重新整理之後還在，校正過的片段看得到原始轉錄', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })

    await startEditing(page, 1)
    await expect(editor(page)).toBeFocused()
    await expect(editor(page)).toHaveValue('前端的校正頁可以播放了。')
    // 照使用者打的字存，不轉換成繁體輸出
    await editor(page).fill('前端的校正页可以边听边改了。')
    await editor(page).press('Enter')

    await expect(editor(page)).toHaveCount(0)
    await expect(rowAt(page, 1)).toContainText('前端的校正页可以边听边改了。')
    await expect(rowAt(page, 1)).toContainText('已存')
    expect(patches(backend)).toEqual([['0.0001', { text: '前端的校正页可以边听边改了。' }]])

    await rowAt(page, 1).getByRole('button', { name: '校正過' }).click()
    await expect(rowAt(page, 1)).toContainText('原始轉錄')
    await expect(rowAt(page, 1)).toContainText('前端的校正頁可以播放了。')

    // 沒有存檔鈕：重新整理之後讀到的就是存過的內容
    await page.reload()
    await expect(row(page, '边听边改')).toBeVisible()
    await expect(row(page, '边听边改').getByRole('button', { name: '校正過' })).toBeVisible()
    await expect(page.getByRole('button', { name: /存檔/ })).toHaveCount(0)
})

test('點到別處也存；沒改就不送', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })

    await startEditing(page, 2)
    await editor(page).fill('等一下喔。')
    await page.getByText('meeting.wav').click()
    await expect(editor(page)).toHaveCount(0)
    await expect(rowAt(page, 2)).toContainText('等一下喔。')

    await startEditing(page, 3)
    await page.getByText('meeting.wav').click()
    await expect(editor(page)).toHaveCount(0)
    expect(patches(backend)).toEqual([['0.0002', { text: '等一下喔。' }]])
})

test('輸入法選字時按的 Enter 不存檔；Esc 放棄，回到改之前的內容', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(GEMINI)
    const backend = await openCorrection(page, mockBackend, { segments: GEMINI, routes: fake.routes })

    await startEditing(page, 0)
    await editor(page).fill('大家早安')
    // 用注音選字：還在選字時按 Enter（Chromium 的輸入法事件，keydown 的 isComposing 是 true）
    const ime = await page.context().newCDPSession(page)
    await ime.send('Input.imeSetComposition', { text: 'ㄉㄜ˙', selectionStart: 3, selectionEnd: 3 })
    await page.keyboard.press('Enter')
    await ime.send('Input.insertText', { text: '的' })
    // Safari 選完字那一下的 Enter：compositionend 之後才到，isComposing 已經是 false，keyCode 是 229
    await editor(page).evaluate((textarea) => {
        textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 229, bubbles: true }))
    })
    // 沒有存，還在改。CDP 模擬的輸入法不會吃掉選字時的 Enter，文字框可能多一個換行（真的輸入法拿它選字）
    await expect(editor(page)).toBeFocused()
    await expect(editor(page)).toHaveValue(/^大家早安的\s*$/)
    expect(patches(backend)).toEqual([])

    await editor(page).press('Escape')
    await expect(editor(page)).toHaveCount(0)
    await expect(rowAt(page, 0)).toContainText('大家早安，今天先看進度。')
    expect(patches(backend)).toEqual([])
})

test('打字時 Tab 播放或暫停、Shift+Tab 倒退 3 秒，焦點留在文字框；空白鍵與方向鍵照常打字', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(GEMINI)
    await openCorrection(page, mockBackend, { segments: GEMINI, routes: fake.routes })
    // 播放位置先放到 10 秒
    await rowAt(page, 3).getByTitle('從這個片段的開頭播放').click()
    await page.getByRole('button', { name: '暫停' }).click()
    await expect.poll(async () => (await audioState(page)).paused).toBe(true)
    const before = (await audioState(page)).time

    await startEditing(page, 1)
    await editor(page).press('Shift+Tab')
    expect((await audioState(page)).time).toBeCloseTo(before - 3, 1)
    await expect(editor(page)).toBeFocused()

    await editor(page).press('Tab')
    await expect.poll(async () => (await audioState(page)).paused).toBe(false)
    await expect(editor(page)).toBeFocused()
    await editor(page).press('Tab')
    await expect.poll(async () => (await audioState(page)).paused).toBe(true)
    await expect(editor(page)).toBeFocused()

    // 空白鍵與方向鍵是打字用的：不播放，也不算捲動列表（不會停止跟著播放）
    await editor(page).press('End')
    await editor(page).press('ArrowLeft')
    await editor(page).press('Space')
    await editor(page).press('ArrowUp')
    await editor(page).press('ArrowDown')
    await expect(editor(page)).toHaveValue('前端的校正頁可以播放了 。')
    expect((await audioState(page)).paused).toBe(true)
    await editor(page).press('Escape')
    await expect(page.getByRole('button', { name: '回到正在播放的片段' })).toHaveCount(0)
})

test('存檔中寫在那一列，存完寫已存；存檔中的片段先不能再改', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(GEMINI)
    let release
    const answered = new Promise((resolve) => { release = resolve })
    await openCorrection(page, mockBackend, {
        segments: GEMINI,
        routes: { ...fake.routes, [PATCH]: async (request) => { await answered; return fake.routes[PATCH](request) } },
    })

    await startEditing(page, 0)
    await editor(page).fill('大家早，今天先看進度。')
    await editor(page).press('Enter')
    await expect(rowAt(page, 0)).toContainText('存檔中')
    await expect(rowAt(page, 0)).toContainText('大家早，今天先看進度。')
    await startEditing(page, 0)
    await expect(editor(page)).toHaveCount(0)

    release()
    await expect(rowAt(page, 0)).toContainText('已存')
    await expect(rowAt(page, 0)).not.toContainText('存檔中')
})

test('存不進去時留著打的字與原因，可以重試；也可以放棄，回到存好的內容', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(GEMINI)
    let down = true
    const backend = await openCorrection(page, mockBackend, {
        segments: GEMINI,
        routes: { ...fake.routes, [PATCH]: (request) => (down ? reply(500, { detail: 'Internal Server Error' }) : fake.routes[PATCH](request)) },
    })

    await startEditing(page, 1)
    await editor(page).fill('前端的校正頁可以改字了。')
    await editor(page).press('Enter')
    const failed = rowAt(page, 1).getByRole('alert')
    await expect(failed).toContainText('沒有存到：連不上 Mimiji，確認它還在執行之後再重試')
    await expect(rowAt(page, 1)).toContainText('前端的校正頁可以改字了。')

    down = false
    await failed.getByRole('button', { name: '重試' }).click()
    await expect(rowAt(page, 1)).toContainText('已存')
    await expect(rowAt(page, 1).getByRole('alert')).toHaveCount(0)
    expect(patches(backend)).toEqual([
        ['0.0001', { text: '前端的校正頁可以改字了。' }], ['0.0001', { text: '前端的校正頁可以改字了。' }]])

    down = true
    await startEditing(page, 2)
    await editor(page).fill('不要了')
    await editor(page).press('Enter')
    await rowAt(page, 2).getByRole('button', { name: '放棄' }).click()
    await expect(rowAt(page, 2)).toContainText('等一下。')
    await expect(rowAt(page, 2).getByRole('alert')).toHaveCount(0)
})

test('存檔之後幾秒的「已存檔，復原」：按了收回這一次，不按就自己收起來', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(GEMINI)
    const backend = await openCorrection(page, mockBackend, { segments: GEMINI, routes: fake.routes })

    await startEditing(page, 0)
    await editor(page).fill('大家午安，今天先看進度。')
    await editor(page).press('Enter')
    const toast = page.getByRole('status').filter({ hasText: '已存檔' })
    await expect(toast).toBeVisible()
    await toast.getByRole('button', { name: '復原' }).click()

    await expect(rowAt(page, 0)).toContainText('大家早安，今天先看進度。')
    await expect(page.getByText('已復原')).toBeVisible()
    await expect(toast).toHaveCount(0)
    await expect(rowAt(page, 0).getByRole('button', { name: '校正過' })).toHaveCount(0)
    expect(backend.requests.filter((r) => r.method === 'POST').map((r) => r.path))
        .toEqual(['/transcripts/task-1/operations/op-1/undo'])

    await startEditing(page, 2)
    await editor(page).fill('等一下下。')
    await editor(page).press('Enter')
    await expect(toast).toBeVisible()
    await expect(toast).toHaveCount(0, { timeout: 10_000 })
    await expect(rowAt(page, 2)).not.toContainText('已存')
    await expect(rowAt(page, 2)).toContainText('等一下下。')
})

test('刪掉片段：按刪除鈕或清空再存；刪掉的片段留在原位、淡化加刪除線，還原回到刪掉之前的文字', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(GEMINI)
    const backend = await openCorrection(page, mockBackend, { segments: GEMINI, routes: fake.routes })

    await rowAt(page, 2).getByRole('button', { name: '刪掉這個片段' }).click()
    await expect(rowAt(page, 2).locator('[data-deleted]')).toHaveCount(1)
    await expect(rowAt(page, 2).locator('.correction-text')).toHaveCSS('text-decoration-line', 'line-through')
    await expect(rowAt(page, 2)).toContainText('等一下。')
    await expect(rowAt(page, 2)).toContainText('已刪掉')
    // 刪掉的片段不能直接改，要先還原
    await startEditing(page, 2)
    await expect(editor(page)).toHaveCount(0)

    await rowAt(page, 2).getByRole('button', { name: '還原' }).click()
    await expect(rowAt(page, 2).locator('[data-deleted]')).toHaveCount(0)
    await expect(rowAt(page, 2)).toContainText('等一下。')

    // 改過再清空：還原回到改過的文字，不是原始轉錄
    await startEditing(page, 3)
    await editor(page).fill('點一個字就從那裡開始。')
    await editor(page).press('Enter')
    await expect(rowAt(page, 3)).toContainText('已存')
    await startEditing(page, 3)
    await editor(page).fill('')
    await editor(page).press('Enter')
    await expect(rowAt(page, 3).locator('[data-deleted]')).toHaveCount(1)
    await expect(rowAt(page, 3)).toContainText('點一個字就從那裡開始。')

    // 重新整理之後還是刪掉的
    await page.reload()
    await expect(rowAt(page, 3).locator('[data-deleted]')).toHaveCount(1)
    await rowAt(page, 3).getByRole('button', { name: '還原' }).click()
    await expect(rowAt(page, 3)).toContainText('點一個字就從那裡開始。')

    expect(patches(backend)).toEqual([
        ['0.0002', { text: '' }],
        ['0.0002', { text: '等一下。' }],
        ['0.0003', { text: '點一個字就從那裡開始。' }],
        ['0.0003', { text: '' }],
        ['0.0003', { text: '點一個字就從那裡開始。' }],
    ])
})

test('校正過的片段展開看得到原始轉錄，一鍵回到原始轉錄（文字與說話者都回去，照樣是一次校正）', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(GEMINI)
    // 打開之前已經改過文字與說話者
    fake.routes[PATCH]({ params: { seg_key: '0.0001' }, body: { text: '前端的校正頁可以改了。', speaker: 'S2' } })
    const backend = await openCorrection(page, mockBackend, { segments: GEMINI, routes: fake.routes })

    const corrected = rowAt(page, 1)
    await expect(corrected).toContainText('前端的校正頁可以改了。')
    await corrected.getByRole('button', { name: '校正過' }).click()
    // 展開的是這個片段的歷程（#355），最下面是原始轉錄
    const original = corrected.getByRole('listitem').filter({ hasText: '原始轉錄' })
    await expect(original).toContainText('S1')
    await expect(original).toContainText('前端的校正頁可以播放了。')

    await original.getByRole('button', { name: '回到這一版' }).click()
    await expect(corrected.locator('.correction-text')).toHaveText('前端的校正頁可以播放了。')
    await expect(corrected.getByRole('button', { name: '校正過' })).toHaveCount(0)
    await expect(page.getByRole('status').filter({ hasText: '已存檔' })).toBeVisible()
    expect(patches(backend)).toEqual([['0.0001', { text: '前端的校正頁可以播放了。', speaker: 'S1' }]])
    // 回到原始轉錄是一次操作：文字與說話者各記一筆，共用一個操作編號
    expect(fake.records.slice(-2).map((r) => [r.field, r.operation_id])).toEqual([['text', 'op-2'], ['speaker', 'op-2']])
})

test('校正頁的下載選單：預設是校正後版本，另有原始轉錄（檔名多一段 .original）', async ({ page, mockBackend }) => {
    const corrected = TRANSCRIPTS.srt.replace('測試的第一句', '校正過的第一句')
    const backend = await openCorrection(page, mockBackend, {
        routes: {
            'GET /history/task-1/download/srt': ({ query }) => (query.version === 'original' ? TRANSCRIPTS.srt : corrected),
        },
    })

    await page.getByRole('button', { name: '下載' }).click()
    const menu = page.locator('.ant-dropdown-menu').filter({ visible: true })
    await expect(menu.getByText('校正後版本')).toBeVisible()
    await expect(menu.getByText('原始轉錄')).toBeVisible()
    expect(await download(page, () => menu.getByRole('menuitem', { name: 'SRT' }).first().click()))
        .toEqual({ filename: 'meeting.srt', text: corrected })

    await page.getByRole('button', { name: '下載' }).click()
    expect(await download(page, () => menu.getByRole('menuitem', { name: 'SRT' }).last().click()))
        .toEqual({ filename: 'meeting.original.srt', text: TRANSCRIPTS.srt })
    expect(backend.requests.filter((r) => r.path === '/history/task-1/download/srt').map((r) => r.query))
        .toEqual([{ version: 'corrected' }, { version: 'original' }])
})

test('保留音檔已經不在時，文字照樣可以校正', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING, { audio_available: false })
    const backend = await openCorrection(page, mockBackend, { audio: false, routes: fake.routes })

    await expect(page.getByText('保留音檔已經不在，無法播放；文字照樣可以校正')).toBeVisible()
    await startEditing(page, 0)
    // 沒有音檔：Tab 不做事，焦點照樣留在文字框
    await editor(page).press('Tab')
    await expect(editor(page)).toBeFocused()
    await editor(page).fill('大家早安，先看進度。')
    await editor(page).press('Enter')
    await expect(rowAt(page, 0)).toContainText('已存')
    expect(patches(backend)).toEqual([['0.0000', { text: '大家早安，先看進度。' }]])
})
