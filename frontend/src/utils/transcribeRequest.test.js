import { describe, expect, it } from 'vitest';
import { buildBatchPayload, buildSinglePayload } from './transcribeRequest.js';

// 轉錄頁按 Start 時的設定：全域預設（含全域提示詞）與所選的模型支援的輸入
const DEFAULTS = { sourceLang: 'ja-JP', multiSpeaker: false, serviceTier: null, prompt: '人名照寫：佐藤' };
const TAKES_PROMPT = { prompt: true, userText: true, batch: true };
const NO_PROMPT = { prompt: false, userText: false, batch: false };

// 剛加進來、沒動過每檔設定的檔案
const untouched = (overrides = {}) => ({ uid: 'f1', name: 'a.wav', ...overrides });

function singlePrompt({ file = untouched(), defaults = DEFAULTS, promptTemplate = null, supports = TAKES_PROMPT } = {}) {
  return buildSinglePayload({
    serverFilename: 'srv-a.wav', file, provider: 'google', model: 'gemini-2.5-flash',
    promptTemplate, defaults, supports, sessionId: 's1',
  }).prompt;
}

describe('單檔任務送出的提示詞', () => {
  it('沒有自己設定提示詞的檔案，帶全域提示詞（不必先按 Apply to All）', () => {
    expect(singlePrompt({ promptTemplate: '設定頁的範本' })).toBe('人名照寫：佐藤');
  });

  it('自己設定了提示詞的檔案，帶自己的', () => {
    expect(singlePrompt({ file: untouched({ prompt: '這個檔案是關西腔' }) })).toBe('這個檔案是關西腔');
  });

  it('自己的提示詞清成空白時不會被全域的補上，和檔案卡顯示的一樣：改帶提示詞範本', () => {
    expect(singlePrompt({ file: untouched({ prompt: '' }), promptTemplate: '設定頁的範本' }))
      .toBe('設定頁的範本');
  });

  it('全域與自己的都沒填時，帶供應商的提示詞範本；只有空白也算沒填', () => {
    for (const globalPrompt of ['', ' \n']) {
      expect(singlePrompt({ defaults: { ...DEFAULTS, prompt: globalPrompt }, promptTemplate: '設定頁的範本' }))
        .toBe('設定頁的範本');
    }
  });

  it('什麼都沒填時不帶，由後端用預設範本', () => {
    expect(singlePrompt({ defaults: { ...DEFAULTS, prompt: '' }, promptTemplate: '' })).toBeNull();
  });

  it('所選的模型不吃提示詞時一律不帶（#108）', () => {
    expect(singlePrompt({ supports: NO_PROMPT, promptTemplate: '設定頁的範本' })).toBeNull();
    expect(singlePrompt({ supports: NO_PROMPT, file: untouched({ prompt: '這個檔案是關西腔' }) })).toBeNull();
  });
});

describe('批次送出的提示詞', () => {
  // 已經上傳、拿到伺服器檔名的檔案
  const uploaded = (overrides) => ({ name: 'a.wav', serverFilename: 'srv-a.wav', ...overrides });
  const batch = ({ supports = TAKES_PROMPT } = {}) => buildBatchPayload({
    files: [uploaded({ uid: 'f1' }), uploaded({ uid: 'f2', prompt: '這個檔案是關西腔' })],
    provider: 'google', model: 'gemini-2.5-flash', promptTemplate: '設定頁的範本',
    defaults: DEFAULTS, supports, sessionId: 's1',
  });

  it('每個檔案帶自己的提示詞，沒有就帶全域的；批次層級的備用值也是全域的', () => {
    const payload = batch();
    expect(payload.files.map((f) => f.prompt)).toEqual(['人名照寫：佐藤', '這個檔案是關西腔']);
    expect(payload.prompt).toBe('人名照寫：佐藤');
  });

  it('所選的模型不吃提示詞時，檔案與批次層級都不帶（#108）', () => {
    const payload = batch({ supports: { ...NO_PROMPT, batch: true } });
    expect([...payload.files.map((f) => f.prompt), payload.prompt]).toEqual([null, null, null]);
  });
});

describe('單檔任務送出的內容', () => {
  it('帶所選的供應商與模型，沒設定的欄位用全域預設', () => {
    expect(buildSinglePayload({
      serverFilename: 'srv-a.wav', file: untouched(), provider: 'local', model: 'moss-align',
      promptTemplate: null, defaults: DEFAULTS, supports: NO_PROMPT, sessionId: 's1',
    })).toEqual({
      filename: 'srv-a.wav',
      original_filename: 'a.wav',
      provider: 'local',
      model: 'moss-align',
      source_lang: 'ja-JP',
      prompt: null,
      original_text: null,
      multi_speaker: false,
      service_tier: null,
      session_id: 's1',
    });
  });
});
