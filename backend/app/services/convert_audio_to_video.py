import subprocess
from pathlib import Path


def convert_audio_to_mp4(input_path: Path) -> Path:
    """
    將任何 ffmpeg 支援的音訊檔案轉換為帶有 ALAC 無損音訊的 MP4 檔案。

    這個函式會建立一個最小的黑色視訊軌，並將音訊軌使用 ALAC 編碼。
    返回新建立的 MP4 檔案的路徑。
    如果轉換失敗，則會引發異常。

    :param input_path: 輸入音訊檔案的 Path 物件。
    :return: 輸出 MP4 檔案的 Path 物件。
    """
    if not input_path.exists():
        raise FileNotFoundError(f"找不到輸入的音訊檔案: '{input_path}'")

    output_path = input_path.with_suffix(".mp4")

    # 使用 ffprobe 獲取音訊時長
    ffprobe_cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)
    ]
    try:
        duration_result = subprocess.run(
            ffprobe_cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        duration = float(duration_result.stdout.strip())
    except Exception as e:
        print(f"無法獲取音訊時長: {e}")
        raise RuntimeError(f"無法獲取 '{input_path.name}' 的音訊時長。") from e

    # FFmpeg 命令，使用 ALAC 編碼
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",  # 自動覆蓋輸出檔案
        "-i", str(input_path),
        "-f", "lavfi",
        "-i", f"color=c=black:s=2x2:r=1:d={duration}",
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "alac",
        "-sample_fmt", "s32p",
        str(output_path)
    ]

    print(f"正在將 '{input_path.name}' 轉換為帶有 ALAC 音訊的 MP4...")
    try:
        subprocess.run(ffmpeg_cmd, check=True,
                       capture_output=True, text=True, encoding='utf-8')
        print(f"成功轉換檔案至 '{output_path.name}'")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg 轉換失敗。返回碼: {e.returncode}")
        print(f"FFmpeg 錯誤輸出:\n{e.stderr}")
        raise RuntimeError(f"使用 FFmpeg 轉換檔案 '{input_path.name}' 時失敗。") from e
    except FileNotFoundError:
        print("找不到 FFmpeg。請確保 FFmpeg 已安裝並已加入到系統 PATH 中。")
        raise RuntimeError("伺服器錯誤：找不到 FFmpeg 執行檔。")
