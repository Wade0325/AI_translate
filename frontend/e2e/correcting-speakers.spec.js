import { test, expect } from './support/test.js'
import { reply } from './support/backend.js'
import { MEETING, correctionsBackend, openCorrection, rowAt, segment } from './support/correction.js'

/**
 * 校正頁的說話者（#354）：改一個片段的說話者、新的說話者、把這位說話者全部換成另一位再整批復原，以及
 * 「整份當成同一位說話者」與「照模型分出的說話者顯示」的切換。假後端照 ADR 0011 記下每次校正
 * （support/correction.js 的 correctionsBackend）。
 */

/** 送出的請求：[方法, 路徑（去掉 /transcripts/task-1）, body]，讀取的 GET 與保留音檔不算。 */
const writes = (backend) => backend.requests.filter((r) => r.method !== 'GET')
    .map((r) => [r.method, r.path.replace('/transcripts/task-1', ''), r.body])
/** 第 index 列的說話者（點開是選單）。 */
const speakerButton = (page, index) => rowAt(page, index).locator('.correction-speaker')
/** 打開的說話者選單裡，標題是 group 的那一組裡名稱是 name 的選項。 */
const menuItem = (page, group, name) => openMenu(page).locator('.ant-dropdown-menu-item-group', { hasText: group })
    .getByRole('menuitem', { name, exact: true })
/** 打開的說話者選單（關到一半的不算）。 */
const openMenu = (page) => page.locator('.ant-dropdown:not(.ant-dropdown-hidden)')
/** 在打開的說話者選單裡選一項，等選單關好：下一個選單打開時，畫面上才不會同時有兩個選單。 */
const pick = async (page, group, name) => {
    await menuItem(page, group, name).click()
    await expect(openMenu(page)).toHaveCount(0)
}
/** 片段列表裡每一列的說話者，給 toHaveText([...]) 比對每一列寫的說話者。 */
const speakers = (page) => page.locator('[data-index] .correction-speaker')
/** 說話者的切換的一個狀態（選中時 toBeChecked）。 */
const speakerMode = (page, name) => page.getByRole('radio', { name })
/** 按說話者的切換的一個狀態（radio 本身是藏起來的，按的是它的文字）。 */
const switchSpeakerMode = (page, name) => page.locator('.ant-segmented-item', { hasText: name }).click()

test('改一個片段的說話者：換成新的說話者就拆開了，之後的新的說話者接著往上加', async ({ page, mockBackend }) => {
    // 模型把兩位來賓併成同一個 S1：把第 3 個片段指定成新的說話者
    const fake = correctionsBackend(MEETING)
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })

    await speakerButton(page, 3).click()
    await expect(menuItem(page, '這個片段改成', 'S0')).toBeVisible()
    await pick(page, '這個片段改成', '新的說話者（S2）')

    await expect(speakerButton(page, 3)).toHaveText('S2')
    await expect(rowAt(page, 3)).toContainText('已存')
    await expect(page.getByRole('status')).toContainText('已存檔')
    expect(writes(backend)).toEqual([['PATCH', '/segments/0.0003', { speaker: 'S2' }]])

    // 校正過的片段展開是歷程（#355）：說話者的校正與原始轉錄的說話者
    await rowAt(page, 3).getByRole('button', { name: '校正過' }).click()
    await expect(rowAt(page, 3)).toContainText('S1 → S2')
    await expect(rowAt(page, 3)).toContainText('原始轉錄')

    // 下一個新的說話者是 S3；S2 成了現有的說話者
    await speakerButton(page, 1).click()
    await expect(menuItem(page, '這個片段改成', 'S2')).toBeVisible()
    await pick(page, '這個片段改成', '新的說話者（S3）')
    await expect(speakerButton(page, 1)).toHaveText('S3')
    await expect(speakers(page)).toHaveText(['S0', 'S3', 'S0', 'S2'])

    // 重新整理之後讀到的就是存過的內容
    await page.reload()
    await expect(speakerButton(page, 1)).toHaveText('S3')
    await expect(speakers(page)).toHaveText(['S0', 'S3', 'S0', 'S2'])
})

test('把這位說話者全部換成另一位，按「復原」整批收回', async ({ page, mockBackend }) => {
    // 模型把主持人分成 S0 和 S1：把 S0 全部換成 S1
    const fake = correctionsBackend(MEETING)
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })

    await speakerButton(page, 2).click()
    await pick(page, 'S0 的 2 個片段全部換成', 'S1')

    await expect(page.getByRole('status')).toContainText('已把 2 個片段換成 S1')
    await expect(speakers(page)).toHaveText(['S1', 'S1', 'S1', 'S1'])
    expect(writes(backend)).toEqual([['POST', '/speakers/reassign', { from_speaker: 'S0', to_speaker: 'S1' }]])
    // 每個片段各記一筆，共用一個操作編號
    expect(fake.records.map((r) => [r.seg_key, r.before, r.after, r.operation_id])).toEqual([
        ['0.0000', 'S0', 'S1', 'op-1'], ['0.0002', 'S0', 'S1', 'op-1'],
    ])
    // 片段的歷程（#355）把它標成整批操作
    await rowAt(page, 0).getByRole('button', { name: '校正過' }).click()
    await expect(rowAt(page, 0)).toContainText('整批操作：一共改了 2 個片段')

    await page.getByRole('status').getByRole('button', { name: '復原' }).click()

    await expect(page.getByText('已復原')).toBeVisible()
    await expect(speakers(page)).toHaveText(['S0', 'S1', 'S0', 'S1'])
    expect(writes(backend).at(-1)).toEqual(['POST', '/operations/op-1/undo', null])
})

