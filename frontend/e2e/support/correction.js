/**
 * 校正頁的瀏覽器測試共用的假資料：片段、轉錄文件、保留音檔，以及記得每次校正的假後端（#347、#348、#354）。
 *
 * 形狀照 backend/app/schemas/schemas.py 的 TranscriptResponse 與 TranscriptSegmentResponse；欄位一改名，這裡要跟著改。
 */

/** seconds 秒的無聲 WAV（8 kHz、單聲道、16 位元）：保留音檔的內容不重要，播放器要真的能播、能拖曳。 */
export function silentWav(seconds) {
    const rate = 8000
    const data = rate * seconds * 2
    const wav = Buffer.alloc(44 + data)
    wav.write('RIFF', 0)
    wav.writeUInt32LE(36 + data, 4)
    wav.write('WAVEfmt ', 8)
    wav.writeUInt32LE(16, 16)
    wav.writeUInt16LE(1, 20)
    wav.writeUInt16LE(1, 22)
    wav.writeUInt32LE(rate, 24)
    wav.writeUInt32LE(rate * 2, 28)
    wav.writeUInt16LE(2, 32)
    wav.writeUInt16LE(16, 34)
    wav.write('data', 36)
    wav.writeUInt32LE(data, 40)
    return wav
}

/** 一字一個逐字時間，平均分在片段裡（漢字一字一詞，標點沒有逐字時間；和本機的對齊器一樣）。 */
export function wordsOf(text, start, end) {
    const chars = Array.from(text).filter((c) => /[\p{L}\p{N}]/u.test(c))
    const step = (end - start) / chars.length
    return chars.map((c, i) => ({ text: c, start: start + i * step, end: start + (i + 1) * step }))
}

/** 沒有校正過的片段：校正後版本（text、speaker）和原始轉錄（original_text、original_speaker）相同。 */
export const segment = (seq, start, end, speaker, text, { words = true } = {}) => ({
    seg_key: `0.${String(seq).padStart(4, '0')}`, seq, start, end, speaker, text,
    original_speaker: speaker, original_text: text, corrected: false, deleted: false, deleted_text: null,
    has_correction_records: false, text_alt: null, source: words ? 'aligned' : null, confidence: null, review_state: null,
    words: words ? wordsOf(text, start, end) : null,
})

/**
 * 新的說話者編號：這些說話者編號裡最大的號碼加一，沒有時是 S0（後端另外看校正紀錄與說話者名稱，見
 * backend/app/repositories/correction_repository.py 的 next_speaker）。
 *
 * @param {(string | null | undefined)[]} speakers
 */
export function nextSpeakerOf(speakers) {
    const numbers = speakers.map((s) => /^S(\d+)$/.exec(s ?? '')).filter(Boolean).map((m) => Number(m[1]))
    return `S${numbers.length ? Math.max(...numbers) + 1 : 0}`
}

/** GET /transcripts/<task_uuid> 的形狀。 */
export const transcript = (taskUuid, segments, fields = {}) => ({
    task_uuid: taskUuid, status: 'COMPLETED', original_filename: 'meeting.wav', audio_duration_seconds: 20.0,
    audio_available: true, correctable: true, uncorrectable_reason: null, single_speaker: false,
    next_speaker: nextSpeakerOf(segments.flatMap((s) => [s.speaker, s.original_speaker])),
    segment_count: segments.length, segments, ...fields,
})

export const MEETING = [
    segment(0, 0.5, 3.5, 'S0', '大家早安，今天先看進度。'),
    segment(1, 4.0, 7.5, 'S1', '前端的校正頁可以播放了。'),
    segment(2, 7.0, 9.0, 'S0', '等一下。'),
    segment(3, 10.0, 14.0, 'S1', '點一個字就從那個字開始。'),
]

/**
 * task-1 的保留音檔：和後端的 FileResponse 一樣支援 Range（只回整個檔時 Chromium 不讓播放器跳到別的時間）。
 * 假後端只回 JSON 與文字，所以另外攔；比假後端晚註冊的攔截先處理。
 */
export async function serveAudio(page, seconds) {
    const wav = silentWav(seconds)
    await page.route('**/api/v1/transcripts/task-1/audio', (route) => {
        const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers().range ?? '')
        const headers = { 'Accept-Ranges': 'bytes' }
        if (!range) return route.fulfill({ status: 200, contentType: 'audio/wav', headers, body: wav })
        const start = Number(range[1])
        const end = range[2] ? Number(range[2]) : wav.length - 1
        return route.fulfill({
            status: 206, contentType: 'audio/wav', headers: { ...headers, 'Content-Range': `bytes ${start}-${end}/${wav.length}` },
            body: wav.subarray(start, end + 1),
        })
    })
}

