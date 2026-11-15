import { useState } from 'react';
import { message } from 'antd';
import { api } from '../services/api';
import { saveFailureMessage } from '../utils/segmentCorrections';

/**
 * 校正頁「整份當成同一位說話者」與「照模型分出的說話者顯示」的切換（#354）。改的是任務的設定，不算校正：不留校正
 * 紀錄，沒有「復原」，也不重新轉錄；下載帶不帶說話者標記跟著它變。
 *
 * 按下去畫面先切過去，存不進去時切回來並寫原因。存的時候不能再按。
 *
 * 切換改寫任務的說話者人數（#352）：整份當成同一位是 1 人，照模型分出的說話者顯示是 'auto'；speakerCount 是存好之後
 * 任務記下的人數，校正頁照它提醒人數不同（#351 第 4 點）。
 *
 * @param {string} taskUuid
 * @param {boolean} initial GET /transcripts/{task_uuid} 的 single_speaker
 * @param {'auto' | number | null} [initialCount] GET /transcripts/{task_uuid} 的 speaker_count
 */
export function useSingleSpeaker(taskUuid, initial, initialCount = null) {
  const [singleSpeaker, setSingleSpeaker] = useState(initial);
  const [speakerCount, setSpeakerCount] = useState(initialCount);
  const [switching, setSwitching] = useState(false);

  /** @param {boolean} single 切換成整份當成同一位說話者（true），或照模型分出的說話者顯示（false） */
  const switchTo = async (single) => {
    if (switching || single === singleSpeaker) return;
    setSingleSpeaker(single);
    setSwitching(true);
    try {
      const settings = await api.transcripts.updateSettings(taskUuid, { single_speaker: single });
      setSingleSpeaker(settings.single_speaker);
      setSpeakerCount(settings.speaker_count ?? null);
    } catch (error) {
      setSingleSpeaker(!single);
      message.error(`沒有切換：${saveFailureMessage(error)}`);
    } finally {
      setSwitching(false);
    }
  };

  return { singleSpeaker, speakerCount, switching, switchTo };
}
