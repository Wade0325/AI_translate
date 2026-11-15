import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { replacementPlan, searchSegments, stepMatch } from '../utils/segmentSearch';

/**
 * 校正頁的尋找（#356）：尋找列開著沒有、要找與取代的文字、符合的片段，以及現在是第幾個。比對的規則在
 * utils/segmentSearch.js。
 *
 * 換到一個符合的片段（打了要找的字、按上一個或下一個）時，reveal 換成一個新的物件，片段列表把那一列捲到看得到的
 * 地方；同時呼叫 onReveal，由頁面停止跟著播放捲動，免得播放把畫面拉回去。
 *
 * @param {import('../utils/segmentSearch').SearchableSegment[]} segments 校正後版本的片段
 * @param {{ onReveal: () => void }} options
 */
export function useSegmentSearch(segments, { onReveal }) {
  const [open, setOpen] = useState(false);
  const [query, setQueryState] = useState('');
  const [replacement, setReplacement] = useState('');
  const [current, setCurrent] = useState(-1);
  const [focusRequest, setFocusRequest] = useState(0);
  const [reveal, setReveal] = useState(/** @type {{ index: number } | null} */ (null));

  const matches = useMemo(() => (open ? searchSegments(segments, query) : []), [open, segments, query]);
  // 改了片段之後符合的片段可能變少：停在還在範圍裡的那一個
  const currentIndex = matches.length ? Math.min(Math.max(current, 0), matches.length - 1) : -1;
  const ranges = useMemo(() => new Map(matches.map((m) => [m.segKey, m.ranges])), [matches]);
  const plan = useMemo(
    () => (open ? replacementPlan(segments, query, replacement) : null),
    [open, segments, query, replacement],
  );

  // 事件處理讀最新的內容，actions 的身分才能不變
  const latest = useRef({ segments, matches, currentIndex, onReveal });
  useLayoutEffect(() => {
    latest.current = { segments, matches, currentIndex, onReveal };
  });

  const actions = useMemo(() => {
    const goTo = (index, found) => {
      setCurrent(index);
      if (index >= 0) {
        setReveal({ index: found[index].index });
        latest.current.onReveal();
      }
    };
    return {
      /** 打開尋找列（Ctrl+F），焦點放進尋找框；有選取的文字時拿它來找。 */
      openFind(prefill = '') {
        setOpen(true);
        setFocusRequest((n) => n + 1);
        if (prefill) {
          setQueryState(prefill);
          goTo(0, searchSegments(latest.current.segments, prefill));
        }
      },
      close() {
        setOpen(false);
        setReveal(null);
      },
      /** 改了要找的字：跳到第一個符合的片段。 */
      setQuery(value) {
        setQueryState(value);
        const found = searchSegments(latest.current.segments, value);
        goTo(found.length ? 0 : -1, found);
      },
      setReplacement,
      /** 上一個或下一個符合的片段。 */
      step(direction) {
        const { matches: found, currentIndex: at } = latest.current;
        goTo(stepMatch(at, found.length, direction), found);
      },
    };
  }, []);

  return {
    open,
    query,
    replacement,
    matches,
    currentIndex,
    currentKey: currentIndex >= 0 ? matches[currentIndex].segKey : null,
    ranges,
    plan,
    focusRequest,
    reveal,
    actions,
  };
}
