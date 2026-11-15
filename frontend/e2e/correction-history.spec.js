import { test, expect } from './support/test.js'
import { reply } from './support/backend.js'
import { MEETING, correctionsBackend, openCorrection, rowAt } from './support/correction.js'

/**
 * 校正頁：校正的歷程（#355）。每個片段看得到自己的每一筆校正紀錄，可以回到任何一版（包括原始轉錄）；
 * 整批操作可以整批復原。假後端照 ADR 0011 記下每次校正（support/correction.js 的 correctionsBackend）。
 */

const PATCH = 'PATCH /transcripts/task-1/segments/:seg_key'
const HISTORY = 'GET /transcripts/task-1/segments/:seg_key/correction-records'
/** 送出的校正（PATCH）：[片段鍵, body]。 */
const patches = (backend) => backend.requests.filter((r) => r.method === 'PATCH')
    .map((r) => [r.path.split('/').pop(), r.body])
/** 第 index 列的歷程。 */
const history = (page, index) => rowAt(page, index).getByRole('region', { name: '這個片段的歷程' })
/** 歷程裡的每一版，最上面是最新的一筆。 */
const entries = (page, index) => history(page, index).getByRole('listitem')
/** 一列現在的文字（歷程裡也有文字，用這個分開）。 */
const text = (page, index) => rowAt(page, index).locator('.correction-text')

test('改兩次之後展開歷程：最新的在最上面、原始轉錄在最下面；回到原始轉錄，再回到第二版', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    fake.routes[PATCH]({ params: { seg_key: '0.0001' }, body: { text: '前端的校正頁可以改字了。' } })
    fake.routes[PATCH]({ params: { seg_key: '0.0001' }, body: { text: '前端的校正頁可以邊聽邊改了。' } })
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })

    await rowAt(page, 1).getByRole('button', { name: '校正過' }).click()
    await expect(entries(page, 1)).toHaveCount(3)
    // 每一筆寫了什麼時候改的、改了文字還是說話者、改前與改後；現在的內容標成「現在」
    await expect(entries(page, 1).nth(0)).toContainText(/11\/15\s下午09:01:05/)
    await expect(entries(page, 1).nth(0)).toContainText('改了文字')
    await expect(entries(page, 1).nth(0)).toContainText('改前前端的校正頁可以改字了。')
    await expect(entries(page, 1).nth(0)).toContainText('改後前端的校正頁可以邊聽邊改了。')
    await expect(entries(page, 1).nth(0)).toContainText('現在')
    await expect(entries(page, 1).nth(0).getByRole('button', { name: '回到這一版' })).toHaveCount(0)
    await expect(entries(page, 1).nth(1)).toContainText('改後前端的校正頁可以改字了。')
    await expect(entries(page, 1).nth(2)).toContainText('原始轉錄')
    await expect(entries(page, 1).nth(2)).toContainText('前端的校正頁可以播放了。')

    // 回到原始轉錄：再記一筆，新的一筆出現在最上面，之前的都留著
    await entries(page, 1).nth(2).getByRole('button', { name: '回到這一版' }).click()
    await expect(text(page, 1)).toHaveText('前端的校正頁可以播放了。')
    await expect(entries(page, 1)).toHaveCount(4)
    await expect(entries(page, 1).nth(0)).toContainText('改後前端的校正頁可以播放了。')
    await expect(entries(page, 1).last()).toContainText('現在')
    // 改回和原始轉錄相同：不再是「校正過」，歷程照樣開著
    await expect(rowAt(page, 1).getByRole('button', { name: '歷程' })).toHaveAttribute('aria-expanded', 'true')
    await expect(page.getByRole('status').filter({ hasText: '已存檔' })).toBeVisible()

    // 回到第二版（原本最上面的那一筆，現在在第二個）
    await entries(page, 1).nth(1).getByRole('button', { name: '回到這一版' }).click()
    await expect(text(page, 1)).toHaveText('前端的校正頁可以邊聽邊改了。')
    await expect(entries(page, 1)).toHaveCount(5)
    await expect(rowAt(page, 1).getByRole('button', { name: '校正過' })).toBeVisible()

    expect(patches(backend)).toEqual([
        ['0.0001', { text: '前端的校正頁可以播放了。' }],
        ['0.0001', { text: '前端的校正頁可以邊聽邊改了。' }],
    ])
})

test('一筆改的是說話者時，回到那一筆只改說話者；回到原始轉錄是文字與說話者一起回去', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    fake.routes[PATCH]({ params: { seg_key: '0.0000' }, body: { speaker: 'S2' } })
    fake.routes[PATCH]({ params: { seg_key: '0.0000' }, body: { text: '大家早，今天先看進度。' } })
    fake.routes[PATCH]({ params: { seg_key: '0.0000' }, body: { speaker: 'S1' } })
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })

    await rowAt(page, 0).getByRole('button', { name: '校正過' }).click()
    await expect(entries(page, 0)).toHaveCount(4)
    await expect(entries(page, 0).nth(0)).toContainText('改了說話者')
    await expect(entries(page, 0).nth(0)).toContainText('S2 → S1')

    await entries(page, 0).nth(2).getByRole('button', { name: '回到這一版' }).click()
    await expect(entries(page, 0).nth(0)).toContainText('S1 → S2')
    await expect(text(page, 0)).toHaveText('大家早，今天先看進度。')

    await entries(page, 0).last().getByRole('button', { name: '回到這一版' }).click()
    await expect(text(page, 0)).toHaveText('大家早安，今天先看進度。')
    expect(patches(backend)).toEqual([
        ['0.0000', { speaker: 'S2' }],
        ['0.0000', { text: '大家早安，今天先看進度。', speaker: 'S0' }],
    ])
    // 回到原始轉錄是一次操作：文字與說話者各記一筆，共用一個操作編號
    expect(fake.records.slice(-2).map((r) => [r.field, r.operation_id])).toEqual([['text', 'op-5'], ['speaker', 'op-5']])
})

