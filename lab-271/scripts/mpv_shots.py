"""mpv 在每個時間點的畫面（含字幕），每種變體、Multi-Speaker 開關、輸出格式各一組。

用法：python mpv_shots.py <工作資料夾>
輸出：<工作資料夾>/mpv/<變體>-<on|off>-<格式>/NN.png
"""
import pathlib
import subprocess
import sys

from times import TIMES

ROOT = pathlib.Path(sys.argv[1])
VIDEO = ROOT / "subtitle-test.mp4"


def frame(sub: pathlib.Path, seconds: float, target: pathlib.Path) -> None:
    # 編碼模式把字幕燒進輸出的畫面；--vo=image 在 0.37 遇到某些畫面會 assert 失敗
    subprocess.run(["mpv", "--no-config", "--really-quiet", "--ao=null", f"--start={seconds}",
                    "--frames=1", f"--o={target}", "--ovc=png", f"--sub-file={sub}", str(VIDEO)],
                   check=True, timeout=60)


for variant in ["utf8-lf", "utf8bom-lf", "utf8-crlf", "utf8bom-crlf"]:
    for ms in ["on", "off"]:
        for ext in ["srt", "vtt", "lrc"]:
            sub = ROOT / "variants" / variant / ms / f"subtitle-test.{ext}"
            out = ROOT / "mpv" / f"{variant}-{ms}-{ext}"
            out.mkdir(parents=True, exist_ok=True)
            for i, (seconds, _) in enumerate(TIMES):
                frame(sub, seconds, out / f"{i:02d}.png")
            print("done", out.name, flush=True)
