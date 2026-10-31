// @ts-nocheck
import { describe, expect, it } from 'vitest';
import {
  buildBatchPayload,
  buildSinglePayload,
  followsGlobalPrompt,
  forRetranscription,
  globalSettingsPatch,
  promptToSend,
  requestDefaults,
} from './transcribeRequest.js';

// 轉錄頁按 Start 時的設定：全域預設（含全域提示詞）與所選的模型支援的輸入
const DEFAULTS = { sourceLang: 'ja-JP', multiSpeaker: false, serviceTier: null, prompt: '人名照寫：佐藤' };
const TAKES_PROMPT = { prompt: true, userText: true, batch: true };
const NO_PROMPT = { prompt: false, userText: false, batch: false };

// 剛加進來、沒動過每檔設定的檔案
const untouched = (overrides = {}) => ({ uid: 'f1', name: 'a.wav', ...overrides });

function singlePayload({ file = untouched(), defaults = DEFAULTS, supports = TAKES_PROMPT } = {}) {
  return buildSinglePayload({
    serverFilename: 'srv-a.wav', file, provider: 'google', model: 'gemini-2.5-flash',
    defaults, supports, sessionId: 's1',
  });
}

const singlePrompt = (options) => singlePayload(options).prompt;

// 送出的提示詞是補充說明：後端把它接在設定頁存的提示詞範本後面，範本由後端從設定讀（#144）
describe('單檔任務送出的提示詞（補充說明）', () => {
  it('沒有自己設定提示詞的檔案，帶全域提示詞（不必先按 Apply to All）', () => {
    expect(singlePrompt()).toBe('人名照寫：佐藤');
  });

  it('自己設定了提示詞的檔案，帶自己的', () => {
    expect(singlePrompt({ file: untouched({ prompt: '這個檔案是關西腔' }) })).toBe('這個檔案是關西腔');
  });

  it('自己的提示詞清空（只剩空白也算）就回到跟著全域：帶全域提示詞', () => {
    for (const cleared of ['', ' \n']) {
      expect(singlePrompt({ file: untouched({ prompt: cleared }) })).toBe('人名照寫：佐藤');
    }
  });

  it('全域與自己的都沒填時不帶（只有空白也算沒填）：後端只送提示詞範本', () => {
    for (const globalPrompt of ['', ' \n']) {
      expect(singlePrompt({ defaults: { ...DEFAULTS, prompt: globalPrompt } })).toBeNull();
    }
  });

  it('所選的模型不吃提示詞時一律不帶（#108）', () => {
    expect(singlePrompt({ supports: NO_PROMPT })).toBeNull();
    expect(singlePrompt({ supports: NO_PROMPT, file: untouched({ prompt: '這個檔案是關西腔' }) })).toBeNull();
  });
});

describe('批次送出的提示詞（補充說明）', () => {
  // 已經上傳、拿到伺服器檔名的檔案
  const uploaded = (overrides) => ({ name: 'a.wav', serverFilename: 'srv-a.wav', ...overrides });
  const batch = ({ files, defaults = DEFAULTS, supports = TAKES_PROMPT } = {}) => buildBatchPayload({
    files: files ?? [uploaded({ uid: 'f1' }), uploaded({ uid: 'f2', prompt: '這個檔案是關西腔' })],
    provider: 'google', model: 'gemini-2.5-flash', defaults, supports, sessionId: 's1',
  });

  it('每個檔案帶自己的提示詞，沒有就帶全域的', () => {
    expect(batch().files.map((f) => f.prompt)).toEqual(['人名照寫：佐藤', '這個檔案是關西腔']);
  });

  it('清空自己提示詞的檔案和單檔一樣跟著全域', () => {
    const payload = batch({
      files: [uploaded({ uid: 'f1', prompt: '' }), uploaded({ uid: 'f2', prompt: '這個檔案是關西腔' })],
    });
    expect(payload.files.map((f) => f.prompt)).toEqual(['人名照寫：佐藤', '這個檔案是關西腔']);
  });

  it('批次層級不帶提示詞：每個檔案已經帶了自己的補充說明，範本由後端讀', () => {
    // 後端拿批次層級的值補沒帶提示詞的檔案（batch_core 的 file.prompt or 批次層級）；不帶就只送範本
    const payload = batch({ defaults: { ...DEFAULTS, prompt: '' } });
    expect([payload.files.map((f) => f.prompt), 'prompt' in payload])
      .toEqual([[null, '這個檔案是關西腔'], false]);
  });

  it('所選的模型不吃提示詞時，檔案都不帶（#108）', () => {
    const payload = batch({ supports: { ...NO_PROMPT, batch: true } });
    expect([payload.files.map((f) => f.prompt), 'prompt' in payload]).toEqual([[null, null], false]);
  });
});

