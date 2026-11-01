import { describe, expect, it } from 'vitest';
import { readinessView } from './localReadiness.js';

const NOTHING = { blockedReason: null, nextStep: null, warning: null };

// 後端 GET /setting/local-models/readiness 回的形狀
const answer = (fields) => ({
  checked: true, ready: true, reason: null, message: null, vram_notice: null, ...fields,
});

describe('轉錄頁選本機時，這台電腦能不能轉錄（#11）', () => {
  it('能轉錄、記憶體也夠時不提示也不擋', () => {
    expect(readinessView(answer({}))).toEqual(NOTHING);
  });

  it('沒有可用的顯卡：擋下 Start，下一步是改用別的供應商', () => {
    const message = '這台電腦沒有可用的 NVIDIA 顯卡，本機轉錄不能用，可以改用 Gemini';
    expect(readinessView(answer({ ready: false, reason: 'no_gpu', message }))).toEqual({
      blockedReason: message, nextStep: 'switch', warning: null,
    });
  });

  it('PyTorch 不支援這張顯卡時也一樣改用別的供應商', () => {
    expect(readinessView(answer({ ready: false, reason: 'unsupported_gpu', message: '不支援' })).nextStep)
      .toBe('switch');
  });

  it.each(['driver_too_old', 'cuda_init_failed', 'torch_load_failed'])(
    'PyTorch 用不了顯卡（%s，#262）：照後端寫的原因與下一步擋下，另外可以改用別的供應商',
    (reason) => {
      const message = 'NVIDIA 顯卡驅動太舊（目前 472.12，需要 572.61 以上），本機轉錄不能用，'
        + '更新驅動後重新開啟 Mimiji，或改用 Gemini';
      expect(readinessView(answer({ ready: false, reason, message }))).toEqual({
        blockedReason: message, nextStep: 'switch', warning: null,
      });
    },
  );

  it('缺模型權重：擋下 Start，下一步是到設定頁下載', () => {
    expect(readinessView(answer({ ready: false, reason: 'missing_weights', message: '缺權重' })))
      .toEqual({ blockedReason: '缺權重', nextStep: 'settings', warning: null });
  });

  it('顯卡記憶體低於最低需求只提示、不擋（Q2）', () => {
    const notice = '顯卡記憶體 8 GB 沒有測過';
    expect(readinessView(answer({ vram_notice: notice })))
      .toEqual({ blockedReason: null, nextStep: null, warning: notice });
  });

  it('擋下的原因和記憶體提示可以同時有', () => {
    const view = readinessView(answer({
      ready: false, reason: 'missing_weights', message: '缺權重', vram_notice: '低於 8 GB',
    }));
    expect([view.blockedReason, view.warning]).toEqual(['缺權重', '低於 8 GB']);
  });

  it('還沒問到、問不到，或 Docker 模式沒有查時，都不提示也不擋', () => {
    expect([readinessView(null), readinessView({ checked: false, ready: null })])
      .toEqual([NOTHING, NOTHING]);
  });
});
