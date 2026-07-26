import { useCallback } from 'react';
import { message } from 'antd';
import { api, WS_URLS } from '../services/api';
import { registerTranscribeSession } from '../utils/transcribeSessions';
import { randomId } from '../utils/id';

/**
 * 封裝「上傳檔案 → 開啟 WebSocket → 接收後端推送」的完整流程。
 *
 * 接收：
 *   - fileList / setFileList：呼叫端維護的 React state
 *   - socketManager：來自 useTranscriptionSocket()
 *
 * 回傳兩個高階函式：
 *   - startRegular({ provider, model, apiKey, prompt, defaults }):
 *       每個檔案各自一條 WS；單檔轉錄／Flex／Standard 模式
 *   - startBatch({ provider, model, apiKey, prompt, defaults }):
 *       所有檔案共用一條 batch WS（Gemini Batch API，50% 折扣）
 *
 * defaults 物件包含全域 fallback：source_lang / multi_speaker / service_tier；
 * 當檔案本身沒指定 per-file 設定時會用 defaults 補上。
 */

const isRestartable = (f) =>
  (f.status === 'waiting' || f.status === 'error' || f.status === 'cancelled') &&
  !!f.originFileObj;

function buildSinglePayload({ serverFilename, file, provider, model, apiKey, prompt, defaults, sessionId }) {
  return {
    filename: serverFilename,
    original_filename: file.name,
    provider,
    model,
    api_keys: apiKey,
    source_lang: file.language || defaults.sourceLang,
    prompt: file.prompt ?? prompt,
    original_text: file.original_text || null,
    multi_speaker: file.isMultiSpeaker ?? defaults.multiSpeaker,
    service_tier: defaults.serviceTier,
    session_id: sessionId,
  };
}

// 依 COMPLETED/FAILED/CANCELLED 的 WS 訊息，算出單一 file 的下一個 state。
function applyFileResult(file, data) {
  const next = {
    ...file,
    statusText: data.status_text,
    task_uuid: data.task_uuid,
  };
  if (data.status_code === 'COMPLETED') {
    next.status = 'completed';
    next.percent = 100;
    next.result = data.result?.transcripts;
    next.tokens_used = data.result?.tokens_used;
    next.cost = data.result?.cost;
    // Result 頁顯示用：時長、模型與實際使用的來源語言
    next.audioDurationSec = data.result?.audio_duration_seconds;
    next.model = data.result?.model ?? file.model;
    next.sourceLanguage = data.result?.source_language;
  } else if (data.status_code === 'FAILED') {
    next.status = 'error';
    next.percent = 100;
    next.error = data.status_text;
  } else if (data.status_code === 'CANCELLED') {
    next.status = 'cancelled';
    next.percent = 100;
  }
  return next;
}

