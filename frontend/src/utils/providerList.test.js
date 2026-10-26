import { describe, expect, it } from 'vitest';
import {
  allowedProcessingMode,
  missingApiKey,
  modelSupports,
  modelForProvider,
  modelOptions,
  processingModeNote,
  providerOptions,
  providerTestRequest,
  requiresApiKey,
  resolveSelection,
  withModel,
  withProvider,
} from './providerList.js';

// 後端 GET /providers 回的形狀，只留測試用得到的欄位
const PROVIDERS = [
  {
    provider: 'google',
    label: 'Gemini',
    requires_api_key: true,
    models: [
      { model: 'gemini-3.5-flash', label: 'gemini-3.5-flash', capabilities: {} },
      { model: 'gemini-2.5-pro', label: 'gemini-2.5-pro', capabilities: {} },
    ],
  },
  {
    provider: 'local',
    label: '本機',
    requires_api_key: false,
    models: [
      { model: 'moss-align', label: 'MOSS-Transcribe-Diarize', capabilities: {} },
      { model: 'vibevoice-qwen3-asr', label: 'VibeVoice + Qwen3-ASR（舊版）', capabilities: {} },
    ],
  },
];

describe('modelForProvider：選了供應商之後用哪個模型', () => {
  it('想用的模型（設定頁存的預設模型）屬於這個供應商就用它', () => {
    expect(modelForProvider(PROVIDERS, 'google', 'gemini-2.5-pro')).toBe('gemini-2.5-pro');
  });

  it('存的是別的供應商的模型時，退回這個供應商的預設模型', () => {
    expect(modelForProvider(PROVIDERS, 'google', 'moss-align')).toBe('gemini-3.5-flash');
  });

  it('存的是已經不在清單上的舊模型時，退回預設模型', () => {
    expect(modelForProvider(PROVIDERS, 'local', 'gemini-1.5-pro')).toBe('moss-align');
  });

  it('沒存過模型時用預設模型', () => {
    expect(modelForProvider(PROVIDERS, 'local', null)).toBe('moss-align');
  });

  it('清單還沒載入時沒有模型可選', () => {
    expect(modelForProvider(null, 'google', 'gemini-2.5-pro')).toBeNull();
  });
});

describe('requiresApiKey：要不要使用者的 API 金鑰（送出前檢查金鑰、有沒有「編輯 API」與金鑰欄位都照它）', () => {
  it('照端點說的：Gemini 要，本機不用', () => {
    expect([requiresApiKey(PROVIDERS, 'google'), requiresApiKey(PROVIDERS, 'local')])
      .toEqual([true, false]);
  });
});

describe('missingApiKey：按 Start 時缺不缺金鑰', () => {
  it('只有要金鑰的供應商才檢查：Gemini 沒存金鑰才算缺，本機不用存', () => {
    const saved = { apiKeys: ['AIza********ABCD'] };
    expect([
      missingApiKey(PROVIDERS, 'google', { apiKeys: [] }),
      missingApiKey(PROVIDERS, 'google', saved),
      missingApiKey(PROVIDERS, 'local', null),
    ]).toEqual([true, false, false]);
  });
});

describe('providerTestRequest：按「測試」送出的請求', () => {
  it('不用金鑰的供應商不帶金鑰，也不必先存過設定', () => {
    expect(providerTestRequest(PROVIDERS, 'local', null, 'moss-align'))
      .toEqual({ provider: 'local', apiKeys: [], model: 'moss-align' });
  });

  it('要金鑰的供應商帶設定頁存的金鑰（遮罩值，後端換回實際金鑰），空白的不帶', () => {
    const saved = { apiKeys: ['AIza********ABCD', ''] };

    expect(providerTestRequest(PROVIDERS, 'google', saved, 'gemini-2.5-pro')).toEqual({
      provider: 'google', apiKeys: ['AIza********ABCD'], model: 'gemini-2.5-pro',
    });
  });

  it('測畫面上選的模型（設定頁卡片上的、轉錄頁模型選單上的，還沒儲存也算），不測設定頁存的預設模型', () => {
    const saved = { apiKeys: [], model: 'moss-align' };

    expect(providerTestRequest(PROVIDERS, 'local', saved, 'vibevoice-qwen3-asr').model)
      .toBe('vibevoice-qwen3-asr');
  });
});