test('整批操作的那一筆寫明一共改了幾個片段；整批復原略過之後又改過的片段，並寫出略過了幾個', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    // 全部取代「。」→「！」：一次操作改了 4 個片段
    const replaceAll = fake.bulk(MEETING.map((s) => [s.seg_key, 'text', s.text.replace('。', '！')]))
    // 之後又親手改了其中 1 個
    fake.routes[PATCH]({ params: { seg_key: '0.0002' }, body: { text: '等一下喔！' } })
    const backend = await openCorrection(page, mockBackend, { routes: fake.routes })

    await rowAt(page, 0).getByRole('button', { name: '校正過' }).click()
    const bulk = entries(page, 0).nth(0)
    await expect(bulk).toContainText('整批操作：一共改了 4 個片段')
    // 只是一個片段的校正沒有整批復原
    await rowAt(page, 2).getByRole('button', { name: '校正過' }).click()
    await expect(entries(page, 2).nth(0).getByRole('button', { name: '整批復原' })).toHaveCount(0)

    await bulk.getByRole('button', { name: '整批復原' }).click()
    await expect(page.getByText('已整批復原 3 個片段；略過 1 個在這之後又改過的片段')).toBeVisible()
    await expect(text(page, 0)).toHaveText('大家早安，今天先看進度。')
    await expect(text(page, 1)).toHaveText('前端的校正頁可以播放了。')
    await expect(text(page, 2)).toHaveText('等一下喔！')
    await expect(text(page, 3)).toHaveText('點一個字就從那個字開始。')
    expect(backend.requests.filter((r) => r.method === 'POST').map((r) => r.path))
        .toEqual([`/transcripts/task-1/operations/${replaceAll}/undo`])

    // 整批復原本身也是一次操作：歷程多一筆（同樣是整批操作），存完一樣可以馬上復原
    await expect(entries(page, 0).nth(0)).toContainText('整批操作：一共改了 3 個片段')
    await page.getByRole('status').filter({ hasText: '已存檔' }).getByRole('button', { name: '復原' }).click()
    await expect(text(page, 0)).toHaveText('大家早安，今天先看進度！')
    await expect(text(page, 2)).toHaveText('等一下喔！')
})

test('刪掉的片段與改回原樣的片段照樣按「歷程」展開', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    fake.routes[PATCH]({ params: { seg_key: '0.0002' }, body: { text: '' } })
    fake.routes[PATCH]({ params: { seg_key: '0.0003' }, body: { text: '點一個字。' } })
    fake.routes[PATCH]({ params: { seg_key: '0.0003' }, body: { text: '點一個字就從那個字開始。' } })
    await openCorrection(page, mockBackend, { routes: fake.routes })

    await expect(rowAt(page, 0).getByRole('button', { name: '歷程' })).toHaveCount(0)
    await rowAt(page, 2).getByRole('button', { name: '歷程' }).click()
    await expect(entries(page, 2).nth(0)).toContainText('改後（刪掉這個片段）')
    // 回到刪掉之前的那一版就是還原
    await entries(page, 2).last().getByRole('button', { name: '回到這一版' }).click()
    await expect(rowAt(page, 2).locator('[data-deleted]')).toHaveCount(0)

    await rowAt(page, 3).getByRole('button', { name: '歷程' }).click()
    await expect(entries(page, 3)).toHaveCount(3)
    await expect(entries(page, 3).last()).toContainText('現在')
})

test('讀不到歷程時寫原因，可以重試', async ({ page, mockBackend }) => {
    const fake = correctionsBackend(MEETING)
    fake.routes[PATCH]({ params: { seg_key: '0.0001' }, body: { text: '前端的校正頁可以改字了。' } })
    let down = true
    await openCorrection(page, mockBackend, {
        routes: { ...fake.routes, [HISTORY]: (request) => (down ? reply(500, { detail: 'Internal Server Error' }) : fake.routes[HISTORY](request)) },
    })

    await rowAt(page, 1).getByRole('button', { name: '校正過' }).click()
    const failed = history(page, 1).getByRole('alert')
    await expect(failed).toContainText('讀不到歷程：連不上 Mimiji，確認它還在執行之後再重試')

    down = false
    await failed.getByRole('button', { name: '重試' }).click()
    await expect(entries(page, 1)).toHaveCount(2)
    await expect(history(page, 1).getByRole('alert')).toHaveCount(0)
})
