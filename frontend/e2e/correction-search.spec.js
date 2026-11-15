import { test, expect } from './support/test.js'
import { correctionsBackend, openCorrection, rowAt, segment } from './support/correction.js'

/**
 * 校正頁的尋找與全部取代（#356）。假後端照 ADR 0011 記下每次校正（support/correction.js 的 correctionsBackend），
 * 全部取代算一次操作，可以整批復原。
 */

const SEGMENTS = [
    segment(0, 0.5, 3.5, 'S0', '王曉明先說明進度。'),
    segment(1, 4.0, 7.5, 'S1', '謝謝王曉明，王曉明的報告很清楚。'),
    segment(2, 8.0, 9.0, 'S0', '下一位請準備。'),
    segment(3, 10.0, 14.0, 'S1', 'Mimiji 和 MIMIJI 都可以。'),
]

/** 尋找列與裡面的東西。 */
const findBar = (page) => page.getByRole('search', { name: '尋找與取代' })
const findBox = (page) => findBar(page).getByRole('textbox', { name: '尋找', exact: true })
const counter = (page) => findBar(page).locator('[aria-live]')
/** 那一列標出來的符合的字（本機的片段一個字一段，「王曉明」標成三段，接起來比對）。 */
const marks = (page, index) => rowAt(page, index).locator('mark')
const markedText = async (page, index) => (await marks(page, index).allTextContents()).join('')

test('按 Ctrl+F 開頁面自己的尋找：寫出符合的片段數，Enter 與 Shift+Enter 在符合的片段之間跳，符合的字標出來', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(SEGMENTS)
    await openCorrection(page, mockBackend, { segments: SEGMENTS, routes: fake.routes })
    await expect(rowAt(page, 0)).toBeVisible()

    await page.keyboard.press('Control+f')
    await expect(findBox(page)).toBeFocused()

    await findBox(page).fill('王曉明')
    await expect(counter(page)).toHaveText('1／2 個片段')
    expect(await markedText(page, 0)).toBe('王曉明')
    expect(await markedText(page, 1)).toBe('王曉明王曉明')
    await expect(marks(page, 2)).toHaveCount(0)
    // 現在跳到的那個片段標得更明顯
    await expect(rowAt(page, 0).locator('[data-current-match]')).toHaveCount(1)

    await findBox(page).press('Enter')
    await expect(counter(page)).toHaveText('2／2 個片段')
    await expect(rowAt(page, 1).locator('[data-current-match]')).toHaveCount(1)
    await findBox(page).press('Enter')
    await expect(counter(page)).toHaveText('1／2 個片段')
    await findBox(page).press('Shift+Enter')
    await expect(counter(page)).toHaveText('2／2 個片段')
    await findBar(page).getByRole('button', { name: '上一個符合的片段' }).click()
    await expect(counter(page)).toHaveText('1／2 個片段')

    // 英文不分大小寫；本機的片段標字時照樣標得出來
    await findBox(page).fill('mimiji')
    await expect(counter(page)).toHaveText('1／1 個片段')
    expect(await markedText(page, 3)).toBe('MimijiMIMIJI')

    await findBox(page).fill('明天')
    await expect(counter(page)).toHaveText('沒有符合的片段')

    // Esc 收起尋找列，符合的字不再標
    await findBox(page).press('Escape')
    await expect(findBar(page)).toHaveCount(0)
    await expect(page.locator('mark')).toHaveCount(0)
})

test('還沒捲到、沒有畫出來的片段也找得到，跳過去時捲到那一列', async ({ page, mockBackend }) => {
    const many = Array.from({ length: 300 }, (_, i) => segment(i, i * 4, i * 4 + 3, 'S0', `第 ${i} 句，沒有要找的字。`, { words: false }))
    many[250] = segment(250, 1000, 1003, 'S0', '這裡有王曉明。', { words: false })
    const fake = correctionsBackend(many)
    await openCorrection(page, mockBackend, { segments: many, routes: fake.routes, seconds: 30 })
    await expect(rowAt(page, 0)).toBeVisible()
    await expect(rowAt(page, 250)).toHaveCount(0)

    await page.keyboard.press('Control+f')
    await findBox(page).fill('王曉明')

    await expect(counter(page)).toHaveText('1／1 個片段')
    await expect(rowAt(page, 250)).toBeInViewport()
    await expect(marks(page, 250)).toHaveText(['王曉明'])
})