export function useUploadQueue({ fileList, setFileList, socketManager, onBatchSubmitted }) {
  const updateFile = useCallback((uid, patch) => {
    setFileList((current) =>
      current.map((f) => (f.uid === uid ? { ...f, ...patch } : f))
    );
  }, [setFileList]);

  const handleSingleMessage = useCallback((event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    if (!data.file_uid) return;

    setFileList((current) =>
      current.map((f) => (f.uid === data.file_uid ? applyFileResult(f, data) : f))
    );
  }, [setFileList]);

  // 建立 session 並把候選檔案標記為 processing；記下 provider 與模式供取消端點使用
  const beginSession = useCallback((candidates, provider, transcribeMode) => {
    const sessionId = randomId('session');
    registerTranscribeSession({
      sessionId,
      fileUids: candidates.map((f) => f.uid),
    });

    const candidateUids = new Set(candidates.map((f) => f.uid));
    setFileList((current) =>
      current.map((f) =>
        candidateUids.has(f.uid)
          ? {
              ...f,
              status: 'processing',
              statusText: '正在上傳檔案...',
              sessionId,
              provider,
              transcribeMode,
            }
          : f
      )
    );
    return sessionId;
  }, [setFileList]);

  const uploadFile = useCallback(async (file) => {
    const formData = new FormData();
    formData.append('file', file.originFileObj);
    const { filename } = await api.upload(formData);
    return filename;
  }, []);

  // 一般模式：每個 file uid 一條 WebSocket
  const startRegular = useCallback(async ({ provider, model, apiKey, prompt, defaults }) => {
    const candidates = fileList.filter(isRestartable);
    if (candidates.length === 0) {
      return { skipped: true };
    }

    const sessionId = beginSession(candidates, provider, 'single');

    const openTranscriptionSocket = (file, serverFilename) => {
      socketManager.openSocket(file.uid, WS_URLS.transcription(file.uid), {
        onOpen: () => {
          updateFile(file.uid, { statusText: '連線成功，正在提交任務...', serverFilename });
          const payload = buildSinglePayload({
            serverFilename: serverFilename ?? file.name,
            file,
            provider,
            model,
            apiKey,
            prompt,
            defaults,
            sessionId,
          });
          socketManager.sendMessage(file.uid, payload);
        },
        onMessage: handleSingleMessage,
        onError: () => {
          message.error(`檔案 ${file.name} 的連線發生錯誤。`);
          updateFile(file.uid, {
            status: 'error',
            percent: 100,
            error: '連線錯誤',
            statusText: '連線失敗',
          });
        },
      });
    };

    // 先 upload 拿到伺服器檔名再開 WS
    for (const file of candidates) {
      try {
        const serverFilename = await uploadFile(file);
        openTranscriptionSocket(file, serverFilename);
      } catch (error) {
        console.error(`上傳檔案 ${file.name} 失敗:`, error);
        updateFile(file.uid, {
          status: 'error',
          statusText: '上傳失敗',
          percent: 100,
        });
      }
    }

    return { skipped: false };
  }, [fileList, updateFile, socketManager, handleSingleMessage, beginSession, uploadFile]);

  // 批次模式：所有檔案共用一條 batch WebSocket
  const startBatch = useCallback(async ({ provider, model, apiKey, prompt, defaults }) => {
    const candidates = fileList.filter(isRestartable);
    if (candidates.length === 0) {
      return { skipped: true, reason: 'no-files' };
    }

    const sessionId = beginSession(candidates, provider, 'batch');

    const uploaded = [];
    for (const file of candidates) {
      try {
        const serverFilename = await uploadFile(file);
        uploaded.push({ ...file, serverFilename });
        updateFile(file.uid, {
          statusText: '檔案已上傳，等待批次處理...',
          serverFilename,
        });
      } catch (error) {
        console.error(`上傳檔案 ${file.name} 失敗:`, error);
        updateFile(file.uid, {
          status: 'error',
          statusText: '上傳失敗',
          percent: 100,
        });
      }
    }

    if (uploaded.length === 0) {
      message.error('所有檔案上傳失敗，無法啟動批次任務');
      return { skipped: true, reason: 'all-upload-failed' };
    }

    const batchId = randomId('batch');
    const uploadedUidSet = new Set(uploaded.map((f) => f.uid));

    socketManager.openSocket(batchId, WS_URLS.batch(batchId), {
      onOpen: () => {
        setFileList((current) =>
          current.map((f) =>
            uploadedUidSet.has(f.uid)
              ? { ...f, statusText: '批次任務已提交，等待處理...' }
              : f
          )
        );

        const payload = {
          files: uploaded.map((f) => ({
            filename: f.serverFilename,
            original_filename: f.name,
            file_uid: f.uid,
            // per-file 設定，後端優先於下方批次層級 fallback 使用
            source_lang: f.language || defaults.sourceLang,
            prompt: f.prompt ?? prompt,
            multi_speaker: f.isMultiSpeaker ?? defaults.multiSpeaker,
          })),
          provider,
          model,
          api_keys: apiKey,
          // 整個批次的 fallback 值
          source_lang: defaults.sourceLang,
          prompt,
          multi_speaker: defaults.multiSpeaker,
          session_id: sessionId,
        };
        socketManager.sendMessage(batchId, payload);
      },
      onMessage: (event) => {
        let data;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }

        if (data.status_code === 'BATCH_SUBMITTED') {
          // 送出成功：把仍在 processing 的批次檔案改成 batch_pending；
          // 主動關閉這條 socket，後續結果靠 recovery 取回
          setFileList((current) =>
            current.map((f) =>
              f.status === 'processing' && uploadedUidSet.has(f.uid)
                ? { ...f, status: 'batch_pending', statusText: data.status_text }
                : f
            )
          );
          message.success('批次任務已提交，可繼續其他操作。結果將自動更新或可稍後恢復。');
          onBatchSubmitted?.(batchId);
          socketManager.closeSocket(batchId, 1000);
          return;
        }

        if (data.status_code === 'BATCH_COMPLETED') {
          return;
        }

        if (data.file_uid) {
          setFileList((current) =>
            current.map((f) => (f.uid === data.file_uid ? applyFileResult(f, data) : f))
          );
        } else {
          // 整體進度文字（無 file_uid）→ 同步到所有 processing 中的檔案
          setFileList((current) =>
            current.map((f) =>
              f.status === 'processing' && uploadedUidSet.has(f.uid)
                ? { ...f, statusText: data.status_text }
                : f
            )
          );
        }
      },
      onError: () => {
        message.error('批次任務連線發生錯誤');
        setFileList((current) =>
          current.map((f) =>
            uploadedUidSet.has(f.uid) && f.status === 'processing'
              ? { ...f, status: 'error', percent: 100, error: '批次連線錯誤', statusText: '連線失敗' }
              : f
          )
        );
      },
    });

    return { skipped: false, batchId };
  }, [fileList, setFileList, updateFile, socketManager, onBatchSubmitted, beginSession, uploadFile]);

  return { startRegular, startBatch };
}
