#!/bin/bash
# Aegisub 3.2.2（Linux）開一個字幕檔並截圖：用法 aegisub_shot.sh <字幕檔> <輸出.png>
# Ubuntu 的 wxWidgets 會跳出 sizer 的 assertion 對話框，點掉之後才會載入檔案
export DISPLAY=:98 WXSUPPRESS_SIZER_FLAGS_CHECK=1
pkill -x aegisub-3.2; sleep 1
aegisub-3.2 "$1" > /dev/null 2>&1 &
sleep 6
for i in $(seq 1 8); do
  name=$(xdotool search --onlyvisible --name "Aegisub" 2>/dev/null | head -1 | xargs -r xdotool getwindowname)
  if [[ "$name" == *"$(basename "$1")"* ]]; then break; fi
  xdotool mousemove 526 129 click 1; sleep 0.3; xdotool mousemove 874 129 click 1; sleep 1.5
done
sleep 1
import -window root -crop 920x700+0+0 +repage "$2"
echo "$(basename "$(dirname "$1")") $(basename "$1"): window=[$name]"