test('全部取代：先寫明會改到幾個片段、一共幾處，確認之後才做；做完可以整批復原', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(SEGMENTS)
    const backend = await openCorrection(page, mockBackend, { segments: SEGMENTS, routes: fake.routes })

    await page.getByRole('button', { name: '尋找' }).click()
    await findBox(page).fill('王曉明')
    await findBar(page).getByLabel('取代為').fill('王小明')
    await findBar(page).getByRole('button', { name: '全部取代' }).click()

    const confirm = page.locator('.ant-popconfirm').filter({ visible: true })
    await expect(confirm).toContainText('把「王曉明」換成「王小明」')
    await expect(confirm).toContainText('會改到 2 個片段，一共 3 處。')
    // 確認之前什麼都不送
    expect(backend.requests.filter((r) => r.path.endsWith('/replace-all'))).toEqual([])
    await confirm.getByRole('button', { name: '全部取代' }).click()

    await expect(rowAt(page, 0)).toContainText('王小明先說明進度。')
    await expect(rowAt(page, 1)).toContainText('謝謝王小明，王小明的報告很清楚。')
    await expect(rowAt(page, 2)).toContainText('下一位請準備。')
    await expect(counter(page)).toHaveText('沒有符合的片段')
    expect(backend.requests.filter((r) => r.path.endsWith('/replace-all')).map((r) => r.body))
        .toEqual([{ find: '王曉明', replacement: '王小明' }])
    // 一次操作：兩個片段各記一筆，共用一個操作編號
    expect(fake.records.map((r) => [r.seg_key, r.operation_id])).toEqual([['0.0000', 'op-1'], ['0.0001', 'op-1']])

    const toast = page.getByRole('status').filter({ hasText: '已取代 2 個片段，一共 3 處' })
    await expect(toast).toBeVisible()
    await toast.getByRole('button', { name: '復原' }).click()

    await expect(page.getByText('已復原')).toBeVisible()
    await expect(rowAt(page, 0)).toContainText('王曉明先說明進度。')
    await expect(rowAt(page, 1)).toContainText('謝謝王曉明，王曉明的報告很清楚。')
    await expect(counter(page)).toHaveText('1／2 個片段')
})

test('取代成空的：寫明有幾個片段會變成空的，做完那些片段就是刪掉的片段', async ({ page, mockBackend }) => {
    const segments = [
        segment(0, 0.5, 1.5, 'S0', '嗯'),
        segment(1, 2.0, 4.0, 'S1', '嗯，好的。'),
        segment(2, 4.5, 6.0, 'S0', '好的。'),
    ]
    const fake = correctionsBackend(segments)
    await openCorrection(page, mockBackend, { segments, routes: fake.routes })
    await expect(rowAt(page, 0)).toBeVisible()

    await page.keyboard.press('Control+f')
    await findBox(page).fill('嗯')
    await findBar(page).getByRole('button', { name: '全部取代' }).click()

    const confirm = page.locator('.ant-popconfirm').filter({ visible: true })
    await expect(confirm).toContainText('把「嗯」換成空的')
    await expect(confirm).toContainText('會改到 2 個片段，一共 2 處。其中 1 個片段會變成空的，等於刪掉（可以還原）。')
    await confirm.getByRole('button', { name: '全部取代' }).click()

    await expect(rowAt(page, 0)).toContainText('已刪掉')
    await expect(rowAt(page, 1)).toContainText('，好的。')
})

test('刪掉的片段不找；取代之後內容都和現在相同時不能按全部取代', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(SEGMENTS)
    await openCorrection(page, mockBackend, { segments: SEGMENTS, routes: fake.routes })

    await rowAt(page, 0).getByRole('button', { name: '刪掉這個片段' }).click()
    await expect(rowAt(page, 0)).toContainText('已刪掉')

    await page.keyboard.press('Control+f')
    await findBox(page).fill('王曉明')
    await expect(counter(page)).toHaveText('1／1 個片段')
    await expect(marks(page, 0)).toHaveCount(0)

    // 「MIMIJI」換成「Mimiji」會改到；「Mimiji」本來就是，換了也一樣
    await findBox(page).fill('mimiji')
    await findBar(page).getByLabel('取代為').fill('Mimiji')
    await expect(findBar(page).getByRole('button', { name: '全部取代' })).toBeEnabled()
    await findBox(page).fill('都可以')
    await findBar(page).getByLabel('取代為').fill('都可以')
    await expect(counter(page)).toHaveText('1／1 個片段')
    await expect(findBar(page).getByRole('button', { name: '全部取代' })).toBeDisabled()
})

test('改文字時按 Ctrl+F：打到一半的字照樣存，選起來的字拿來找', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(SEGMENTS)
    const backend = await openCorrection(page, mockBackend, { segments: SEGMENTS, routes: fake.routes })

    await rowAt(page, 2).locator('.correction-text').click()
    const editor = page.getByLabel('片段的文字')
    await editor.fill('下一位請準備好。')
    await editor.evaluate((textarea) => textarea.setSelectionRange(0, 3))
    await page.keyboard.press('Control+f')

    await expect(findBox(page)).toBeFocused()
    await expect(findBox(page)).toHaveValue('下一位')
    await expect(rowAt(page, 2)).toContainText('下一位請準備好。')
    await expect(counter(page)).toHaveText('1／1 個片段')
    expect(backend.requests.filter((r) => r.method === 'PATCH').map((r) => r.body)).toEqual([{ text: '下一位請準備好。' }])
})
