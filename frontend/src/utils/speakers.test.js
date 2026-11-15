import { describe, it, expect } from 'vitest';
import {
  NO_SPEAKER_LABEL,
  SPEAKER_NAME_MAX_LENGTH,
  choiceLabel,
  nextSpeakerAfter,
  reassignMessage,
  renameMessage,
  shownSpeaker,
  showsAsCorrected,
  speakerChoices,
  speakerCounts,
  speakerText,
  speakerNameProblem,
} from './speakers';

/** 片段裡用得到的欄位：校正後與原始轉錄的文字與說話者。 */
const seg = (speaker, { originalSpeaker = speaker, text = 'A', originalText = text } = {}) => ({
  seg_key: Math.random().toString(36), start: 0, speaker, original_speaker: originalSpeaker, text, original_text: originalText,
  corrected: speaker !== originalSpeaker || text !== originalText, deleted: false, has_correction_records: false,
});

describe('speakerCounts：每位說話者有幾個片段（#354）', () => {
  it('照號碼排序（S2 在 S10 前面），沒有說話者的片段排在最後', () => {
    const segments = [seg('S10'), seg('S2'), seg(null), seg('S0'), seg('S2'), seg(undefined)];
    expect(speakerCounts(segments)).toEqual([['S0', 1], ['S2', 2], ['S10', 1], [null, 2]]);
  });

  it('看校正後的說話者，不看原始轉錄', () => {
    expect(speakerCounts([seg('S0', { originalSpeaker: 'S3' })])).toEqual([['S0', 1]]);
  });

  it('沒有片段時是空的', () => {
    expect(speakerCounts([])).toEqual([]);
  });
});

describe('speakerChoices：選單上可以換成的說話者', () => {
  it('現有的其他說話者，加上新的說話者', () => {
    expect(speakerChoices(['S0', 'S1', 'S2'], 'S1', 'S3')).toEqual([
      { speaker: 'S0', isNew: false }, { speaker: 'S2', isNew: false }, { speaker: 'S3', isNew: true },
    ]);
  });

  it('沒有說話者的片段：現有的每一位都可以選', () => {
    expect(speakerChoices(['S0'], null, 'S1')).toEqual([{ speaker: 'S0', isNew: false }, { speaker: 'S1', isNew: true }]);
  });
});

describe('nextSpeakerAfter：新的說話者編號（#354 第 1 點）', () => {
  it('取後端給的編號與片段裡的說話者之後，較大的那個', () => {
    expect(nextSpeakerAfter('S2', [seg('S0'), seg('S1')])).toBe('S2');
    expect(nextSpeakerAfter('S2', [seg('S0'), seg('S2')])).toBe('S3');
    expect(nextSpeakerAfter('S2', [seg('S10')])).toBe('S11');
  });

  it('只會變大：指定了新的說話者又復原，那個編號也不再給（後端也照這樣算）', () => {
    expect(nextSpeakerAfter('S3', [seg('S0')])).toBe('S3');
  });

  it('沒有任何說話者時從 S0 起', () => {
    expect(nextSpeakerAfter('S0', [seg(null)])).toBe('S0');
  });
});

describe('shownSpeaker：片段那一列寫的說話者', () => {
  it('存檔中與失敗時寫送出的說話者，其他時候寫片段現在的說話者', () => {
    const segment = seg('S0');
    expect(shownSpeaker(segment, undefined)).toBe('S0');
    expect(shownSpeaker(segment, { status: 'saving', request: { speaker: 'S1' } })).toBe('S1');
    expect(shownSpeaker(segment, { status: 'failed', request: { speaker: 'S2' }, message: 'x' })).toBe('S2');
    expect(shownSpeaker(segment, { status: 'saved' })).toBe('S0');
  });

  it('送出的只有文字時照片段現在的說話者', () => {
    expect(shownSpeaker(seg('S0'), { status: 'saving', request: { text: 'B' } })).toBe('S0');
  });
});

