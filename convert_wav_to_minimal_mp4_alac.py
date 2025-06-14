import subprocess
import os


def get_audio_duration(file_path):
    """
    使用 ffprobe 獲取音訊檔案的時長 (秒)。
    """
    ffprobe_cmd = [
        "ffprobe",
        "-v", "error",             # 只顯示錯誤訊息
        "-show_entries", "format=duration",  # 只獲取時長資訊
        "-of", "default=noprint_wrappers=1:nokey=1",  # 以簡單的鍵值對輸出，且不帶鍵名
        file_path
    ]

    try:
        result = subprocess.run(
            ffprobe_cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        duration_str = result.stdout.strip()
        if not duration_str:
            print(f"錯誤：ffprobe 未能獲取 '{file_path}' 的時長 (輸出為空)。")
            return None
        return float(duration_str)
    except Exception as e:
        print(f"使用 ffprobe 獲取時長時發生未知錯誤: {e}")
        return None


def convert_wav_to_minimal_mp4_alac(input_wav_file):
    """
    將 .wav 檔案的音訊使用 ALAC 編碼轉換到 .mp4 容器中。
    輸出檔案名與輸入檔名相同，副檔名改為 .mp4。
    創建一個最小化的黑色視訊軌。

    參數:
    input_wav_file (str): 輸入的 .wav 檔案路徑。

    返回:
    bool: 轉換成功返回 True，否則返回 False。
    """
    if not os.path.exists(input_wav_file):
        print(f"錯誤：找不到輸入的 WAV 檔案 '{input_wav_file}'")
        return False

    base_name = os.path.splitext(input_wav_file)[0]
    output_mp4_file = base_name + ".mp4"

    # 檢查 FFmpeg 是否安裝
    try:
        # 使用 capture_output=True, text=True 避免版本資訊直接印到控制台
        # check=True 會在 FFmpeg 未找到或返回錯誤時拋出例外
        subprocess.run(["ffmpeg", "-version"], capture_output=True,
                       text=True, check=True, encoding='utf-8')
    except FileNotFoundError:
        print("錯誤：找不到 FFmpeg。請確保 FFmpeg 已安裝並已加入到系統 PATH 中。")
        return False
    except subprocess.CalledProcessError:
        # FFmpeg 存在但執行 -version 出錯（不太可能，但以防萬一）
        print("錯誤：執行 FFmpeg 版本檢查時出錯。")
        return False
    except Exception as e:
        print(f"檢查 FFmpeg 時發生未知錯誤: {e}")
        return False

    lavfi_video_source = f"color=c=black:s=2x2:r=1:d={audio_duration}"

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",  # 自動覆蓋輸出檔案
        "-i", input_wav_file,  # 輸入 WAV 檔案
        # 創建一個持續的、最小的黑色視訊軌，-shortest 會使其與音訊等長
        "-f", "lavfi",
        "-i", lavfi_video_source,  # 1x1 像素, 1fps 黑色畫面
        "-c:v", "libx264",       # H.264 視訊編碼
        "-tune", "stillimage",   # 針對靜態內容優化
        "-profile:v", "baseline",  # 使用 Baseline profile 增加相容性
        "-level", "3.0",
        "-pix_fmt", "yuv420p",   # 像素格式，提高相容性
        "-c:a", "alac",          # 音訊編碼器 (ALAC - Apple Lossless)
        "-sample_fmt", "s32p",
        output_mp4_file
    ]

    print(f"正在將 '{input_wav_file}' 轉換為 '{output_mp4_file}' (ALAC 音訊)...")

    try:
        # 設定 encoding 和 errors 以處理可能的輸出字元問題
        process = subprocess.run(ffmpeg_cmd, capture_output=True,
                                 text=True, check=True, encoding='utf-8', errors='replace')
        print("轉換成功！")
        # 如果需要查看 FFmpeg 的詳細輸出 (即使成功時也可能有很多訊息)，可以取消以下註解
        # if process.stderr:
        #     print("FFmpeg 輸出:\n", process.stderr)
        return True
    except Exception as e:
        print(f"執行 FFmpeg 時發生未預期的錯誤: {e}")
        return False


# --- 使用範例 ---
if __name__ == "__main__":
    # 您需要將 'YOUR_AUDIO_FILE.wav' 替換成您實際的 WAV 檔案名稱和路徑
    # 例如: input_file = "my_song.wav"
    # 或者: input_file = "/path/to/my/audio/track.wav"
    input_file = "Track1.wav"

    audio_duration = get_audio_duration(input_file)

    convert_wav_to_minimal_mp4_alac(input_file)
