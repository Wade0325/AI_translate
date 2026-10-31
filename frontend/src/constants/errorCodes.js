/**
 * 錯誤碼 → 顯示給使用者的原因、下一步，以及畫面上要不要放一個前往的連結（#24 門檻 4）。
 *
 * 後端把任務失敗的原因歸類成錯誤碼（backend/app/core/error_codes.py 的 ErrorCode），連同細節記進任務
 * 紀錄（error_code、error_message），也隨失敗的狀態廣播送來；文案只寫在這裡。後端的每個錯誤碼這裡都要有，
 * 由 tests/unit/test_error_codes.py 檢查。UPLOAD_FAILED 只有前端用：上傳失敗時任務還沒有送到後端。
 *
 * action：
 *   - settings：到設定頁就能處理（填金鑰、下載模型權重）
 *   - report：多半是程式的問題，請使用者到設定頁的回報問題入口回報，附上錯誤碼
 */
export const ERROR_CODES = Object.freeze({
  // ── Gemini ──
  GEMINI_NO_API_KEY: {
    reason: '還沒有設定 Gemini 的 API 金鑰',
    nextStep: '到設定頁的 Gemini 填入 API Key 並儲存，再重新轉錄。',
    action: 'settings',
  },
  GEMINI_KEY_REJECTED: {
    reason: 'Gemini 不接受這把 API 金鑰',
    nextStep: '金鑰可能打錯、已經停用，或所屬專案沒有權限。到設定頁的 Gemini 換一把可用的 API Key，再重新轉錄。',
    action: 'settings',
  },
  GEMINI_BILLING: {
    reason: 'Gemini 帳戶的計費或使用資格有問題',
    nextStep: '到 Google AI Studio 確認金鑰所屬的專案已經啟用計費，或所在地區可以使用 Gemini API，再重新轉錄。',
  },
  GEMINI_QUOTA: {
    reason: 'Gemini 的用量達到上限',
    nextStep: '已經自動重試過幾次仍然超過上限。等幾分鐘再重新轉錄；常常遇到的話，到 Google AI Studio 查看這把金鑰的配額。',
  },
  GEMINI_UNAVAILABLE: {
    reason: 'Gemini 暫時無法服務',
    nextStep: '已經自動重試過幾次。Gemini 可能正忙，稍後再重新轉錄。',
  },
  GEMINI_BLOCKED: {
    reason: 'Gemini 的安全機制擋下了這段內容',
    nextStep: '同樣的內容重送多半還是會被擋，可以改用本機的模型轉錄這個音檔。',
  },
  GEMINI_REQUEST_FAILED: {
    reason: 'Gemini 回報這個請求失敗',
    nextStep: '原因寫在下面的細節。重新轉錄還是失敗的話，請回報問題並附上錯誤碼。',
    action: 'report',
  },
  NETWORK: {
    reason: '網路連線失敗，連不上 Gemini',
    nextStep: '確認這台電腦可以上網（公司或學校的網路可能擋住 Google 的服務），再重新轉錄。',
  },
  // ── 本機 ──
  LOCAL_NO_GPU: {
    reason: '這台電腦沒有可用的 NVIDIA 顯卡',
    nextStep: '本機的模型需要 NVIDIA 顯卡，請改用 Gemini 轉錄。',
  },
  LOCAL_DRIVER_TOO_OLD: {
    reason: 'NVIDIA 顯卡驅動太舊',
    nextStep: '目前與需要的驅動版本寫在下面的細節。更新驅動後重新開啟 Mimiji，再重新轉錄；或改用 Gemini 轉錄。',
  },
  LOCAL_CUDA_INIT_FAILED: {
    reason: '顯卡的 CUDA 初始化失敗',
    nextStep: '重新開機後再重新轉錄；還是失敗的話，重新安裝最新的 NVIDIA 驅動，或改用 Gemini 轉錄。',
  },
  LOCAL_TORCH_LOAD_FAILED: {
    reason: 'PyTorch 載入失敗',
    nextStep: '原因寫在下面的細節。重新開機後再重新轉錄；一直失敗的話，請回報問題並附上錯誤碼，或改用 Gemini 轉錄。',
    action: 'report',
  },
  LOCAL_UNSUPPORTED_GPU: {
    reason: '目前的版本不支援這張顯卡',
    nextStep: '本機的模型在這張顯卡上跑不了，請改用 Gemini 轉錄。',
  },
  LOCAL_MISSING_WEIGHTS: {
    reason: '所選模型的模型權重還沒下載',
    nextStep: '到設定頁下載模型權重，下載完再重新轉錄。',
    action: 'settings',
  },
  LOCAL_OUT_OF_MEMORY: {
    reason: '顯卡的記憶體不夠',
    nextStep: '關掉其他正在用顯卡的程式（例如遊戲、其他 AI 工具）再重新轉錄，或改用 Gemini。',
  },
  // ── 音檔與轉錄結果 ──
  AUDIO_UNREADABLE: {
    reason: '讀不出這個音檔',
    nextStep: '檔案可能損壞，或是不支援的編碼。用其他播放器確認能播放，或轉成 MP3、WAV 再上傳一次。',
  },
  NO_TRANSCRIPT: {
    reason: '沒有轉錄出任何內容',
    nextStep: '音檔裡可能沒有說話的聲音，或音量太小。確認語言設定正確，或換一個模型再試。',
  },
  // ── 送出任務 ──
  UPLOAD_FAILED: {
    reason: '檔案沒有上傳成功',
    nextStep: '原因寫在下面的細節。確認檔案格式與大小，再重新轉錄。',
  },
  UNSUPPORTED_REQUEST: {
    reason: '所選的模型不支援這次的設定',
    nextStep: '原因寫在下面的細節。換一個模型，或拿掉不支援的設定，再重新轉錄。',
  },
  UPLOAD_MISSING: {
    reason: '伺服器上找不到上傳的檔案',
    nextStep: '上傳的檔案可能已經被清掉，或另一個分頁已經送出同一個檔案。把檔案移除後重新加入，再轉錄一次。',
  },
  SUBMIT_FAILED: {
    reason: '任務沒有送出',
    nextStep: '重新轉錄一次。一直失敗的話，請回報問題並附上錯誤碼。',
    action: 'report',
  },
  // ── 任務 ──
  INTERRUPTED: {
    reason: '應用程式在處理途中關閉了',
    nextStep: '任務沒有做完，重新轉錄一次即可。',
  },
  DATABASE: {
    reason: '讀寫任務紀錄時出錯',
    nextStep: '重新轉錄一次。一直失敗的話，請回報問題並附上錯誤碼。',
    action: 'report',
  },
  BATCH_FAILED: {
    reason: '批次處理失敗',
    nextStep: '原因寫在下面的細節。可以重新送出，或改用標準模式逐一轉錄。',
  },
  INTERNAL: {
    reason: '發生了非預期的錯誤',
    nextStep: '重新轉錄一次。一直失敗的話，請回報問題並附上錯誤碼與下面的細節。',
    action: 'report',
  },
});

/** action → 連結的文字與目的地。 */
export const ERROR_ACTIONS = Object.freeze({
  settings: { label: '前往設定頁', to: '/settings' },
  report: { label: '到設定頁回報問題', to: '/settings' },
});
