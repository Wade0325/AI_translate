import { test, expect } from './support/test.js'
import { MEETING, correctionsBackend, openCorrection, rowAt } from './support/correction.js'

/**
 * 校正頁的說話者名稱（#359）：從片段的說話者選單替說話者取名字、改名字、清掉名字，這位說話者的每一列一起換成新名稱，
 * 「復原」收回；同一個任務裡重複的名稱被擋。假後端照 ADR 0011 記下每次校正（support/correction.js 的
 * correctionsBackend），說話者名稱的紀錄對象是說話者編號。下載寫名稱由後端的整合測試驗（test_speaker_names_api.py）。
 */

/** 送出的請求：[方法, 路徑（去掉 /transcripts/task-1）, body]，讀取的 GET 與保留音檔不算。 */
const writes = (backend) => backend.requests.filter((r) => r.method !== 'GET')
    .map((r) => [r.method, r.path.replace('/transcripts/task-1', ''), r.body])
/** 片段列表裡每一列的說話者，給 toHaveText([...]) 比對每一列寫的說話者。 */
const speakers = (page) => page.locator('[data-index] .correction-speaker')
/** 打開的說話者選單（關到一半的不算）。 */
const openMenu = (page) => page.locator('.ant-dropdown:not(.ant-dropdown-hidden)')
/** 點第 index 列的說話者，在選單裡選 name 那一項。 */
const chooseFromMenu = async (page, index, name) => {
    await rowAt(page, index).locator('.correction-speaker').click()
    await openMenu(page).getByRole('menuitem', { name, exact: true }).click()
    await expect(openMenu(page)).toHaveCount(0)
}
const dialog = (page) => page.getByRole('dialog')
const nameInput = (page) => dialog(page).getByRole('textbox', { name: '說話者名稱' })
/** 名稱紀錄：[說話者編號, 改前, 改後, 操作編號]。 */
const nameRecords = (fake) => fake.records.filter((r) => r.field === 'speaker_name')
    .map((r) => [r.seg_key, r.before, r.after, r.operation_id])

test('替一位說話者取名字：這位說話者的每一列一起換成名稱，按「復原」收回', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })
    await expect(speakers(page)).toHaveText(['S0', 'S1', 'S0', 'S1'])

    await chooseFromMenu(page, 2, '替 S0 取名字…')
    await expect(dialog(page)).toContainText('替 S0 取名字')
    await expect(nameInput(page)).toBeFocused()
    await nameInput(page).fill('王小明')
    await nameInput(page).press('Enter')

    await expect(dialog(page)).toHaveCount(0)
    await expect(speakers(page)).toHaveText(['王小明', 'S1', '王小明', 'S1'])
    await expect(page.getByRole('status')).toContainText('已把 S0 叫做「王小明」')
    expect(writes(backend)).toEqual([['PUT', '/speakers/S0/name', { name: '王小明' }]])
    expect(nameRecords(fake)).toEqual([['S0', '', '王小明', 'op-1']])

    // 選單也寫名稱：換成王小明的選項後面帶著它的說話者編號
    await rowAt(page, 1).locator('.correction-speaker').click()
    await expect(openMenu(page).getByRole('menuitem', { name: '王小明（S0）', exact: true }).first()).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(openMenu(page)).toHaveCount(0)

    await page.getByRole('status').getByRole('button', { name: '復原' }).click()

    await expect(page.getByText('已復原')).toBeVisible()
    await expect(speakers(page)).toHaveText(['S0', 'S1', 'S0', 'S1'])
    expect(writes(backend).at(-1)).toEqual(['POST', '/operations/op-1/undo', null])
    expect(nameRecords(fake)).toEqual([['S0', '', '王小明', 'op-1'], ['S0', '王小明', '', 'op-2']])
})

test('改名字與清掉名字：清空再存就回到顯示說話者編號，重新整理之後還在', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    fake.bulk([['S1', 'speaker_name', '李大華']])
    await openCorrection(page, mockBackend, { routes: fake.routes })
    await expect(speakers(page)).toHaveText(['S0', '李大華', 'S0', '李大華'])

    await chooseFromMenu(page, 1, '改 S1 的名字…')
    await expect(nameInput(page)).toHaveValue('李大華')
    await nameInput(page).fill('李小華')
    await dialog(page).getByRole('button', { name: /存\s*檔/ }).click()

    await expect(speakers(page)).toHaveText(['S0', '李小華', 'S0', '李小華'])
    await page.reload()
    await expect(speakers(page)).toHaveText(['S0', '李小華', 'S0', '李小華'])

    await chooseFromMenu(page, 3, '改 S1 的名字…')
    await nameInput(page).fill('')
    await expect(dialog(page)).toContainText('清空再存就回到顯示 S1')
    await dialog(page).getByRole('button', { name: /存\s*檔/ }).click()

    await expect(speakers(page)).toHaveText(['S0', 'S1', 'S0', 'S1'])
    await expect(page.getByRole('status')).toContainText('S1 已改回顯示說話者編號')
    expect(nameRecords(fake).map((r) => r.slice(1, 3))).toEqual([['', '李大華'], ['李大華', '李小華'], ['李小華', '']])
})

test('另一位說話者已經用了這個名稱：寫出是哪一位，對話框留著讓人改', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    fake.bulk([['S0', 'speaker_name', '王小明']])
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })

    await chooseFromMenu(page, 1, '替 S1 取名字…')
    await nameInput(page).fill('王小明')
    await nameInput(page).press('Enter')

    await expect(dialog(page).getByRole('alert')).toHaveText('S0 已經叫「王小明」：同一個任務裡兩位說話者不能取同一個名稱')
    await expect(speakers(page)).toHaveText(['王小明', 'S1', '王小明', 'S1'])
    expect(nameRecords(fake)).toHaveLength(1)

    await nameInput(page).fill('李大華')
    await expect(dialog(page).getByRole('alert')).toHaveCount(0)
    await nameInput(page).press('Enter')

    await expect(dialog(page)).toHaveCount(0)
    await expect(speakers(page)).toHaveText(['王小明', '李大華', '王小明', '李大華'])
    expect(writes(backend).map(([method, path]) => [method, path])).toEqual([
        ['PUT', '/speakers/S1/name'], ['PUT', '/speakers/S1/name']])
})

test('不合規則的名稱邊打邊寫出原因，不能存；按 Esc 不存就關掉', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })
    await chooseFromMenu(page, 0, '替 S0 取名字…')
    const save = dialog(page).getByRole('button', { name: /存\s*檔/ })

    for (const [name, reason] of [
        ['[主持人]', '名稱不能有方括號（[ 或 ]）'],
        ['S2', '名稱不能寫成 S 加數字，會和說話者編號分不出來'],
        ['名'.repeat(31), '名稱最多 30 個字'],
        ['00:05.00', '名稱不能寫成時間（例如 00:05.00），LRC 會把它當成時間戳'],
    ]) {
        await nameInput(page).fill(name)
        await expect(dialog(page).getByRole('alert')).toHaveText(reason)
        await expect(save).toBeDisabled()
        await nameInput(page).press('Enter')
    }
    expect(writes(backend)).toEqual([])

    await nameInput(page).fill('主持人')
    await expect(save).toBeEnabled()
    await page.keyboard.press('Escape')

    await expect(dialog(page)).toHaveCount(0)
    await expect(speakers(page)).toHaveText(['S0', 'S1', 'S0', 'S1'])
    expect(writes(backend)).toEqual([])
})
