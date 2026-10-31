/**
 * 轉錄頁選了在這台電腦上轉錄的供應商（本機）時，就緒檢查（後端
 * GET /setting/local-models/readiness）的結果怎麼呈現（#11）。
 *
 * 沒有 GPU 的電腦也預設本機：不能轉錄時寫出原因並停用 Start，下一步由使用者自己選，例如改用
 * Gemini（會上傳音檔，所以不自動切換，#11 Q1）。顯卡記憶體低於最低需求只提示、不擋（Q2）。
 */

/** 不提示、不擋：還沒查到、查不到（請求失敗）或沒有查（Docker 模式）。 */
const NOTHING = { blockedReason: null, nextStep: null, warning: null };

/**
 * { blockedReason, nextStep, warning }：
 * - blockedReason：不能轉錄的原因，Start 停用並顯示它；能轉錄時是 null。
 * - nextStep：'switch'（這台電腦現在跑不了：怎麼修寫在 blockedReason，例如更新驅動；另外給改用別的
 *   供應商的按鈕）、'settings'（到設定頁下載模型權重）或 null。
 * - warning：顯卡記憶體的提示，只提示、不擋；沒有時是 null。
 *
 * 不知道的一律不擋，由轉錄時的檢查把關。
 */
export function readinessView(readiness) {
  if (!readiness?.checked) return NOTHING;
  const warning = readiness.vram_notice ?? null;
  if (readiness.ready) return { ...NOTHING, warning };
  return {
    blockedReason: readiness.message ?? '本機現在不能轉錄',
    nextStep: readiness.reason === 'missing_weights' ? 'settings' : 'switch',
    warning,
  };
}
