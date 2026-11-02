"""把一組截圖（NN.png）排成一張對照表，每格標上時間點與說明；並比對變體的截圖是否和基準相同。

用法：
  python sheet.py sheet <截圖資料夾> <輸出.png> <標題>
  python sheet.py same <基準資料夾> <資料夾>...   # 印出每個資料夾和基準不同的時間點
"""
import pathlib
import subprocess
import sys

from times import TIMES

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def sheet(folder: pathlib.Path, target: pathlib.Path, title: str) -> None:
    args = ["montage", "-font", FONT, "-pointsize", "18", "-background", "#f4f4f4"]
    for i, (seconds, note) in enumerate(TIMES):
        shot = folder / f"{i:02d}.png"
        if shot.exists():
            args += ["-label", f"{seconds:g}s {note}", str(shot)]
    args += ["-tile", "4x", "-geometry", "480x270+6+6", "-title", title, str(target)]
    subprocess.run(args, check=True)


def differs(a: pathlib.Path, b: pathlib.Path) -> bool:
    result = subprocess.run(["compare", "-metric", "AE", str(a), str(b), "null:"],
                            capture_output=True, text=True)
    return result.stderr.strip() not in ("0", "0 (0)")


if __name__ == "__main__":
    if sys.argv[1] == "sheet":
        sheet(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]), sys.argv[4])
    else:
        base = pathlib.Path(sys.argv[2])
        for other in map(pathlib.Path, sys.argv[3:]):
            diff = [f"{TIMES[i][0]:g}s" for i in range(len(TIMES))
                    if (other / f"{i:02d}.png").exists()
                    and differs(base / f"{i:02d}.png", other / f"{i:02d}.png")]
            print(other.name, "相同" if not diff else "不同：" + "、".join(diff))