test('一位說話者只有一個片段時，選單沒有「全部換成」', async ({ page, mockBackend }) => {
    const segments = [...MEETING, segment(4, 15.0, 17.0, 'S2', '我只講一句。')]
    const fake = correctionsBackend(segments)
    await openCorrection(page, mockBackend, { segments, routes: fake.routes })

    await speakerButton(page, 4).click()
    await expect(menuItem(page, '這個片段改成', '新的說話者（S3）')).toBeVisible()
    await expect(openMenu(page)).not.toContainText('全部換成')
})

test('當初沒有分說話者的任務：沒有說話者的片段一次全部指定給新的說話者', async ({ page, mockBackend }) => {
    const unassigned = MEETING.map((s) => segment(s.seq, s.start, s.end, null, s.text, { words: false }))
    const fake = correctionsBackend(unassigned)
    const backend = await openCorrection(page, mockBackend, { segments: unassigned, routes: fake.routes })

    await expect(speakers(page)).toHaveText(['未指定', '未指定', '未指定', '未指定'])
    await speakerButton(page, 0).click()
    await pick(page, '未指定的 4 個片段全部換成', '新的說話者（S0）')

    await expect(page.getByRole('status')).toContainText('已把 4 個片段換成 S0')
    await expect(speakers(page)).toHaveText(['S0', 'S0', 'S0', 'S0'])
    expect(writes(backend)).toEqual([['POST', '/speakers/reassign', { from_speaker: null, to_speaker: 'S0' }]])

    // 再把其中一個片段指定給另一位：新的說話者是 S1
    await speakerButton(page, 1).click()
    await pick(page, '這個片段改成', '新的說話者（S1）')
    await expect(speakers(page)).toHaveText(['S0', 'S1', 'S0', 'S0'])
})

test('整份當成同一位說話者時不顯示說話者與相關操作；切換之後看得到模型分出的說話者', async ({ page, mockBackend }) => {
    // 人數做出來之前、Multi-Speaker 開關關著的本機任務：片段照樣存著模型分出的說話者編號
    const fake = correctionsBackend(MEETING, { single_speaker: true })
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })

    await expect(speakerMode(page, '整份當成同一位')).toBeChecked()
    await expect(rowAt(page, 0)).toContainText('大家早安')
    await expect(page.locator('.correction-speaker')).toHaveCount(0)
    await expect(page.locator('[data-index]', { hasText: /S[01]/ })).toHaveCount(0)

    await switchSpeakerMode(page, '照模型分出的說話者顯示')

    await expect(speakerMode(page, '照模型分出的說話者顯示')).toBeChecked()
    await expect(speakers(page)).toHaveText(['S0', 'S1', 'S0', 'S1'])
    // 切換是任務的設定，不算校正：沒有校正紀錄，也沒有「復原」
    expect(writes(backend)).toEqual([['PATCH', '', { single_speaker: false }]])
    expect(fake.records).toEqual([])
    await expect(page.getByRole('status')).toHaveCount(0)

    // 只改說話者的片段：顯示說話者時標「校正過」，切回整份當成同一位時不標
    await speakerButton(page, 2).click()
    await pick(page, '這個片段改成', 'S1')
    await expect(rowAt(page, 2).getByRole('button', { name: '校正過' })).toBeVisible()

    await switchSpeakerMode(page, '整份當成同一位')

    await expect(page.locator('.correction-speaker')).toHaveCount(0)
    await expect(rowAt(page, 2).getByRole('button', { name: '校正過' })).toHaveCount(0)
    expect(writes(backend).at(-1)).toEqual(['PATCH', '', { single_speaker: true }])
    // 歷程還在，但不列說話者的校正，也不寫原始轉錄的說話者
    await rowAt(page, 2).getByRole('button', { name: '歷程' }).click()
    await expect(rowAt(page, 2)).toContainText('另有 1 筆說話者的校正')
    await expect(rowAt(page, 2)).not.toContainText(/S[01]/)

    // 設定存在任務上：重新整理之後還是整份當成同一位
    await page.reload()
    await expect(speakerMode(page, '整份當成同一位')).toBeChecked()
    await expect(page.locator('.correction-speaker')).toHaveCount(0)
})

test('切換存不進去時切回來，並寫出原因', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    await openCorrection(page, mockBackend, {
        routes: { ...fake.routes, 'PATCH /transcripts/task-1': reply(409, { detail: '這個任務還沒完成，完成之後才能校正' }) },
    })

    await switchSpeakerMode(page, '整份當成同一位')

    await expect(page.getByText('沒有切換：這個任務還沒完成，完成之後才能校正')).toBeVisible()
    await expect(speakerMode(page, '照模型分出的說話者顯示')).toBeChecked()
    await expect(speakers(page)).toHaveText(['S0', 'S1', 'S0', 'S1'])
})
