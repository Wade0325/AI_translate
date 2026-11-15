import { test, expect } from './support/test.js'
import { reply } from './support/backend.js'
import { MEETING, audioState, correctionsBackend, openCorrection, rowAt } from './support/correction.js'

/**
 * 校正頁：確認狀態、快捷鍵、進度與篩選（#349）。假後端照 ADR 0011 記下每次校正，確認狀態直接記在片段上
 * （support/correction.js 的 correctionsBackend）。
 */

/** 正在改的那一列的文字框。 */
const editor = (page) => page.getByLabel('片段的文字')
/** 第 index 列（從 0 起）的確認狀態按鈕：已確認或待查。 */
const reviewButton = (page, index, name) => rowAt(page, index).getByRole('button', { name, exact: true })
/** 送出的 PATCH：[路徑的最後一段, body]。 */
const patches = (backend) => backend.requests.filter((r) => r.method === 'PATCH').map((r) => [r.path.split('/').pop(), r.body])
/** 目前這個片段是第 index 列。 */
const expectCurrent = (page, index) => expect(rowAt(page, index).locator('[data-current]')).toHaveCount(1)
const progress = (page) => page.locator('.correction-progress')
const filterOption = (page, name) => page.getByRole('radiogroup', { name: '篩選片段' }).getByText(name)

test('只用鍵盤校完一個任務：播放、換片段、改文字、標已確認與待查', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })
    await expectCurrent(page, 0)

    // 空白鍵播放或暫停
    await page.keyboard.press(' ')
    await expect.poll(async () => (await audioState(page)).paused).toBe(false)
    await page.keyboard.press(' ')
    await expect.poll(async () => (await audioState(page)).paused).toBe(true)

    // ↓、↑ 換片段，播放位置跟著跳到它的開頭
    await page.keyboard.press('ArrowDown')
    await expectCurrent(page, 1)
    expect((await audioState(page)).time).toBeCloseTo(4.0)
    await page.keyboard.press('ArrowUp')
    await expectCurrent(page, 0)
    expect((await audioState(page)).time).toBeCloseTo(0.5)

    // →、← 前進、倒退 3 秒
    await page.keyboard.press('ArrowRight')
    expect((await audioState(page)).time).toBeCloseTo(3.5)
    await page.keyboard.press('ArrowLeft')
    expect((await audioState(page)).time).toBeCloseTo(0.5)

    // Enter 開始改目前這個片段；打字時空白鍵、方向鍵、V 與 F 都是打字用的
    await page.keyboard.press('Enter')
    await expect(editor(page)).toBeFocused()
    await expect(editor(page)).toHaveValue('大家早安，今天先看進度。')
    await page.keyboard.type(' 好 vf')
    await page.keyboard.press('ArrowDown')
    await expect(editor(page)).toHaveValue('大家早安，今天先看進度。 好 vf')
    await expectCurrent(page, 0)
    expect((await audioState(page)).paused).toBe(true)
    await page.keyboard.press('Enter')
    await expect(editor(page)).toHaveCount(0)
    await expect(rowAt(page, 0)).toContainText('大家早安，今天先看進度。 好 vf')

    // V 標成已確認並換到下一個片段；F 標成待查並換到下一個片段
    await page.keyboard.press('v')
    await expect(reviewButton(page, 0, '已確認')).toHaveAttribute('aria-pressed', 'true')
    await expectCurrent(page, 1)
    expect((await audioState(page)).time).toBeCloseTo(4.0)
    await page.keyboard.press('f')
    await expect(reviewButton(page, 1, '待查')).toHaveAttribute('aria-pressed', 'true')
    await expectCurrent(page, 2)

    // 已經是待查時再按一次 F 是取消，留在原地；V 也一樣
    await page.keyboard.press('ArrowUp')
    await page.keyboard.press('f')
    await expect(reviewButton(page, 1, '待查')).toHaveAttribute('aria-pressed', 'false')
    await expectCurrent(page, 1)
    await page.keyboard.press('v')
    await expectCurrent(page, 2)
    await page.keyboard.press('ArrowUp')
    await page.keyboard.press('v')
    await expect(reviewButton(page, 1, '已確認')).toHaveAttribute('aria-pressed', 'false')
    await expectCurrent(page, 1)

    // R 從頭重播目前這個片段
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('r')
    await expect.poll(async () => (await audioState(page)).paused).toBe(false)
    expect((await audioState(page)).time).toBeLessThan(5.0)
    await page.keyboard.press(' ')

    expect(patches(backend)).toEqual([
        ['0.0000', { text: '大家早安，今天先看進度。 好 vf' }],
        ['0.0000', { review_state: 'verified' }],
        ['0.0001', { review_state: 'flagged' }],
        ['0.0001', { review_state: null }],
        ['0.0001', { review_state: 'verified' }],
        ['0.0001', { review_state: null }],
    ])
    // 確認狀態不是校正：校正紀錄只有改文字的那一筆
    expect(fake.records.map((r) => r.field)).toEqual(['text'])

    // 重新整理之後確認狀態還在
    await page.reload()
    await expect(reviewButton(page, 0, '已確認')).toHaveAttribute('aria-pressed', 'true')
})

