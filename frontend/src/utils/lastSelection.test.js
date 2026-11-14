import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  loadLastLanguage,
  loadLastSelection,
  loadLastSpeakerCount,
  saveLastLanguage,
  saveLastSelection,
  saveLastSpeakerCount,
} from './lastSelection.js';

const NOTHING_CHOSEN = { provider: null, model: null };

/** 換上和 localStorage 一樣只存字串的假儲存空間，回傳存進去的內容。 */
function stubStorage(initial = {}) {
  const items = { ...initial };
  vi.stubGlobal('localStorage', {
    getItem: (key) => (key in items ? items[key] : null),
    setItem: (key, value) => { items[key] = String(value); },
  });
  return items;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('轉錄頁記住上次選的供應商與模型', () => {
  it('存了之後讀回同一組', () => {
    stubStorage();

    saveLastSelection({ provider: 'local', model: 'moss-align' });

    expect(loadLastSelection()).toEqual({ provider: 'local', model: 'moss-align' });
  });

  it('只存供應商與模型的名稱，其他欄位不存', () => {
    const items = stubStorage();
    const withKeys = { provider: 'google', model: 'gemini-2.5-pro', apiKeys: ['AIza-secret'] };

    saveLastSelection(withKeys);

    expect(Object.values(items).join()).not.toContain('AIza-secret');
  });

  it('沒存過時當成還沒選，由供應商清單決定預設', () => {
    stubStorage();

    expect(loadLastSelection()).toEqual(NOTHING_CHOSEN);
  });

  it('存的內容壞掉或形狀不對時當成還沒選', () => {
    for (const saved of ['{壞掉', '"local"', '[1,2]', '{"provider":3,"model":{}}']) {
      stubStorage({ ai_translate_last_selection: saved });
      expect(loadLastSelection()).toEqual(NOTHING_CHOSEN);
    }
  });

  it('瀏覽器擋下儲存空間時，讀不到就當成還沒選，存不進去也不影響轉錄', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('SecurityError'); },
      setItem: () => { throw new Error('QuotaExceededError'); },
    });

    expect(loadLastSelection()).toEqual(NOTHING_CHOSEN);
    expect(() => saveLastSelection({ provider: 'local', model: 'moss-align' })).not.toThrow();
  });

  it('沒有儲存空間可用（例如不在瀏覽器裡）時也一樣', () => {
    vi.stubGlobal('localStorage', undefined);

    expect(loadLastSelection()).toEqual(NOTHING_CHOSEN);
    expect(() => saveLastSelection({ provider: 'local', model: null })).not.toThrow();
  });
});

describe('轉錄頁記住上次選的說話者人數（#351）', () => {
  it('第一次開頁是 Auto', () => {
    stubStorage();

    expect(loadLastSpeakerCount()).toBe('auto');
  });

  it('存了之後讀回同一個人數，選回 Auto 也記住', () => {
    stubStorage();

    saveLastSpeakerCount(3);
    expect(loadLastSpeakerCount()).toBe(3);

    saveLastSpeakerCount('auto');
    expect(loadLastSpeakerCount()).toBe('auto');
  });

  it('和供應商與模型分開存，互不影響', () => {
    const items = stubStorage();

    saveLastSelection({ provider: 'local', model: 'moss-align' });
    saveLastSpeakerCount(2);

    expect(items).toEqual({
      ai_translate_last_selection: JSON.stringify({ provider: 'local', model: 'moss-align' }),
      ai_translate_last_speaker_count: '2',
    });
    expect(loadLastSelection()).toEqual({ provider: 'local', model: 'moss-align' });
  });

  it('舊的 Multi-Speaker 開關不沿用：開著的人也從 Auto 開始', () => {
    stubStorage({ ai_translate_last_multi_speaker: 'true' });

    expect(loadLastSpeakerCount()).toBe('auto');
  });

  it('存的內容壞掉或不是選單上的人數時當成 Auto', () => {
    for (const saved of ['{壞掉', '"3"', '0', '9', '2.5', 'true', '"Auto"', 'null']) {
      stubStorage({ ai_translate_last_speaker_count: saved });
      expect(loadLastSpeakerCount()).toBe('auto');
    }
  });

  it('瀏覽器擋下儲存空間或沒有儲存空間時，讀不到就是 Auto，存不進去也不影響轉錄', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('SecurityError'); },
      setItem: () => { throw new Error('QuotaExceededError'); },
    });
    expect(loadLastSpeakerCount()).toBe('auto');
    expect(() => saveLastSpeakerCount(2)).not.toThrow();

    vi.stubGlobal('localStorage', undefined);
    expect(loadLastSpeakerCount()).toBe('auto');
    expect(() => saveLastSpeakerCount(2)).not.toThrow();
  });
});

describe('轉錄頁記住上次選的語言（#261）', () => {
  it('第一次開頁是 Auto Detect', () => {
    stubStorage();

    expect(loadLastLanguage()).toBe('auto');
  });

  it('存了之後讀回同一個語言，選回 Auto Detect 也記住', () => {
    stubStorage();

    for (const language of ['ja', 'zh-TW', 'fr', 'auto']) {
      saveLastLanguage(language);
      expect(loadLastLanguage()).toBe(language);
    }
  });

  it('和供應商、模型與說話者人數分開存，只存語言代碼', () => {
    const items = stubStorage();

    saveLastSelection({ provider: 'local', model: 'moss-align' });
    saveLastSpeakerCount(2);
    saveLastLanguage('ja');

    expect(items).toEqual({
      ai_translate_last_selection: JSON.stringify({ provider: 'local', model: 'moss-align' }),
      ai_translate_last_speaker_count: '2',
      ai_translate_last_language: '"ja"',
    });
  });

  it('存的語言已經不在選單上（舊的 zh-CN）、內容壞掉或不是語言代碼時是 Auto Detect', () => {
    for (const saved of ['"zh-CN"', '"日文"', '""', '{壞掉', '1', 'null', '{"language":"ja"}']) {
      stubStorage({ ai_translate_last_language: saved });
      expect(loadLastLanguage()).toBe('auto');
    }
  });

  it('瀏覽器擋下儲存空間或沒有儲存空間時，讀不到就是 Auto Detect，存不進去也不影響轉錄', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('SecurityError'); },
      setItem: () => { throw new Error('QuotaExceededError'); },
    });
    expect(loadLastLanguage()).toBe('auto');
    expect(() => saveLastLanguage('ja')).not.toThrow();

    vi.stubGlobal('localStorage', undefined);
    expect(loadLastLanguage()).toBe('auto');
    expect(() => saveLastLanguage('ja')).not.toThrow();
  });
});
