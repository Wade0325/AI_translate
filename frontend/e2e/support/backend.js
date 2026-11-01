/**
 * 瀏覽器測試用的假後端：在瀏覽器裡攔下 /api 的請求與 WebSocket，回固定資料。
 *
 * 不連真的後端、資料庫或任何供應商。資料的形狀照後端實際的回應（免安裝模式下用 curl 取得），
 * 欄位一改名，這裡要跟著改；畫面讀哪些欄位見 src/services/api.js 與 src/utils/providerList.js。
 */

/** Gemini 的上傳告知（#231 Q6）：選 Gemini 時，設定頁與轉錄頁照這段文字告訴使用者，並連到條款原文。 */
export const GEMINI_UPLOAD_NOTICE = {
    text: '音檔與提示詞會上傳到 Google。金鑰所屬的專案沒有啟用計費時（免費層），'
        + 'Google 可能拿這些內容改善產品，也可能由人工審閱；條款要求不要送出敏感或個人資訊。',
    terms_url: 'https://ai.google.dev/gemini-api/terms',
}

/**
 * GET /providers：本機在第一個，是預設（#11 Q1）。本機在使用者的電腦上轉錄，不要金鑰，只有標準，
 * 也不去靜音（#95），音檔不送出；Gemini 要金鑰、支援提示詞與三種處理模式，音檔會上傳。兩邊都
 * 不吃使用者文稿（#66 修好之前 Gemini 也不吃）。
 */
export const PROVIDERS = [
    {
        provider: 'local',
        label: '本機',
        requires_api_key: false,
        checks_transcribing_machine: true,
        upload_notice: null,
        models: [
            {
                model: 'moss-align',
                label: 'MOSS-Transcribe-Diarize',
                capabilities: {
                    single_pass_seconds: 4200.0, queue: 'local_asr', can_terminate: false,
                    split_retry_on_failure: false, accepts_prompt: false, accepts_user_text: false,
                    supports_batch: false, supports_flex: false, pricing: 'free', remove_silence: false,
                },
            },
        ],
    },
    {
        provider: 'google',
        label: 'Gemini',
        requires_api_key: true,
        checks_transcribing_machine: false,
        upload_notice: GEMINI_UPLOAD_NOTICE,
        models: [
            {
                model: 'gemini-3.5-flash',
                label: 'gemini-3.5-flash',
                capabilities: {
                    single_pass_seconds: 900.0, queue: 'celery', can_terminate: true,
                    split_retry_on_failure: true, accepts_prompt: true, accepts_user_text: false,
                    supports_batch: true, supports_flex: true, pricing: 'per_token', remove_silence: true,
                },
            },
        ],
    },
]

/**
 * GET /setting/local-models/readiness：免安裝模式的回應（checked: true）。預設的路由用的是
 * Docker 模式的回應（沒有查），轉錄頁不提示也不擋；要模擬這台電腦的狀況時用這個組。
 */
export const readiness = (fields) => ({
    checked: true, ready: true, reason: null, message: null, vram_notice: null, ...fields,
})

/** 後端回給畫面的金鑰只有遮罩值（前後 4 碼），明文不會出現在任何回應裡。 */
export const MASKED_KEY = 'AIza********wxyz'

/** 設定頁讀到的 Gemini 設定：已存過一把金鑰，還沒存過提示詞。 */
export const GOOGLE_CONFIG = { provider: 'Google', apiKeys: [MASKED_KEY], model: 'gemini-3.5-flash', prompt: null }

/** 一個任務完成時的四種輸出格式（WebSocket 的 result.transcripts，也是下載端點的內容）。 */
export const TRANSCRIPTS = {
    lrc: '[00:00.000][S0]測試的第一句\n[00:02.500][S0]測試的第二句\n',
    srt: '1\n00:00:00,000 --> 00:00:02,500\n[S0]測試的第一句\n\n2\n00:00:02,500 --> 00:00:05,000\n[S0]測試的第二句\n',
    vtt: 'WEBVTT\n\n00:00:00.000 --> 00:00:02.500\n[S0]測試的第一句\n\n00:00:02.500 --> 00:00:05.000\n[S0]測試的第二句\n',
    txt: '[S0]測試的第一句\n[S0]測試的第二句\n',
}

/**
 * GET /local-data：Docker 模式的回應（沒有單一的資料夾），保留區裡還沒有音檔。免安裝模式另外有
 * data_folder，見 e2e/settings.spec.js。
 */
export const LOCAL_DATA = {
    data_folder: null,
    retained_audio: { enabled: true, retention_days: 30, folder: '/app/audio_store', file_count: 0, total_bytes: 0 },
}

const EMPTY_STATS = {
    total_tasks: 0, completed_tasks: 0, failed_tasks: 0, success_rate: 0.0, total_cost: 0.0,
    total_tokens: 0, total_audio_duration_seconds: 0.0, avg_processing_time_seconds: 0.0,
}

