---
status: accepted
date: 2026-11-01
---

# 免安裝版不做程式碼簽章

免安裝版裡我們自己建置的 `Mimiji.exe` 沒有 Authenticode 簽章，隨包的 `ffmpeg.exe` 與 `ffprobe.exe` 也沒有（#35 實測）。使用者在 2026-11-01 決定：免安裝版永遠不做程式碼簽章，這是產品的規格，不是之後會補的限制；之後也不再評估（原本排在 v0.1 之後的程式碼簽章評估，草稿 v01-54，取消）。

## 後果

- 第一次執行 `Mimiji.exe` 時，Windows 可能顯示 SmartScreen 的「Windows 已保護您的電腦」，要按「其他資訊 → 仍要執行」。README 與 README.txt 要寫出這一步（#267、#281）；README 的「已知限制」不把它列成「之後的版本處理」。
- Smart App Control 開著的電腦，沒有簽章、Microsoft 也不認得的程式會被擋下，沒有「仍要執行」可以按，只能關掉 Smart App Control（[Microsoft 的說明](https://learn.microsoft.com/windows/apps/develop/smart-app-control/overview)）。免安裝版在這種電腦上實際會不會被擋、擋的是哪個檔案，以 #35 的實測為準，寫進 README。
- 發版流程不保管簽章用的憑證或金鑰，release workflow 沒有簽章的步驟。
- 有人提議加上程式碼簽章時，先回頭看這份決策。