/** 校正頁的假後端：任務 task-1 的片段與保留音檔，再加上 routes。 */
export async function openCorrection(page, mockBackend, { segments = MEETING, fields = {}, seconds = 20, routes = {}, audio = true } = {}) {
    const backend = await mockBackend({
        routes: { 'GET /transcripts/task-1': transcript('task-1', segments, fields), ...routes },
    })
    if (audio) await serveAudio(page, seconds)
    await page.goto('/correction/task-1')
    return backend
}

export const audioState = (page) => page.locator('audio').evaluate((a) => ({ time: a.currentTime, paused: a.paused, rate: a.playbackRate }))
/** 文字裡有 text 的那一列（正在改的那一列文字在文字框裡，用 rowAt 找）。 */
export const row = (page, text) => page.locator('[data-index]', { hasText: text })
/** 第 index 列（從 0 起）。 */
export const rowAt = (page, index) => page.locator(`[data-index="${index}"]`)
/** 那一列反白時找得到一個元素，沒有反白時是 0 個。 */
export const highlight = (page, text) => row(page, text).locator('[data-active]')

/** 和後端存的時候同一個規則（backend/app/api/transcripts.py 的 _LINE_BREAKS 與 _normalized_text）。 */
// eslint-disable-next-line no-control-regex -- 垂直定位、換頁與分隔字元是 str.splitlines 當成換行的字元，和後端同一組
const normalized = (text) => text.trim().replace(/\s*[\n\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]+\s*/gu, ' ')

/**
 * 全部取代的比對（backend/app/core/text_replacement.py 的規則）：一般文字比對、英文字母不分大小寫（全形與半形
 * 不同）、從左到右不重疊。回 [換好的文字, 換了幾處]。
 */
function replaceText(text, find, replacement) {
    const fold = (value) => value.replace(/[A-ZＡ-Ｚ]/g, (c) => String.fromCharCode(c.charCodeAt(0) + 0x20))
    const parts = fold(text).split(fold(find))
    if (parts.length === 1) return [text, 0]
    let pos = 0
    const pieces = parts.map((part) => {
        const piece = text.slice(pos, pos + part.length)
        pos += part.length + find.length
        return piece
    })
    return [pieces.join(replacement), parts.length - 1]
}

/**
 * 記得每次校正的假後端（#348、#354、#355、#356）：照 ADR 0011 的規則，每次校正記一筆校正紀錄（和現在的內容相同的
 * 不記），校正後版本由原始轉錄加上最新的紀錄算出來，GET、PATCH、把這位說話者全部換成另一位、全部取代、復原與片段的
 * 歷程讀的都是同一份。「整份當成同一位說話者」的切換是任務的設定，記在 settings，不留紀錄。回傳的 routes 交給
 * mockBackend；records 是記下的紀錄，settings 是任務的設定，給測試檢查；bulk 直接記一次改很多個片段的操作，回傳
 * 操作編號。
 *
 * @param {ReturnType<typeof segment>[]} segments 原始轉錄
 */
