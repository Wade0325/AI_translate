import { describe, expect, it } from 'vitest';
import { createProviderListStore } from './providerListStore.js';

const LIST = [{ provider: 'google', label: 'Gemini', requires_api_key: true, models: [] }];

// 讀清單：照劇本依序回傳結果或拋錯，記下被呼叫幾次
function scriptedLoad(...outcomes) {
  const load = async () => {
    load.calls += 1;
    const outcome = outcomes.shift();
    if (outcome instanceof Error) throw outcome;
    return outcome;
  };
  load.calls = 0;
  return load;
}

// 自動重試的計時器：不真的等，由測試決定什麼時候到時間
function manualTimers() {
  const timers = { pending: new Map(), delays: [], nextId: 1 };
  timers.schedule = (fn, ms) => {
    timers.delays.push(ms);
    const id = timers.nextId++;
    timers.pending.set(id, fn);
    return id;
  };
  timers.cancel = (id) => timers.pending.delete(id);
  timers.fireNext = () => {
    const [id, fn] = timers.pending.entries().next().value;
    timers.pending.delete(id);
    fn();
  };
  return timers;
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function storeWith(load, timers = manualTimers()) {
  return createProviderListStore({ load, schedule: timers.schedule, cancel: timers.cancel });
}

describe('供應商清單的讀取', () => {
  it('讀取失敗後自動重試；成功後，所有用到清單的地方一起拿到', async () => {
    const timers = manualTimers();
    const store = storeWith(scriptedLoad(new Error('後端還沒起來'), LIST), timers);
    const seen = [null, null];
    store.subscribe(() => { seen[0] = store.getSnapshot(); });
    store.subscribe(() => { seen[1] = store.getSnapshot(); });
    await settle();
    expect(store.getSnapshot()).toEqual({ providerList: null, failed: true });

    timers.fireNext();
    await settle();

    expect(seen).toEqual([{ providerList: LIST, failed: false }, { providerList: LIST, failed: false }]);
  });

  it('按重試就立刻再讀，不等下一次自動重試', async () => {
    const timers = manualTimers();
    const load = scriptedLoad(new Error('網路斷了一下'), LIST);
    const store = storeWith(load, timers);
    store.subscribe(() => {});
    await settle();

    await store.reload();

    expect([load.calls, store.getSnapshot().providerList, timers.pending.size]).toEqual([2, LIST, 0]);
  });

  it('一直失敗時，重試的間隔逐次加倍，最多 30 秒', async () => {
    const timers = manualTimers();
    const store = storeWith(scriptedLoad(...Array.from({ length: 8 }, () => new Error('壞了'))), timers);
    store.subscribe(() => {});
    await settle();
    for (let i = 0; i < 6; i += 1) {
      timers.fireNext();
      await settle();
    }

    expect(timers.delays).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000]);
  });

  it('讀到清單之後，再有地方用到也不會重讀', async () => {
    const load = scriptedLoad(LIST);
    const store = storeWith(load);
    store.subscribe(() => {});
    await settle();

    store.subscribe(() => {});
    await settle();

    expect(load.calls).toBe(1);
  });
});
