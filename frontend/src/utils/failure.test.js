import { describe, expect, it } from 'vitest';
import { ERROR_CODES } from '../constants/errorCodes.js';
import { describeFailure, failureOf, uploadFailure } from './failure.js';
import { applyFileResult } from './fileResult.js';

describe('failureOf：從失敗的狀態訊息或任務紀錄取出錯誤碼與細節', () => {
  it('兩邊的欄位同名', () => {
    expect(failureOf({ error_code: 'GEMINI_QUOTA', error_message: '429 RESOURCE_EXHAUSTED' })).toEqual({
      code: 'GEMINI_QUOTA',
      detail: '429 RESOURCE_EXHAUSTED',
    });
  });

  it('這個版本之前失敗的紀錄沒有錯誤碼；資料庫出錯時沒有細節', () => {
    expect(failureOf({ error_message: '舊的原因' })).toEqual({ code: null, detail: '舊的原因' });
    expect(failureOf({ error_code: 'DATABASE', error_message: null })).toEqual({ code: 'DATABASE', detail: '' });
  });
});

describe('describeFailure：要顯示的原因、下一步與連結', () => {
  it('認得的錯誤碼：原因與下一步照文案，細節放在下面', () => {
    expect(describeFailure({ code: 'GEMINI_KEY_REJECTED', detail: '403 PERMISSION_DENIED: leaked' })).toEqual({
      code: 'GEMINI_KEY_REJECTED',
      reason: ERROR_CODES.GEMINI_KEY_REJECTED.reason,
      nextStep: ERROR_CODES.GEMINI_KEY_REJECTED.nextStep,
      action: { label: '前往設定頁', to: '/settings' },
      detail: '403 PERMISSION_DENIED: leaked',
    });
  });

  it('多半是程式的問題時，連結到設定頁的回報問題入口', () => {
    expect(describeFailure({ code: 'INTERNAL', detail: 'KeyError' }).action).toEqual({
      label: '到設定頁回報問題',
      to: '/settings',
    });
  });

  it('沒有細節時不顯示細節', () => {
    expect(describeFailure({ code: 'DATABASE', detail: '' }).detail).toBeNull();
  });

  it('舊的紀錄沒有錯誤碼：細節就是原因，和以前一樣', () => {
    expect(describeFailure({ code: null, detail: '分段 1 失敗' })).toEqual({
      code: null,
      reason: '分段 1 失敗',
      nextStep: null,
      action: null,
      detail: null,
    });
    expect(describeFailure({ code: null, detail: '' }).reason).toBe('任務失敗');
  });

  it('認不得的錯誤碼（後端比前端新）：說任務失敗，錯誤碼與細節照樣留著給使用者回報', () => {
    expect(describeFailure({ code: 'SOMETHING_NEW', detail: '新的原因' })).toEqual({
      code: 'SOMETHING_NEW',
      reason: '任務失敗',
      nextStep: null,
      action: null,
      detail: '新的原因',
    });
  });

  it('每個錯誤碼都有原因與下一步', () => {
    for (const [code, copy] of Object.entries(ERROR_CODES)) {
      expect(copy.reason, code).toBeTruthy();
      expect(copy.nextStep, code).toBeTruthy();
    }
  });
});

describe('uploadFailure：上傳失敗', () => {
  it('伺服器回了原因時當細節', () => {
    const error = Object.assign(new Error('檔案是空的（0 位元組），請確認檔案沒有損壞'), { name: 'ApiError' });
    expect(uploadFailure(error)).toEqual({ code: 'UPLOAD_FAILED', detail: '檔案是空的（0 位元組），請確認檔案沒有損壞' });
  });

  it('連不上伺服器時瀏覽器的英文訊息不放', () => {
    expect(uploadFailure(new TypeError('Failed to fetch'))).toEqual({ code: 'UPLOAD_FAILED', detail: '' });
  });
});

describe('applyFileResult：失敗的狀態廣播', () => {
  it('檔案卡記下錯誤碼與細節', () => {
    const card = applyFileResult(
      { uid: 'u1', status: 'processing' },
      {
        status_code: 'FAILED',
        status_text: '任務失敗: Gemini 的回應被阻擋（SAFETY）',
        task_uuid: 't1',
        error_code: 'GEMINI_BLOCKED',
        error_message: 'Gemini 的回應被阻擋（SAFETY）',
      },
    );
    expect(card).toMatchObject({
      status: 'error',
      failure: { code: 'GEMINI_BLOCKED', detail: 'Gemini 的回應被阻擋（SAFETY）' },
    });
  });

  it('訊息沒帶錯誤碼與細節時，狀態文字就是原因', () => {
    const card = applyFileResult(
      { uid: 'u1', status: 'processing' },
      { status_code: 'FAILED', status_text: '找不到 NVIDIA 顯示卡', task_uuid: 't1' },
    );
    expect(card.failure).toEqual({ code: null, detail: '找不到 NVIDIA 顯示卡' });
    expect(describeFailure(card.failure).reason).toBe('找不到 NVIDIA 顯示卡');
  });
});