test('一路聽下去：播放進到下一段之後才按 V，標的是剛聽完的那一段；拖播放進度才換目前的片段', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    await openCorrection(page, mockBackend, { routes: fake.routes })
    await expectCurrent(page, 0)

    // 播放位置進到第 2 段（4.0 秒起），目前這個片段還是第 1 段
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('ArrowRight')
    expect((await audioState(page)).time).toBeCloseTo(6.0)
    await expect(rowAt(page, 1).locator('[data-active]').first()).toBeVisible()
    await expectCurrent(page, 0)

    await page.keyboard.press('v')
    await expect(reviewButton(page, 0, '已確認')).toHaveAttribute('aria-pressed', 'true')
    await expect(reviewButton(page, 1, '已確認')).toHaveAttribute('aria-pressed', 'false')
    await expectCurrent(page, 1)

    // 拖播放進度到第 4 段（10 秒起）：目前這個片段換過去
    const slider = page.locator('.ant-slider')
    const box = await slider.boundingBox()
    await slider.click({ position: { x: box.width * 0.55, y: box.height / 2 } })
    await expectCurrent(page, 3)
})

test('其餘全部標成已確認還在送時標的片段排在它後面送，不被它的結果蓋掉', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    let release = () => {}
    const gate = new Promise((resolve) => { release = resolve })
    const bulk = fake.routes['PATCH /transcripts/task-1/review-states']
    const backend = await openCorrection(page, mockBackend, {
        routes: { ...fake.routes, 'PATCH /transcripts/task-1/review-states': async (request) => { await gate; return bulk(request) } },
    })
    await expectCurrent(page, 0)

    await page.getByRole('button', { name: '其餘全部標成已確認' }).click()
    await page.getByRole('button', { name: '標成已確認', exact: true }).click()
    await expect(page.getByRole('button', { name: '其餘全部標成已確認' })).toHaveClass(/ant-btn-loading/)

    // 還在送時把第 2 列標成待查：畫面先換，請求等它送完才送
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('f')
    await expect(reviewButton(page, 1, '待查')).toHaveAttribute('aria-pressed', 'true')
    expect(fake.reviewStates.get('0.0001')).toBe(null)

    release()
    for (const index of [0, 2, 3]) {
        await expect(reviewButton(page, index, '已確認')).toHaveAttribute('aria-pressed', 'true')
    }
    await expect(reviewButton(page, 1, '待查')).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(() => fake.reviewStates.get('0.0001')).toBe('flagged')
    expect(patches(backend)).toEqual([
        ['review-states', { review_state: 'verified', only_if: null }],
        ['0.0001', { review_state: 'flagged' }],
    ])
})

