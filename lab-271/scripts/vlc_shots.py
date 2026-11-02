"""VLC 3.0（Linux）在每個時間點的畫面：在 Xvfb :99 上以 vlcuser 執行 cvlc，從時間點前 1.5 秒開始播放，
用 --stop-time 與 --play-and-pause 停在時間點上，再截圖。

暫停要約 0.3 秒才生效，所以停止時間提早 0.3 秒；畫面上方燒進的時間碼才是截圖的實際時間，判讀時以它為準。
（用 RC 介面 seek 加逐格的做法不可靠：逐格中開始的字幕不會顯示，逐格之後再 seek 也不顯示字幕。）

用法：python vlc_shots.py <工作資料夾>（字幕與影片要先複製到 /home/vlcuser/t）
輸出：<工作資料夾>/vlc/<變體>-<on|off>-<格式>/NN.png。基準（utf8-lf）每個時間點都截；其他變體只截
第一則字幕、重疊、特殊字元與 1:00.00 四個時間點。
"""
import pathlib
import subprocess
import sys
import time

from times import TIMES

ROOT = pathlib.Path(sys.argv[1])
FILES = pathlib.Path("/home/vlcuser/t")
VARIANT_POINTS = [1, 6, 7, 13]


def shot(sub: pathlib.Path, seconds: float, target: pathlib.Path) -> None:
    subprocess.run(["pkill", "-u", "vlcuser", "vlc"], check=False)
    time.sleep(0.3)
    start, stop = max(0.0, seconds - 1.5), max(0.1, seconds - 0.3)
    subprocess.Popen(["su", "vlcuser", "-c",
                      f"DISPLAY=:99 cvlc --no-video-title-show --no-osd --no-audio --vout=xcb_x11 "
                      f"--start-time={start} --stop-time={stop} --play-and-pause --sub-file='{sub}' "
                      f"'{FILES}/subtitle-test-k1.mp4' > /dev/null 2>&1"])
    time.sleep(4.5)
    subprocess.run(["import", "-display", ":99", "-window", "root", "-crop", "640x360+0+0",
                    "+repage", str(target)], check=True)


for variant in ["utf8-lf", "utf8bom-lf", "utf8-crlf", "utf8bom-crlf"]:
    points = range(len(TIMES)) if variant == "utf8-lf" else VARIANT_POINTS
    for ms in ["on", "off"]:
        for ext in ["srt", "vtt", "lrc"]:
            out = ROOT / "vlc" / f"{variant}-{ms}-{ext}"
            out.mkdir(parents=True, exist_ok=True)
            for i in points:
                shot(FILES / "variants" / variant / ms / f"subtitle-test.{ext}", TIMES[i][0],
                     out / f"{i:02d}.png")
            print("done", out.name, flush=True)
subprocess.run(["pkill", "-u", "vlcuser", "vlc"], check=False)