export function correctionsBackend(segments, fields = {}) {
    const originals = new Map(segments.map((s) => [s.seg_key, s]))
    const settings = { single_speaker: Boolean(fields.single_speaker), speaker_count: fields.speaker_count ?? null }
    /** @type {{ id: number, seg_key: string, field: 'text' | 'speaker', before: string | null, after: string | null,
     *   operation_id: string, created_at: string }[]} */
    const records = []
    let operations = 0

    const current = (segKey, field) => {
        const latest = records.findLast((r) => r.seg_key === segKey && r.field === field)
        return latest ? latest.after : originals.get(segKey)[field]
    }
    const view = (segKey) => {
        const original = originals.get(segKey)
        const text = current(segKey, 'text') ?? ''
        const speaker = current(segKey, 'speaker')
        const latestText = records.findLast((r) => r.seg_key === segKey && r.field === 'text')
        const deleted = !text
        return {
            ...original, text, speaker,
            corrected: text !== original.text || speaker !== original.speaker,
            deleted,
            deleted_text: deleted && latestText ? latestText.before : null,
            has_correction_records: records.some((r) => r.seg_key === segKey),
            // 改過文字的片段，逐字時間照校正後的文字重算（#357）；這裡照字數平均分，刪掉的沒有
            words: text === original.text ? original.words : (deleted ? null : wordsOf(text, original.start, original.end)),
        }
    }
    const record = (segKey, field, after, operationId) => {
        const before = current(segKey, field)
        if (before === after) return false
        // 後端寫伺服器的本地時間，到秒、不帶時區；每一筆隔一分鐘，畫面上才分得出先後
        const created = new Date(2026, 10, 15, 21, records.length, 5)
        const pad = (n) => String(n).padStart(2, '0')
        const createdAt = `${created.getFullYear()}-${pad(created.getMonth() + 1)}-${pad(created.getDate())}`
            + `T${pad(created.getHours())}:${pad(created.getMinutes())}:${pad(created.getSeconds())}`
        records.push({ id: records.length + 1, seg_key: segKey, field, before, after, operation_id: operationId, created_at: createdAt })
        return true
    }
    /** 那次操作一共有幾筆、改到幾個片段（backend/app/schemas/schemas.py 的 CorrectionRecordResponse）。 */
    const operationSize = (operationId) => {
        const same = records.filter((r) => r.operation_id === operationId)
        return { operation_record_count: same.length, operation_segment_count: new Set(same.map((r) => r.seg_key)).size }
    }

    const nextSpeaker = () => nextSpeakerOf([
        ...segments.map((s) => s.speaker), ...records.filter((r) => r.field === 'speaker').map((r) => r.after),
    ])

    return {
        records,
        settings,
        /** @param {[string, 'text' | 'speaker', string | null][]} changes [片段鍵, 改了什麼, 改後] */
        bulk(changes) {
            const operationId = `op-${operations += 1}`
            for (const [segKey, field, after] of changes) record(segKey, field, after, operationId)
            return operationId
        },
        routes: {
            'GET /transcripts/task-1': () => transcript('task-1', segments.map((s) => view(s.seg_key)), {
                ...fields, ...settings, next_speaker: nextSpeaker(),
            }),
            'PATCH /transcripts/task-1': ({ body }) => {
                // 和後端的 _set_single_speaker 相同：整份當成同一位寫 1 人；切到照模型分出的說話者顯示寫 'auto'，
                // 本來就顯示的不改人數
                if (body.single_speaker) settings.speaker_count = 1
                else if (settings.single_speaker) settings.speaker_count = 'auto'
                settings.single_speaker = body.single_speaker
                return { ...settings }
            },
            'POST /transcripts/task-1/speakers/reassign': ({ body }) => {
                const operationId = `op-${operations += 1}`
                const changed = segments.map((s) => s.seg_key).filter((segKey) => (
                    (current(segKey, 'speaker') ?? null) === (body.from_speaker ?? null)
                    && record(segKey, 'speaker', body.to_speaker, operationId)
                ))
                return { operation_id: changed.length ? operationId : null, changed: changed.length, segments: changed.map(view) }
            },
            'PATCH /transcripts/task-1/segments/:seg_key': ({ params, body }) => {
                const operationId = `op-${operations += 1}`
                let recorded = false
                if ('text' in body) recorded = record(params.seg_key, 'text', normalized(body.text), operationId) || recorded
                if ('speaker' in body) recorded = record(params.seg_key, 'speaker', body.speaker, operationId) || recorded
                return { operation_id: recorded ? operationId : null, segment: view(params.seg_key) }
            },
            'POST /transcripts/task-1/replace-all': ({ body }) => {
                const operationId = `op-${operations += 1}`
                const changed = []
                let occurrences = 0
                for (const { seg_key: segKey } of segments) {
                    const text = current(segKey, 'text') ?? ''
                    if (!text.trim()) continue
                    const [replaced, count] = replaceText(text, body.find, body.replacement)
                    if (count && record(segKey, 'text', normalized(replaced), operationId)) {
                        changed.push(segKey)
                        occurrences += count
                    }
                }
                return {
                    operation_id: changed.length ? operationId : null, changed_segments: changed.length, occurrences,
                    segments: changed.map(view),
                }
            },
            'POST /transcripts/task-1/operations/:operation_id/undo': ({ params }) => {
                const undoId = `op-${operations += 1}`
                const undone = records.filter((r) => r.operation_id === params.operation_id).reverse()
                let restored = 0
                for (const r of undone) {
                    if (current(r.seg_key, r.field) !== r.after) continue
                    record(r.seg_key, r.field, r.before, undoId)
                    restored += 1
                }
                const segKeys = [...new Set(undone.map((r) => r.seg_key))]
                return {
                    restored, skipped: undone.length - restored, operation_id: restored ? undoId : null,
                    segments: segKeys.map(view),
                }
            },
            'GET /transcripts/task-1/segments/:seg_key/correction-records': ({ params }) => {
                const original = originals.get(params.seg_key)
                return {
                    seg_key: params.seg_key, original_text: original.text, original_speaker: original.speaker,
                    records: records.filter((r) => r.seg_key === params.seg_key).map((r) => ({
                        id: r.id, field: r.field, old_value: r.before, new_value: r.after, operation_id: r.operation_id,
                        created_at: r.created_at, ...operationSize(r.operation_id),
                    })),
                }
            },
        },
    }
}
