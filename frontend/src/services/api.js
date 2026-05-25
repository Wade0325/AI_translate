/**
 * 統一的後端 API 客戶端。
 *
 * 之前各 page / context 自己用 fetch + 散落的 baseURL，現在全部集中在這裡，
 * 維持單一錯誤格式並讓 endpoint 變更時只改一處。
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
    delete(taskUuid) {
      return request(`/history/${taskUuid}`, { method: 'DELETE' });
    },
    /** 下載字幕檔（fmt: lrc | srt | vtt | txt），回傳純文字內容 */
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
  batch: (id) => `${DEFAULT_WS_BATCH_BASE}/${id}`,
};

export { BASE_URL as API_BASE_URL };