describe('轉錄頁選的供應商與模型', () => {
  const NOTHING_CHOSEN = { provider: null, model: null };

  it('還沒選時用清單上的第一個供應商與它的預設模型', () => {
    expect(resolveSelection(PROVIDERS, NOTHING_CHOSEN))
      .toEqual({ provider: 'google', model: 'gemini-3.5-flash' });
  });

  it('選了模型就用它', () => {
    expect(resolveSelection(PROVIDERS, withModel(NOTHING_CHOSEN, 'gemini-2.5-pro')))
      .toEqual({ provider: 'google', model: 'gemini-2.5-pro' });
  });

  it('換供應商時，模型回到這個供應商的預設模型', () => {
    const chosen = withModel(NOTHING_CHOSEN, 'gemini-2.5-pro');
    expect(resolveSelection(PROVIDERS, withProvider(chosen, 'local')))
      .toEqual({ provider: 'local', model: 'moss-align' });
  });

  it('換供應商時，兩邊都有同名的模型也一樣回到預設：一個模型由供應商與模型一起識別', () => {
    const model = (id) => ({ model: id, label: id, capabilities: {} });
    const sameModelOnBoth = [
      { provider: 'local', label: '本機', models: [model('local-default'), model('shared')] },
      { provider: 'cloud', label: '雲端', models: [model('cloud-default'), model('shared')] },
    ];
    const chosen = withModel(withProvider(NOTHING_CHOSEN, 'local'), 'shared');

    expect(resolveSelection(sameModelOnBoth, withProvider(chosen, 'cloud')))
      .toEqual({ provider: 'cloud', model: 'cloud-default' });
  });

  it('清單還沒載入時什麼都沒選', () => {
    expect(resolveSelection(null, NOTHING_CHOSEN)).toEqual({ provider: null, model: null });
  });
});

describe('選單的選項', () => {
  it('供應商與模型都照清單的順序，顯示畫面上的名稱', () => {
    expect([providerOptions(PROVIDERS), modelOptions(PROVIDERS, 'local')]).toEqual([
      [{ value: 'google', label: 'Gemini' }, { value: 'local', label: '本機' }],
      [
        { value: 'moss-align', label: 'MOSS-Transcribe-Diarize' },
        { value: 'vibevoice-qwen3-asr', label: 'VibeVoice + Qwen3-ASR（舊版）' },
      ],
    ]);
  });
});

describe('處理模式依模型能力（#162）', () => {
  const GEMINI = { supports_batch: true, supports_flex: true };
  const LOCAL = { supports_batch: false, supports_flex: false };

  it('模型能力標明不支援的處理模式，modelSupports 就是 false；還沒載入時當成支援', () => {
    expect([modelSupports(GEMINI), modelSupports(LOCAL), modelSupports(null)]
      .map(({ flex, batch }) => ({ flex, batch }))).toEqual([
      { flex: true, batch: true },
      { flex: false, batch: false },
      { flex: true, batch: true },
    ]);
  });

  it('所選的模型支援時照使用者選的處理模式', () => {
    expect(['standard', 'flex', 'batch'].map((mode) => allowedProcessingMode(mode, modelSupports(GEMINI))))
      .toEqual(['standard', 'flex', 'batch']);
  });

  it('換到不支援的模型時，Flex 與批次都退回標準', () => {
    expect(['standard', 'flex', 'batch'].map((mode) => allowedProcessingMode(mode, modelSupports(LOCAL))))
      .toEqual(['standard', 'standard', 'standard']);
  });

  it('只退回不支援的那一個', () => {
    const flexOnly = modelSupports({ supports_batch: false, supports_flex: true });

    expect(['flex', 'batch'].map((mode) => allowedProcessingMode(mode, flexOnly)))
      .toEqual(['flex', 'standard']);
  });

  it('選單下方說明哪些處理模式不能用；都能用時沒有說明', () => {
    expect([
      processingModeNote(modelSupports(LOCAL)),
      processingModeNote(modelSupports({ supports_batch: false, supports_flex: true })),
      processingModeNote(modelSupports({ supports_batch: true, supports_flex: false })),
      processingModeNote(modelSupports(GEMINI)),
    ]).toEqual([
      '所選的模型不支援 Flex 與批次，只能用標準',
      '所選的模型不支援批次',
      '所選的模型不支援 Flex',
      null,
    ]);
  });
});

describe('去靜音依模型能力（#95）', () => {
  it('模型能力說不去靜音的就是 false；還沒載入時當成會去靜音', () => {
    expect([
      modelSupports({ remove_silence: true }).removeSilence,
      modelSupports({ remove_silence: false }).removeSilence,
      modelSupports(null).removeSilence,
    ]).toEqual([true, false, true]);
  });
});