describe('檔案卡顯示的提示詞', () => {
  it('跟著全域：沒有自己的提示詞（沒填過，或清空、只剩空白），套用全域設定之後也是', () => {
    const globalConfig = { language: 'ja-JP', isMultiSpeaker: false };
    expect([
      followsGlobalPrompt(untouched()),
      followsGlobalPrompt(untouched({ prompt: '這個檔案是關西腔' })),
      followsGlobalPrompt(untouched({ prompt: '' })),
      followsGlobalPrompt(untouched({ prompt: '  ' })),
      followsGlobalPrompt({ ...untouched({ prompt: '這個檔案是關西腔' }), ...globalSettingsPatch(globalConfig) }),
    ]).toEqual([true, false, true, true, true]);
  });

  it('和送出的一樣：顯示這個檔案的補充說明（自己的，沒有就是全域的）', () => {
    expect([
      promptToSend(untouched(), '人名照寫：佐藤', TAKES_PROMPT),
      promptToSend(untouched({ prompt: '這個檔案是關西腔' }), '人名照寫：佐藤', TAKES_PROMPT),
    ]).toEqual(['人名照寫：佐藤', '這個檔案是關西腔']);
  });

  it('全域與自己的都沒填時不顯示：提示詞範本每次都送，不是這個檔案的設定', () => {
    expect(promptToSend(untouched(), ' ', TAKES_PROMPT)).toBeNull();
  });
});

describe('重新轉錄', () => {
  it('上一次送了自己的提示詞，清空之後重新轉錄：卡片與送出的都是全域提示詞', () => {
    const sent = {
      ...untouched({ prompt: '這個檔案是關西腔' }),
      status: 'completed', sentPrompt: '這個檔案是關西腔', result: { txt: '上一次的結果' },
    };

    const again = forRetranscription({ ...sent, prompt: '' });

    expect([
      again.status,
      again.result,
      followsGlobalPrompt(again),
      promptToSend(again, '人名照寫：佐藤', TAKES_PROMPT),
      singlePrompt({ file: again }),
    ]).toEqual(['waiting', null, true, '人名照寫：佐藤', '人名照寫：佐藤']);
  });
});

describe('按 Start 時的全域預設', () => {
  const onPage = { language: 'ja-JP', multiSpeaker: true, processingMode: 'standard', globalPrompt: '人名照寫：佐藤' };

  it('全域提示詞會進到送出的內容：沒有自己提示詞的檔案帶它', () => {
    const payload = singlePayload({ defaults: requestDefaults(onPage) });
    expect([payload.prompt, payload.source_lang, payload.multi_speaker])
      .toEqual(['人名照寫：佐藤', 'ja-JP', true]);
  });

  it('只有 Flex 帶 service_tier', () => {
    expect(['standard', 'flex', 'batch'].map((mode) => requestDefaults({ ...onPage, processingMode: mode }).serviceTier))
      .toEqual([null, 'flex', null]);
  });
});

describe('套用全域設定（Apply to All、Reset to global）', () => {
  it('套用之後，檔案跟著全域提示詞走：之後改的全域提示詞也會送出；語言照套用當下的全域值', () => {
    const globalConfig = {
      language: 'zh-TW', isMultiSpeaker: true,
      prompt: '套用當下的全域提示詞',
    };
    const file = {
      ...untouched({ prompt: '這個檔案是關西腔', language: 'en-US', hasOverride: true }),
      ...globalSettingsPatch(globalConfig),
    };

    const payload = singlePayload({ file, defaults: { ...DEFAULTS, prompt: '後來改過的全域提示詞' } });
    expect([payload.prompt, payload.source_lang]).toEqual(['後來改過的全域提示詞', 'zh-TW']);
  });
});

describe('單檔任務送出的內容', () => {
  it('帶所選的供應商與模型，沒設定的欄位用全域預設；沒有提示詞範本的欄位（範本由後端讀）', () => {
    expect(buildSinglePayload({
      serverFilename: 'srv-a.wav', file: untouched(), provider: 'local', model: 'moss-align',
      defaults: DEFAULTS, supports: NO_PROMPT, sessionId: 's1',
    })).toEqual({
      filename: 'srv-a.wav',
      original_filename: 'a.wav',
      provider: 'local',
      model: 'moss-align',
      source_lang: 'ja-JP',
      prompt: null,
      user_supplied_text: null,
      multi_speaker: false,
      service_tier: null,
      session_id: 's1',
    });
  });
});
