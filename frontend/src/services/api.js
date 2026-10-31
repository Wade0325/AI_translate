// @ts-nocheck
/**
 * 統一的後端 API 客戶端：集中 baseURL 與錯誤格式，endpoint 變更時只改此檔。
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

const wsProtocol =
  typeof window !== 'undefined' && window.location.protocol === 'https:'
    ? 'wss:'
    : 'ws:';
const wsHost = typeof window !== 'undefined' ? window.location.host : '';

const DEFAULT_WS_BASE =
  import.meta.env.VITE_WS_BASE_URL || `${wsProtocol}//${wsHost}/api/v1/ws`;
const DEFAULT_WS_BATCH_BASE =
  import.meta.env.VITE_WS_BATCH_URL ||
  `${wsProtocol}//${wsHost}/api/v1/batch/ws`;

export class ApiError extends Error {
  constructor(status, message, payload) {
    super(message || `Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

async function request(path, { method = 'GET', body, headers, ...rest } = {}) {
  const init = {
    method,
    headers: { ...(headers || {}) },
    ...rest,
  };

  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined && body !== null) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  const res = await fetch(`${BASE_URL}${path}`, init);

  if (!res.ok) {
    let payload = null;
    try {
      payload = await res.json();
    } catch {
      /* response body may not be JSON */
    }
    const message = payload?.detail || payload?.message || res.statusText;
    throw new ApiError(res.status, message, payload);
  }

  if (res.status === 204) return null;
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

export const api = {
  upload(formData) {
    return request('/upload', { method: 'POST', body: formData });
  },
  transcription: {
    cancel(fileUid) {
      return request(`/transcription/${fileUid}/cancel`, { method: 'POST' });
    },
  },
  /** 供應商、它們的模型與每個模型的模型能力 */
  providers() {
    return request('/providers');
  },
  /** app 的版本號：{ version }；免安裝版是發布的 tag，從原始碼執行時是 dev */
  version() {
    return request('/version');
  },
  /** 設定頁「複製診斷資訊」：{ text }，回報問題時貼進 GitHub Issue；不含檔名、金鑰、路徑與轉錄內容 */
  diagnostics() {
    return request('/diagnostics');
  },
  history: {
    list({ page = 1, pageSize = 10, keyword, status, mode } = {}) {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (keyword) params.append('keyword', keyword);
      if (status) params.append('status', status);
      if (mode === 'batch') params.append('is_batch', 'true');
      else if (mode === 'regular') params.append('is_batch', 'false');
      return request(`/history?${params.toString()}`);
    },
    stats() {
      return request('/history/stats');
    },
    /** Billing 頁與轉錄頁費用估算的用量彙總：每日、各模型、計費表 */
    usage({ days = 180 } = {}) {
      return request(`/history/usage?days=${days}`);
    },
    /** 單一任務的任務紀錄（不帶轉錄結果）；查不到時丟 404 的 ApiError */
    get(taskUuid) {
      return request(`/history/${taskUuid}`);
    },
    delete(taskUuid) {
      return request(`/history/${taskUuid}`, { method: 'DELETE' });
    },
    /** 以一種輸出格式下載轉錄結果（fmt: lrc | srt | vtt | txt），回傳純文字內容 */
    async downloadTranscript(taskUuid, fmt) {
      const res = await fetch(`${BASE_URL}/history/${taskUuid}/download/${fmt}`);
      if (!res.ok) {
        let payload = null;
        try {
          payload = await res.json();
        } catch {
          /* ignore */
        }
        const message = payload?.detail || res.statusText;
        throw new ApiError(res.status, message, payload);
      }
      return res.text();
    },
    activeSingle({ hours = 6 } = {}) {
      return request(`/history/active?hours=${hours}`);
    },
  },
  batch: {
    tasks() {
      return request('/batch/tasks');
    },
    recover(batchId, body = {}) {
      return request(`/batch/${batchId}/recover`, { method: 'POST', body });
    },
    dismiss(batchId) {
      return request(`/batch/${batchId}/dismiss`, { method: 'POST' });
    },
  },
  vad: {
    /** 去靜音與切點預覽（開發者工具）有沒有開：{ enabled } */
    enabled() {
      return request('/vad/enabled');
    },
    test({ filename, originalFilename, includeSplit = true }) {
      return request('/vad/test', {
        method: 'POST',
        body: {
          filename,
          original_filename: originalFilename,
          include_split: includeSplit,
        },
      });
    },
  },
  localModels: {
    /** 免安裝模式的本機模型權重狀態（GPU、各 repo 下載進度） */
    status() {
      return request('/setting/local-models/status');
    },
    /**
     * 轉錄頁選本機時先問的事（#11）：現在能不能用這個模型轉錄，不能時的原因與 reason，以及顯卡
     * 記憶體的提示；Docker 模式回 checked: false。內容怎麼呈現見 utils/localReadiness.js
     */
    readiness(model) {
      return request(`/setting/local-models/readiness?model=${encodeURIComponent(model)}`);
    },
    /** 啟動（或續傳）權重下載；model 省略＝預設模型所需，'all'＝含選用模型 */
    download(model) {
      const query = model ? `?model=${encodeURIComponent(model)}` : '';
      return request(`/setting/local-models/download${query}`, { method: 'POST' });
    },
  },
  /** 設定頁「資料與隱私」：資料放在哪、保留音檔的設定與用量（#231 Q1、Q7） */
  localData: {
    get() {
      return request('/local-data');
    },
    /** 立即刪除全部保留音檔：{ deleted, failed } */
    deleteRetainedAudio() {
      return request('/local-data/retained-audio', { method: 'DELETE' });
    },
  },
  settings: {
    getProvider(provider) {
      return request(`/setting/models/${provider}`);
    },
    saveProvider(payload) {
      return request('/setting/models', { method: 'POST', body: payload });
    },
    testProvider(payload) {
      return request('/setting/test', { method: 'POST', body: payload });
    },
    defaultPrompt() {
      return request('/setting/default-prompt');
    },
  },
};

export const WS_URLS = {
  transcription: (id) => `${DEFAULT_WS_BASE}/${id}`,
  /** 連線中斷之後接回這個檔案已經送出的單檔任務（#280）：連上就先收到任務現在的狀態 */
  reattach: (id, taskUuid) => `${DEFAULT_WS_BASE}/${id}/tasks/${taskUuid}`,
  batch: (id) => `${DEFAULT_WS_BATCH_BASE}/${id}`,
};
