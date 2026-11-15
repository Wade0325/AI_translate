import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * 校正頁的播放器（#347）：包住一個沒有原生控制列的 <audio>，給播放列與片段列表需要的狀態與動作。
 *
 * 播放時每一格畫面讀一次目前的時間（timeupdate 一秒只有約 4 次，逐字標示會一頓一頓的）；暫停時
 * 由 seek 與 timeupdate 更新。把 audioProps 展開到 <audio> 上才會接上事件。
 */
export function useAudioPlayer() {
  /** @type {import('react').RefObject<HTMLAudioElement | null>} */
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(/** @type {number | null} */ (null));
  const [rate, setRateState] = useState(1);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!playing) return undefined;
    let frame = 0;
    const tick = () => {
      if (audioRef.current) setTime(audioRef.current.currentTime);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  const readDuration = useCallback((event) => {
    const value = event.currentTarget.duration;
    if (Number.isFinite(value) && value > 0) setDuration(value);
  }, []);

  const audioProps = {
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onEnded: () => setPlaying(false),
    onLoadedMetadata: readDuration,
    onDurationChange: readDuration,
    onTimeUpdate: (event) => setTime(event.currentTarget.currentTime),
    onError: () => {
      setPlaying(false);
      setFailed(true);
    },
  };

  const play = useCallback(() => {
    // 瀏覽器拒絕播放（例如音檔讀不到）時，<audio> 自己會再發 error 事件
    audioRef.current?.play().catch(() => {});
  }, []);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) play();
    else audio.pause();
  }, [play]);

  /** 跳到 t 秒；andPlay 時接著播放（點片段的時間或一個字）。 */
  const seek = useCallback((t, { andPlay = false } = {}) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = t;
    setTime(t);
    if (andPlay) play();
  }, [play]);

  /** 從現在的位置前進 seconds 秒（負的是倒退），不超出音檔的頭尾；播放中的照樣播放。 */
  const skip = useCallback((seconds) => {
    const audio = audioRef.current;
    if (!audio) return;
    const end = Number.isFinite(audio.duration) ? audio.duration : Infinity;
    const t = Math.min(Math.max(audio.currentTime + seconds, 0), end);
    audio.currentTime = t;
    setTime(t);
  }, []);

  const setRate = useCallback((value) => {
    const audio = audioRef.current;
    if (audio) {
      // defaultPlaybackRate 也要設：有些瀏覽器重新載入音檔時會把 playbackRate 換回預設值
      audio.defaultPlaybackRate = value;
      audio.playbackRate = value;
    }
    setRateState(value);
  }, []);

  return { audioRef, audioProps, playing, time, duration, rate, failed, toggle, seek, skip, setRate };
}
