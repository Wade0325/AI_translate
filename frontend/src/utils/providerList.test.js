import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { modelForProvider, requiresApiKey } from './providerList.js';

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
    assert.equal(modelForProvider(PROVIDERS, 'google', 'gemini-2.5-pro'), 'gemini-2.5-pro');
  });

  it('存的是別的供應商的模型時，退回這個供應商的預設模型', () => {
    assert.equal(modelForProvider(PROVIDERS, 'google', 'moss-align'), 'gemini-3.5-flash');
  });

  it('存的是已經不在清單上的舊模型時，退回預設模型', () => {
    assert.equal(modelForProvider(PROVIDERS, 'local', 'gemini-1.5-pro'), 'moss-align');
  });

  it('沒存過模型時用預設模型', () => {
    assert.equal(modelForProvider(PROVIDERS, 'local', null), 'moss-align');
  });

  it('清單還沒載入時沒有模型可選', () => {
    assert.equal(modelForProvider(null, 'google', 'gemini-2.5-pro'), null);
  });
});

describe('requiresApiKey：送出前要不要確認設定了 API 金鑰', () => {
  it('照端點說的：Gemini 要，本機不用', () => {
    assert.deepEqual(
      [requiresApiKey(PROVIDERS, 'google'), requiresApiKey(PROVIDERS, 'local')],
      [true, false],
    );
  });
});