describe('showsAsCorrected：要不要標「校正過」', () => {
  it('照模型分出的說話者顯示時，文字或說話者改過都算', () => {
    expect(showsAsCorrected(seg('S1', { originalSpeaker: 'S0' }), false)).toBe(true);
    expect(showsAsCorrected(seg('S0', { text: 'B', originalText: 'A' }), false)).toBe(true);
    expect(showsAsCorrected(seg('S0'), false)).toBe(false);
  });

  it('整份當成同一位說話者時不顯示說話者，只改過說話者的片段不標', () => {
    expect(showsAsCorrected(seg('S1', { originalSpeaker: 'S0' }), true)).toBe(false);
    expect(showsAsCorrected(seg('S1', { originalSpeaker: 'S0', text: 'B', originalText: 'A' }), true)).toBe(true);
  });
});

describe('reassignMessage：全部換成另一位之後寫的結果', () => {
  it('寫出換了幾個片段、換成誰', () => {
    expect(reassignMessage(3, 'S0')).toBe('已把 3 個片段換成 S0');
  });

  it('換成的那一位取了名字時寫名稱（#359）', () => {
    expect(reassignMessage(3, 'S0', { S0: '王小明' })).toBe('已把 3 個片段換成 王小明');
  });
});

describe('speakerText：片段那一列寫的說話者（#359）', () => {
  it('取了名字的寫名稱，沒取的寫說話者編號', () => {
    const names = { S0: '王小明' };
    expect(speakerText('S0', names)).toBe('王小明');
    expect(speakerText('S1', names)).toBe('S1');
  });

  it('沒有說話者的片段寫「未指定」', () => {
    expect(speakerText(null, { S0: '王小明' })).toBe(NO_SPEAKER_LABEL);
  });
});

describe('choiceLabel：說話者選單上一個選項的寫法（#359）', () => {
  it('取了名字的寫名稱，括號裡是說話者編號；沒取的寫編號', () => {
    const names = { S0: '王小明' };
    expect(choiceLabel({ speaker: 'S0', isNew: false }, names)).toBe('王小明（S0）');
    expect(choiceLabel({ speaker: 'S1', isNew: false }, names)).toBe('S1');
  });

  it('新的說話者還沒有名字', () => {
    expect(choiceLabel({ speaker: 'S3', isNew: true }, {})).toBe('新的說話者（S3）');
  });
});

describe('speakerNameProblem：名稱哪裡不合規則（#359 第 6 點，和後端同一套規則）', () => {
  it('合規則時是 null：前後的空白不算，空的是清掉名稱', () => {
    expect(speakerNameProblem('王小明')).toBeNull();
    expect(speakerNameProblem(`  ${'名'.repeat(SPEAKER_NAME_MAX_LENGTH)} `)).toBeNull();
    expect(speakerNameProblem('')).toBeNull();
    expect(speakerNameProblem('   ')).toBeNull();
    expect(speakerNameProblem('Sam')).toBeNull();
  });

  it('超過 30 個字', () => {
    expect(speakerNameProblem('名'.repeat(31))).toBe('名稱最多 30 個字');
  });

  it('有方括號', () => {
    for (const name of ['[王小明]', '王]', 'a[b']) {
      expect(speakerNameProblem(name)).toBe('名稱不能有方括號（[ 或 ]）');
    }
  });

  it('寫成 S 加數字（全形與小寫也算）', () => {
    for (const name of ['S1', 's12', 'Ｓ１']) {
      expect(speakerNameProblem(name)).toBe('名稱不能寫成 S 加數字，會和說話者編號分不出來');
    }
  });

  it('寫成時間（全形也算）：LRC 的播放器會把它當成時間戳', () => {
    for (const name of ['00:05.00', '1:02', '12:30:15', '００：０５']) {
      expect(speakerNameProblem(name)).toBe('名稱不能寫成時間（例如 00:05.00），LRC 會把它當成時間戳');
    }
  });

  it('帶數字但不是編號也不是時間的名稱可以', () => {
    for (const name of ['Sam 2', '第 2 位來賓', 'S1 的助理', '10 點的客人']) {
      expect(speakerNameProblem(name)).toBeNull();
    }
  });
});

describe('renameMessage：取名字之後「復原」旁邊寫的結果（#359）', () => {
  it('取了名字、改了名字與清掉名字', () => {
    expect(renameMessage('S0', '王小明')).toBe('已把 S0 叫做「王小明」');
    expect(renameMessage('S0', null)).toBe('S0 已改回顯示說話者編號');
  });
});