test('焦點在按鈕上時，空白鍵與 Enter 照常按那個按鈕，其他快捷鍵照常', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    await openCorrection(page, mockBackend, { routes: fake.routes })

    // 用滑鼠按了播放之後焦點留在播放鈕上：空白鍵按的是播放鈕，只切換一次
    await page.getByRole('button', { name: '播放' }).click()
    await expect.poll(async () => (await audioState(page)).paused).toBe(false)
    await page.keyboard.press(' ')
    await expect.poll(async () => (await audioState(page)).paused).toBe(true)
    await page.keyboard.press('ArrowDown')
    await expectCurrent(page, 1)
    await expect(editor(page)).toHaveCount(0)
})

test('點一列就換成那一列；用滑鼠標確認狀態不換片段', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    await openCorrection(page, mockBackend, { routes: fake.routes })

    await reviewButton(page, 2, '待查').click()
    await expect(reviewButton(page, 2, '待查')).toHaveAttribute('aria-pressed', 'true')
    await expectCurrent(page, 2)
    await reviewButton(page, 2, '待查').click()
    await expect(reviewButton(page, 2, '待查')).toHaveAttribute('aria-pressed', 'false')
    await expectCurrent(page, 2)
})

test('確認狀態存不進去時改回去，寫出原因', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    await openCorrection(page, mockBackend, {
        routes: { ...fake.routes, 'PATCH /transcripts/task-1/segments/:seg_key': reply(500, { detail: 'Internal Server Error' }) },
    })
    await expectCurrent(page, 0)

    await page.keyboard.press('v')
    await expect(page.getByText('沒有標上確認狀態：連不上 Mimiji，確認它還在執行之後再重試')).toBeVisible()
    await expect(reviewButton(page, 0, '已確認')).toHaveAttribute('aria-pressed', 'false')
})

test('保留音檔不在時，鍵盤照樣換片段、改文字與標確認狀態', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING, { audio_available: false })
    await openCorrection(page, mockBackend, { routes: fake.routes, audio: false })
    await expectCurrent(page, 0)

    await page.keyboard.press(' ')
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
    await expectCurrent(page, 2)
    await page.keyboard.press('f')
    await expect(reviewButton(page, 2, '待查')).toHaveAttribute('aria-pressed', 'true')
    await expectCurrent(page, 3)
    await page.keyboard.press('Enter')
    await expect(editor(page)).toHaveValue('點一個字就從那個字開始。')
})

test('進度寫已確認或校正過的片段數；可以只看待查的或還沒看過的', async ({ page, mockBackend }) => {
    const segments = [{ ...MEETING[0], review_state: 'verified' }, { ...MEETING[1], review_state: 'flagged' }, MEETING[2], MEETING[3]]
    const fake = correctionsBackend(segments)
    await openCorrection(page, mockBackend, { segments, routes: fake.routes })

    await expect(progress(page)).toContainText('已確認或校正過1 / 4')
    // 校正過的片段也算進去
    await rowAt(page, 2).locator('.correction-text').click()
    await editor(page).fill('等一下喔。')
    await editor(page).press('Enter')
    await expect(progress(page)).toContainText('2 / 4')

    await filterOption(page, '只看待查的 1').click()
    await expect(page.locator('[data-index]')).toHaveCount(1)
    await expect(rowAt(page, 0)).toContainText('前端的校正頁可以播放了。')
    await expectCurrent(page, 0)
    // 標成已確認之後不在眼前消失，再按一次還取消得到；要重新篩選就再選一次
    await page.keyboard.press('v')
    await expect(reviewButton(page, 0, '已確認')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('[data-index]')).toHaveCount(1)
    await expect(filterOption(page, '只看待查的 0')).toBeVisible()
    await expect(progress(page)).toContainText('3 / 4')

    // 還沒看過：沒有確認狀態，也沒有校正過
    await filterOption(page, '只看還沒看過的 1').click()
    await expect(page.locator('[data-index]')).toHaveCount(1)
    await expect(rowAt(page, 0)).toContainText('點一個字就從那個字開始。')
    await expectCurrent(page, 0)

    await filterOption(page, '只看待查的 0').click()
    await expect(page.getByText('沒有待查的片段')).toBeVisible()

    await filterOption(page, '全部 4').click()
    await expect(page.locator('[data-index]')).toHaveCount(4)
})

