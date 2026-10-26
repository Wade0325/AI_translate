import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadLastSelection, saveLastSelection } from './lastSelection.js';

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