/**
 * 沒有另外指定時各端點的回應。鍵是「方法 路徑」（路徑不含 /api/v1 與查詢字串），值是 JSON
 * 內容，或 {@link reply} 包好的回應，或收到請求後才決定回應的函式。
 */
const DEFAULT_ROUTES = {
    'GET /providers': PROVIDERS,
    'GET /version': { version: 'v0.1.0-test' },
    'GET /setting/models/google': GOOGLE_CONFIG,
    'GET /setting/models/local': { provider: 'Local', apiKeys: [], model: null, prompt: null },
    // Docker 模式的回應：設定頁不顯示本機模型權重的卡片，轉錄頁不問這台電腦能不能轉錄（#11）
    'GET /setting/local-models/status': { standalone: false },
    'GET /setting/local-models/readiness': {
        checked: false, ready: null, reason: null, message: null, vram_notice: null,
    },
    'GET /local-data': LOCAL_DATA,
    'GET /history/usage': { daily: [], by_model: [], pricing: [] },
    'GET /history/stats': EMPTY_STATS,
    'GET /history': { items: [], total: 0, page: 1, page_size: 10, total_pages: 1 },
    'GET /history/active': [],
    'GET /batch/tasks': [],
    // 去靜音與切點預覽是開發者工具，預設沒開（#13 Q6）
    'GET /vad/enabled': { enabled: false },
}

const REPLY = Symbol('reply')

/** 指定狀態碼的回應；body 是物件時以 JSON 回，字串時以純文字回。 */
export const reply = (status, body) => ({ [REPLY]: true, status, body })

function toFulfill(response) {
    const { status, body } = response?.[REPLY] ? response : { status: 200, body: response }
    return typeof body === 'string'
        ? { status, contentType: 'text/plain; charset=utf-8', body }
        : { status, json: body }
}

/** 請求的內容：JSON 就解析，其他（例如上傳音檔的 multipart）照原樣；沒有內容時是 null。 */
function requestBody(request) {
    try {
        return request.postDataJSON()
    } catch {
        return request.postData()
    }
}

/** 後端派送單檔任務之前先送的排隊中（backend/app/api/transcription.py 的 QUEUED_TEXT）。 */
export const QUEUED_TEXT = '排隊中，輪到時開始轉錄...'

/** 派送前出了非預期的錯誤時，後端給的固定訊息（backend/app/api/transcription.py 的 SUBMISSION_FAILED_TEXT）。 */
export const SUBMISSION_FAILED_TEXT = '提交任務失敗，任務沒有開始。請重新轉錄；一直失敗時，請到設定頁回報問題並附上日誌'

/**
 * 單檔任務收到請求後，後端依序送出的三則狀態訊息（形狀照後端的 publish_status）：
 * queued 是派送前的排隊中，processing 是處理中，completed 是完成並帶四種輸出格式。
 */
export function transcriptionMessages(request) {
    const task_uuid = `task-${request.file_uid}`
    return {
        queued: { task_uuid, status_code: 'PROCESSING', status_text: QUEUED_TEXT, file_uid: request.file_uid },
        processing: { task_uuid, status_code: 'PROCESSING', status_text: '轉錄中...', file_uid: request.file_uid },
        completed: {
            task_uuid,
            status_code: 'COMPLETED',
            status_text: '轉錄完成',
            file_uid: request.file_uid,
            result: {
                task_uuid,
                transcripts: TRANSCRIPTS,
                tokens_used: 0,
                cost: 0.0,
                model: request.model,
                source_language: request.source_lang,
                audio_duration_seconds: 5.0,
                speaker_count: 2,
            },
        },
    }
}

/** 單檔任務的 WebSocket 預設怎麼回：排隊中、處理中之後馬上完成。send 送一則狀態訊息。 */
async function completeTranscription(request, send) {
    const { queued, processing, completed } = transcriptionMessages(request)
    send(queued)
    send(processing)
    send(completed)
}

/** 單檔任務的 WebSocket：/api/v1/ws/<file_uid> */
const TRANSCRIPTION_SOCKET = /^\/api\/v1\/ws\/[^/]+$/

/** 連線中斷之後接回任務的 WebSocket：/api/v1/ws/<file_uid>/tasks/<task_uuid>（#280） */
const REATTACH_SOCKET = /^\/api\/v1\/ws\/([^/]+)\/tasks\/([^/]+)$/

/** 批次的 WebSocket：/api/v1/batch/ws/<batch_id> */
const BATCH_SOCKET = /^\/api\/v1\/batch\/ws\/[^/]+$/

/** 連線中斷之後接回批次的 WebSocket：/api/v1/batch/ws/<batch_id>/reattach（#286） */
const BATCH_REATTACH_SOCKET = /^\/api\/v1\/batch\/ws\/([^/]+)\/reattach$/