test('其餘全部標成已確認：先問一次寫明幾個，做完可以馬上復原，在這之間改成待查的不動', async ({ page, mockBackend }) => {
    const segments = [{ ...MEETING[0], review_state: 'flagged' }, MEETING[1], MEETING[2], MEETING[3]]
    const fake = correctionsBackend(segments)
    const backend = await openCorrection(page, mockBackend, { segments, routes: fake.routes })

    await page.getByRole('button', { name: '其餘全部標成已確認' }).click()
    await expect(page.getByText('把其餘 3 個片段標成已確認？')).toBeVisible()
    // 問的時候快捷鍵不動列表
    await page.keyboard.press('v')
    await expect(reviewButton(page, 0, '已確認')).toHaveAttribute('aria-pressed', 'false')
    await page.getByRole('button', { name: '標成已確認', exact: true }).click()

    for (const index of [1, 2, 3]) {
        await expect(reviewButton(page, index, '已確認')).toHaveAttribute('aria-pressed', 'true')
    }
    await expect(reviewButton(page, 0, '待查')).toHaveAttribute('aria-pressed', 'true')
    await expect(progress(page)).toContainText('3 / 4')
    await expect(page.getByRole('status').filter({ hasText: '已把 3 個片段標成已確認' })).toBeVisible()
    await expect(page.getByRole('button', { name: '其餘全部標成已確認' })).toBeDisabled()
    // 用滑鼠按過的按鈕不留焦點：空白鍵是播放，不是再按一次
    await page.keyboard.press(' ')
    await expect.poll(async () => (await audioState(page)).paused).toBe(false)
    await page.keyboard.press(' ')
    await expect.poll(async () => (await audioState(page)).paused).toBe(true)

    // 在這之間把第 2 列改成待查，再復原：它不動，其他兩個清掉
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('f')
    await expect(reviewButton(page, 1, '待查')).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('status').filter({ hasText: '已把 3 個片段標成已確認' }).getByRole('button', { name: '復原' }).click()
    await expect(page.getByText('已復原；有 1 個片段在這之間改了確認狀態，沒有動')).toBeVisible()
    for (const index of [2, 3]) {
        await expect(reviewButton(page, index, '已確認')).toHaveAttribute('aria-pressed', 'false')
    }
    await expect(reviewButton(page, 1, '待查')).toHaveAttribute('aria-pressed', 'true')
    await expect(reviewButton(page, 0, '待查')).toHaveAttribute('aria-pressed', 'true')

    expect(patches(backend)).toEqual([
        ['review-states', { review_state: 'verified', only_if: null }],
        ['0.0001', { review_state: 'flagged' }],
        ['review-states', { review_state: null, only_if: 'verified', seg_keys: ['0.0001', '0.0002', '0.0003'] }],
    ])
    expect(fake.records).toEqual([])
})

test('頁面上列出快捷鍵', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    await openCorrection(page, mockBackend, { routes: fake.routes })

    await page.getByRole('button', { name: '快捷鍵' }).click()
    const help = page.getByLabel('快捷鍵說明')
    // 播放或暫停：不在打字時是空白鍵，打字時是 Tab
    await expect(help.getByText('播放或暫停', { exact: true })).toHaveCount(2)
    for (const text of ['換到上一個、下一個片段', '倒退、前進 3 秒', '開始改目前這個片段的文字',
        '標成已確認，換到下一個片段；再按一次是取消', '標成待查，換到下一個片段；再按一次是取消', '從頭重播目前這個片段',
        '存檔', '放棄', '倒退 3 秒']) {
        await expect(help.getByText(text, { exact: true })).toBeVisible()
    }
})
