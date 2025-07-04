import torch
import soundfile as sf
from pprint import pprint
import os
import sys
from typing import Tuple, Optional
from pathlib import Path


class VADService:
    """
    一個封裝了 Silero VAD 模型和相關功能的服務類別。
    模型在服務實例化時載入一次，以供重複使用。
    """

    def __init__(self):
        """
        初始化服務並載入 VAD 模型。
        """
        print("Initializing VADService and loading Silero VAD model...")
        self.SAMPLING_RATE = 16000
        try:
            self.model, self.utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False
            )
            print("VAD model loaded successfully.")
        except Exception as e:
            print(f"FATAL: Failed to load VAD model: {e}")
            # 如果模型載入失敗，讓應用程式無法啟動是合理的
            raise e

    def split_audio_on_silence(
        self,
        audio_path: str,
        min_silence_duration: float = 1.0,
        output_dir: str = '.'
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """
        從音檔中點後，尋找第一個長度足夠的靜音區間並進行切割。
        使用階層式命名法來命名檔案 (e.g., base.part1.wav, base.part1.part2.wav)。

        Args:
            audio_path (str): 輸入音檔路徑。
            min_silence_duration (float): 尋找的最短靜音時長（秒）。
            output_dir (str): 輸出分割音檔的目錄。

        Returns:
            tuple: 一個包含 (part1_path, part2_path, split_point_time) 的元組。
                   如果找不到分割點，則回傳 (None, None, None)。
        """
        (get_speech_timestamps, _, read_audio, _, _) = self.utils

        try:
            wav = read_audio(audio_path, sampling_rate=self.SAMPLING_RATE)
            total_duration = len(wav) / self.SAMPLING_RATE
            midpoint_time = total_duration / 2
        except Exception as e:
            print(f"Error reading audio file '{audio_path}': {e}")
            return None, None, None

        speech_timestamps = get_speech_timestamps(
            wav, self.model, sampling_rate=self.SAMPLING_RATE, return_seconds=True)

        silent_timestamps = []
        last_speech_end = 0.0
        for segment in speech_timestamps:
            if segment['start'] > last_speech_end:
                silent_timestamps.append(
                    {'start': round(last_speech_end, 3), 'end': round(segment['start'], 3)})
            last_speech_end = segment['end']
        if last_speech_end < total_duration:
            silent_timestamps.append(
                {'start': round(last_speech_end, 3), 'end': round(total_duration, 3)})

        split_point_time = None
        for silence in silent_timestamps:
            silence_duration = silence['end'] - silence['start']
            if silence['start'] >= midpoint_time and silence_duration >= min_silence_duration:
                split_point_time = silence['start']
                break

        if split_point_time is None:
            return None, None, None

        split_point_sample = int(split_point_time * self.SAMPLING_RATE)
        audio_part1 = wav[:split_point_sample]
        audio_part2 = wav[split_point_sample:]

        os.makedirs(output_dir, exist_ok=True)

        base_name = Path(audio_path).stem
        suffix = Path(audio_path).suffix

        # 新的階層式命名法，不再使用隨機 unique_id
        output_path1 = os.path.join(output_dir, f"{base_name}.part1{suffix}")
        output_path2 = os.path.join(output_dir, f"{base_name}.part2{suffix}")

        print(
            f"Splitting '{Path(audio_path).name}' into '{Path(output_path1).name}' and '{Path(output_path2).name}'")

        sf.write(output_path1, audio_part1, self.SAMPLING_RATE)
        sf.write(output_path2, audio_part2, self.SAMPLING_RATE)

        return output_path1, output_path2, split_point_time


def main():
    """
    主函式，用於獨立測試 VADService 的功能。
    """
    # 在 'tests' 資料夾下定義輸入和輸出資料夾
    base_dir = "tests"
    input_dir = os.path.join(base_dir, "audio_input")
    output_dir = os.path.join(base_dir, "audio_output")

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    supported_extensions = ['.wav', '.mp3', '.flac', '.m4a']
    try:
        audio_files = [f for f in os.listdir(input_dir) if os.path.splitext(f)[
            1].lower() in supported_extensions]
    except OSError as e:
        print(f"Error reading from input directory '{input_dir}': {e}")
        sys.exit(1)

    if not audio_files:
        print(f"No audio files found in '{input_dir}'.")
        print(
            f"Please place supported audio files ({', '.join(supported_extensions)}) in there to test.")
        sys.exit(0)

    print(
        f"Found {len(audio_files)} file(s) in '{input_dir}'. Initializing VADService...")

    # 初始化服務
    try:
        vad_service = VADService()
    except Exception:
        print("Exiting due to VAD model loading failure.")
        sys.exit(1)

    for file_name in audio_files:
        audio_path = os.path.join(input_dir, file_name)
        print(f"\n--- Processing file: {file_name} ---")

        vad_service.split_audio_on_silence(
            audio_path=audio_path,
            min_silence_duration=1.0,
            output_dir=output_dir
        )
        print(f"--- Finished processing: {file_name} ---")


if __name__ == '__main__':
    main()
