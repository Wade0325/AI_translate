/**
 * 測試用的 sessionStorage 替身：照 Web Storage 的介面，資料只放在記憶體裡。
 * Node 沒有 sessionStorage；測試開始時用 vi.stubGlobal 換上一個新的，測試之間互不影響。
 */
export function createMemoryStorage() {
  const items = new Map();
  return {
    get length() {
      return items.size;
    },
    key: (index) => [...items.keys()][index] ?? null,
    getItem: (key) => items.get(String(key)) ?? null,
    setItem: (key, value) => {
      items.set(String(key), String(value));
    },
    removeItem: (key) => {
      items.delete(String(key));
    },
    clear: () => {
      items.clear();
    },
  };
}
