/**
 * 瀏覽器測試用的假後端：在瀏覽器裡攔下 /api/v1 的請求與轉錄的 WebSocket，回固定資料。
 *
 * 不連真的後端、資料庫或任何供應商。資料的形狀照後端實際的回應（免安裝模式下用 curl 取得），
 * 欄位一改名，這裡要跟著改；畫面讀哪些欄位見 src/services/api.js 與 src/utils/providerList.js。
 */

/** GET /providers：Gemini 要金鑰、支援提示詞與三種處理模式；本機不要金鑰，只有標準。 */
export const PROVIDERS = [
    {
        provider: 'google',
        label: 'Gemini',
        requires_api_key: true,
        models: [
            {
                model: 'gemini-3.5-flash',
                label: 'gemini-3.5-flash',
                capabilities: {
                    single_pass_seconds: 900.0, queue: 'celery', can_terminate: true,
                    split_retry_on_failure: true, accepts_prompt: true, accepts_user_text: true,
                    supports_batch: true, supports_flex: true, pricing: 'per_token', remove_silence: true,
                },
            },
        ],
    },
    {
        provider: 'local',
        label: '本機',
        requires_api_key: false,
        models: [
            {
                model: 'moss-align',
                label: 'MOSS-Transcribe-Diarize',
                capabilities: {
                    single_pass_seconds: 4200.0, queue: 'local_asr', can_terminate: false,
                    split_retry_on_failure: false, accepts_prompt: false, accepts_user_text: false,
                    supports_batch: false, supports_flex: false, pricing: 'free', remove_silence: true,
                },
            },
        ],
    },
]

/** 後端回給畫面的金鑰只有遮罩值（前後 4 碼），明文不會出現在任何回應裡。 */
export const MASKED_KEY = 'AIza********wxyz'

/** 一個任務完成時的四種輸出格式（WebSocket 的 result.transcripts，也是下載端點的內容）。 */
export const TRANSCRIPTS = {
    lrc: '[00:00.000][S0]測試的第一句\n[00:02.500][S0]測試的第二句\n',
    srt: '1\n00:00:00,000 --> 00:00:02,500\n[S0]測試的第一句\n\n2\n00:00:02,500 --> 00:00:05,000\n[S0]測試的第二句\n',
    vtt: 'WEBVTT\n\n00:00:00.000 --> 00:00:02.500\n[S0]測試的第一句\n\n00:00:02.500 --> 00:00:05.000\n[S0]測試的第二句\n',
    txt: '[S0]測試的第一句\n[S0]測試的第二句\n',
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
    'GET /setting/models/google': { provider: 'Google', apiKeys: [MASKED_KEY], model: 'gemini-3.5-flash', prompt: null },
    'GET /setting/models/local': { provider: 'Local', apiKeys: [], model: null, prompt: null },
    // Docker 模式的回應：設定頁不顯示本機模型權重的卡片
    'GET /setting/local-models/status': { standalone: false },
    'GET /history/usage': { daily: [], by_model: [], pricing: [] },
    'GET /history/stats': EMPTY_STATS,
    'GET /history': { items: [], total: 0, page: 1, page_size: 10, total_pages: 1 },
    'GET /history/active': [],
    'GET /batch/tasks': [],
}

/** 指定狀態碼的回應；body 是物件時以 JSON 回，字串時以純文字回。 */
export const reply = (status, body) => ({ [REPLY]: true, status, body })
const REPLY = Symbol('reply')

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

/**
 * 單檔任務的 WebSocket 預設怎麼回：收到請求就回處理中，接著回完成與四種輸出格式。
 * send 送一則狀態訊息（形狀照後端的 publish_status）。
 */
export async function completeTranscription(request, send) {
    const task_uuid = `task-${request.file_uid}`
    send({ task_uuid, status_code: 'PROCESSING', status_text: '轉錄中...', file_uid: request.file_uid })
    send({
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
        },
    })
}

/**
 * 換上假後端。routes 蓋過 {@link DEFAULT_ROUTES} 的同名端點；transcribe(request, send) 決定
 * 單檔任務的 WebSocket 收到請求後怎麼回，預設是 {@link completeTranscription}。
 *
 * 回傳的物件記下畫面送出的東西，給測試檢查：
 *   - requests：每個 /api/v1 請求的 { method, path, query, body }
 *   - transcriptions：從單檔任務的 WebSocket 收到的請求（已解析的 JSON，不含心跳）
 *   - unhandled：沒有設定回應的請求（回 404）；測試結束時要是空的，見 e2e/support/test.js
 */
export async function mockBackend(page, { routes = {}, transcribe = completeTranscription } = {}) {
    const table = { ...DEFAULT_ROUTES, ...routes }
    const backend = { requests: [], transcriptions: [], unhandled: [] }

    // 對外的連線（Google Fonts 等）一律擋掉：測試不依賴網路
    await page.route((url) => url.hostname !== '127.0.0.1' && url.hostname !== 'localhost',
        (route) => route.abort())

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

    await page.routeWebSocket('**/api/v1/ws/*', (ws) => {
        ws.onMessage(async (message) => {
            const data = JSON.parse(String(message))
            if (data.type === 'ping') return
            backend.transcriptions.push(data)
            const file_uid = new URL(ws.url()).pathname.split('/').pop()
            await transcribe({ ...data, file_uid }, (payload) => ws.send(JSON.stringify(payload)))
        })
    })

    return backend
}