/**
 * 換上假後端。routes 蓋過 {@link DEFAULT_ROUTES} 的同名端點；transcribe(request, send, close) 決定
 * 單檔任務的 WebSocket 收到請求後怎麼回，預設是 {@link completeTranscription}；
 * batch(request, send, close) 決定批次的 WebSocket 怎麼回，沒給時批次的 WebSocket 算沒有設定；
 * reattach({ file_uid, task_uuid }, send, close) 決定連線中斷之後接回任務的 WebSocket 一連上怎麼回，
 * batchReattach(batch_id, send, close) 決定接回批次的 WebSocket 一連上怎麼回；兩個都是每連一次呼叫一次，
 * 沒給時那條 WebSocket 算沒有設定。
 * send 送一則狀態訊息，close 從伺服器那一端關掉連線。
 *
 * 回傳的物件記下畫面送出的東西，給測試檢查：
 *   - requests：每個 /api/v1 請求的 { method, path, query, body }
 *   - transcriptionRequests：從單檔任務的 WebSocket 收到的請求（已解析的 JSON，不含心跳）
 *   - reattachments：每次接回任務的 WebSocket 連上時的 { file_uid, task_uuid }
 *   - batchReattachments：每次接回批次的 WebSocket 連上時的 batch_id
 *   - unhandled：沒有設定回應的請求（回 404）與 WebSocket（直接關掉）；測試結束時要是空的，
 *     見 e2e/support/test.js
 *   - external：畫面向本機以外要的資源（網址）；測試結束時也要是空的
 */
export async function mockBackend(page, {
    routes = {}, transcribe = completeTranscription, batch, reattach, batchReattach,
} = {}) {
    const table = { ...DEFAULT_ROUTES, ...routes }
    const backend = {
        requests: [], transcriptionRequests: [], reattachments: [], batchReattachments: [], unhandled: [], external: [],
    }

    // 對外的連線一律擋掉並記下來：app 不收遙測（ADR-0005），開頁面也不該向第三方要資源，
    // 例如 Google Fonts（#16 Q3）。只有使用者點了才開的外部連結（像 GitHub Releases）不算
    await page.route((url) => url.hostname !== '127.0.0.1' && url.hostname !== 'localhost',
        (route) => {
            backend.external.push(route.request().url())
            return route.abort()
        })

    await page.route('**/api/v1/**', async (route) => {
        const request = route.request()
        const url = new URL(request.url())
        const path = url.pathname.replace(/^\/api\/v1/, '')
        const key = `${request.method()} ${path}`
        const entry = {
            method: request.method(), path, query: Object.fromEntries(url.searchParams), body: requestBody(request),
        }
        backend.requests.push(entry)

        if (!(key in table)) {
            backend.unhandled.push(key)
            await route.fulfill({ status: 404, json: { detail: `假後端沒有設定 ${key}` } })
            return
        }
        const handler = table[key]
        const response = typeof handler === 'function' ? await handler(entry) : handler
        await route.fulfill(toFulfill(response))
    })

    // /api 底下的 WebSocket 全部攔下，沒有一條會經 vite 的 proxy 接到真的後端。模擬單檔任務，以及
    // 測試給了 batch、reattach、batchReattach 時的批次、接回任務與接回批次；其他的記成沒有設定，直接關掉
    await page.routeWebSocket((url) => url.pathname.startsWith('/api/'), (ws) => {
        const path = new URL(ws.url()).pathname
        const id = path.split('/').pop()
        const send = (payload) => ws.send(JSON.stringify(payload))
        const close = () => ws.close()
        const reattaching = REATTACH_SOCKET.exec(path)
        const reattachingBatch = BATCH_REATTACH_SOCKET.exec(path)
        if (batchReattach && reattachingBatch) {
            // 伺服器一連上就先回批次現在的狀態；畫面送來的只有心跳
            backend.batchReattachments.push(reattachingBatch[1])
            ws.onMessage(() => {})
            batchReattach(reattachingBatch[1], send, close)
        } else if (reattach && reattaching) {
            // 伺服器一連上就先回任務現在的狀態；畫面送來的只有心跳
            const task = { file_uid: reattaching[1], task_uuid: reattaching[2] }
            backend.reattachments.push(task)
            ws.onMessage(() => {})
            reattach(task, send, close)
        } else if (TRANSCRIPTION_SOCKET.test(path)) {
            ws.onMessage(async (message) => {
                const data = JSON.parse(String(message))
                if (data.type === 'ping') return
                backend.transcriptionRequests.push(data)
                await transcribe({ ...data, file_uid: id }, send, close)
            })
        } else if (batch && BATCH_SOCKET.test(path)) {
            ws.onMessage(async (message) => {
                const data = JSON.parse(String(message))
                if (data.type === 'ping') return
                await batch({ ...data, batch_id: id }, send, close)
            })
        } else {
            backend.unhandled.push(`WebSocket ${path}`)
            ws.close()
        }
    })

    return backend
}
