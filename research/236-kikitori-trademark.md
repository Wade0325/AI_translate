# 產品名稱 Kikitori 的商標與撞名

研究票 #236，查的是 #26 的前置問題：暫定的產品名稱 **Kikitori**（日文「聞き取り」：聽取、聽懂）能不能用。產品是給 Windows 個人使用者的免費開源（Apache-2.0）轉錄工具，發布成 `Kikitori.exe`、`Kikitori-v0.1.0-win64.zip`。

- 要回答的問題：
  1. **商標**：台灣 TIPO、日本 JPO（J-PlatPat）、美國 USPTO、歐盟 EUIPO、WIPO Global Brand Database（與 TMview）裡，有沒有 `Kikitori` 或近似名稱的登記或申請。重點是第 9 類（下載的軟體）與第 42 類（線上軟體服務），第 41 類（教育）一併記下。近似名稱包括 `KikiTori`、`Kiki Tori`、「聞き取り」、「聞取り」、「キキトリ」、「ききとり」。
  2. **撞名**：GitHub、PyPI、npm、Microsoft Store、App Store、Google Play 上，有沒有同名或很像的語音、轉錄、字幕或聽力相關產品。`kikitori.com`、`.app`、`.dev`、`.io` 有沒有被註冊、拿來做什麼。
- 查詢日期：2026-10-28，所有來源都在這天讀取。
- 只引用第一手來源：商標局的資料庫或它前端用的 API、套件註冊處、應用商店、RDAP 與 DNS、網站本身。搜尋引擎只用來找線索。段落後面的 [Sn] 連到該頁，並對到文末〈來源〉表。
- 「沒查到」只代表在寫明的查法下沒有結果，不等於「沒有登記」。查不到的資料庫寫在 §4。
- 這是查詢整理，不是法律意見。標「推論」的地方是我從資料推出來的，資料沒有逐字寫。

## 短答

| 資料庫或平台 | 查到什麼 | 來源 |
|---|---|---|
| 台灣 TIPO | 沒有 `KIKITORI`，也沒有含「聞き取り」「聞取り」「キキトリ」「ききとり」的商標。第 9、41、42 類最接近的是 KIKITRADE、Kiiroitori、KiKiper 這類，推論近似程度低（§1.1）。 | [S1] [S2] |
| 日本 J-PlatPat | 沒能查。所有網址都被轉到 `reject_sorry.html`，頁面寫系統維護中。 | [S3] |
| 美國 USPTO | 沒有 `KIKITORI`、`KIKI TORI` 或近似拼法，譯文欄位也沒有。 | [S4] [S5] |
| 歐盟 EUIPO | 沒能查。eSearch plus 的連線沒有回應。 | [S6] |
| WIPO Global Brand Database | 沒能查。首頁是 ALTCHA 驗證頁。 | [S7] |
| TMview | 沒能查。網頁殼載得到，檢索 API 沒有回應。 | [S8] |
| GitHub | 確認了 4 個名為 kikitori 的 repo，另有 1 個已改名。其中 2 個是 Windows 的本機轉錄或字幕工具，已經發布安裝檔（§2.1）。另有一個空的組織 `kikitori`。 | [S14] [S16] [S18] [S19] [S20] [S21] |
| PyPI | 沒有名稱含 kikitori 的專案。 | [S10] [S11] |
| npm | `kikitori` 回 404。scope `@kikitori` 底下有一個無關的套件。 | [S12] [S13] |
| App Store（iOS） | 3 款叫 Kikitori 的端末內轉錄 app，2026-07 到 10 月上架。另有 1 款聽力學習 app 在美國商店叫 Kikitori，以及一家叫 kikitori Co., Ltd. 的公司。 | [S22] [S23] |
| Mac App Store | 1 款 Kikitori：本機 Whisper 語音輸入，2026-08-27 上架。 | [S29] [S30] |
| Microsoft Store | 沒有。US、JP、TW 市集的搜尋結果都沒有同名 app。 | [S31] |
| Google Play | 沒有。en-US 與 ja-JP 的搜尋結果都沒有同名 app。 | [S32] |
| `kikitori.com` | 已註冊（2000-04-10，Register.com）。HTTPS 連不上，看不到用途。 | [S34] [S35] |
| `kikitori.app` | 已註冊（2025-09-04，Cloudflare）。網站是 Cloudflare 的預設歡迎頁。 | [S36] [S37] |
| `kikitori.dev` | Registry 的 RDAP 回「kikitori.dev not found」。推論：沒人註冊。 | [S38] |
| `kikitori.io` | .io 沒有 RDAP。.io 的權威 DNS 回 NXDOMAIN。推論：沒人註冊，但沒查到 WHOIS。 | [S39] [S40] [S41] |

商標方面，台灣與美國沒查到，但日本、歐盟與 WIPO 這次都查不到。撞名方面，同名、同類的轉錄與字幕軟體已經有好幾個，其中 2 個和本產品一樣是 Windows 的本機轉錄工具。結論見 §3。

## 1. 商標

### 1.1 台灣 TIPO

- 查法：商標檢索系統 [S1] 的「文字」檢索。前端把檢索詞送到 `POST /api/search/wordSearch`（body 是 `{"tmarkDraft": "<檢索詞>"}`），再用 `POST /api/result/list` 取回每筆的詳細資料 [S2]。我照同樣的方式呼叫。
- 前端送出前會刪掉空白（`t.text.replace(/\s+/g,"")`），所以 `Kiki Tori` 等於 `KikiTori` [S2]。
- 系統的資料更新日期是 2026-10-27（`/api/common/dataUpdateDate` 回 `{"dataUpdateDate":"2026-10-27"}`）[S2]。
- 這個檢索會回傳拼法或讀音相近的商標，不限類別。例如用 `kikitori` 查，前兩筆是「淇淇吃KIKI EAT及圖」與「心裡麵 YAKITORI 及圖」[S2]。

| 檢索詞 | 回傳筆數 | 有沒有含 KIKITORI 或日文寫法的商標 |
|---|---|---|
| `kikitori` | 382 | 沒有 |
| `KikiTori` | 382（和上一列相同） | 沒有 |
| 聞き取り | 138 | 沒有 |
| 聞取り | 117 | 沒有 |
| キキトリ | 78 | 沒有 |
| ききとり | 65 | 沒有 |

我把六次共 1,162 筆（含重複）的商標名稱、圖樣英文與圖樣日文合起來篩選，條件是「同時含 kiki 與 tor」或「含聞き取、聞取、キキトリ、ききとり」。只篩出兩筆，都不在第 9、41、42 類 [S2]：

- kikistory及圖（申請號 106038575，兆宥企業有限公司，第 21、24、25、28 類）。
- 奇奇的故事KIKI STORY及圖（申請號 087025236，高安貿易有限公司，第 35 類）。

第 9、41、42 類裡拼法最接近的幾筆如下 [S2]。推論：它們和 Kikitori 只共用 KIKI、TORI 或 KI…TO 這類片段，整體的字形與讀音不同，近似程度低。

| 商標 | 號碼 | 權利人 | 類別與指定商品（摘錄） | 狀態 |
|---|---|---|---|---|
| Kiiroitori & Device | 註冊 01954500（申請 107029666） | 森克斯股份有限公司（SAN-X CO., LTD.，日本） | 第 9 類：行動電話護套、耳機、滑鼠、手機應用程式等 | 註冊，期限 2028-11-30 |
| KIKITRADE | 註冊 02213932（申請 110075082） | KKTD GROUP LIMITED（英屬維爾京群島） | 第 9 類：電腦軟體、可下載之應用程式等；第 36 類：虛擬貨幣金融交易等 | 註冊，期限 2032-03-31 |
| KiKiper | 註冊 01870978（第 9 類）、01872748（第 42 類） | 易易資設有限公司 | 第 9 類：電腦程式、手機應用程式、電腦軟體等；第 42 類：電腦軟體設計、提供線上不可下載電腦軟體之暫時使用服務等 | 註冊，期限 2027-09-30 |
| KiKico | 註冊 01919728（第 9 類）、01918338（第 42 類） | 易易資設有限公司 | 和 KiKiper 相同 | 註冊，期限 2028-06-15、2028-05-31 |
| KiKAiTO及設計字 | 申請 115041321 | 彪騰虎興業有限公司 | 第 9 類：蓄電池、行動電源、電池充電器等 | 申請中，申請日 2026-06-15 |
| KOTORI (ロゴ) | 註冊 01434255 | 豐達電機股份有限公司（FOSTER ELECTRIC CO., LTD.，日本） | 第 9 類：頭戴式耳機、耳機等 | 註冊，期限 2030-09-30 |
| KIKIKOKO及圖 | 註冊 01968746 | 太平洋旅行社股份有限公司 | 第 41 類：透過電腦網路提供教育及娛樂之資訊、舉辦各種講座等 | 註冊，期限 2029-01-31 |

狀態欄的依據：API 的 `item_name` 寫「註冊案」或「申請案」，`deadline` 是專用期限，`cancel_text` 是空的。已消滅的案子，`cancel_text` 會寫「到期消滅」，例如「積奇Ｋ．Ｉ．Ｋ．Ｉ．Ｔ．」（註冊 00474353）[S2]。

### 1.2 日本 JPO（J-PlatPat）

- 沒能查。首頁 `https://www.j-platpat.inpit.go.jp/` 與商標檢索頁 `/t0100` 都回 302，轉到 `/reject_sorry.html` [S3]。02:22 與 02:34（UTC）各試一次，結果相同。
- 那一頁寫：「申し訳ありません。本システムは、現在メンテナンス作業によりサービスを停止しております。」[S3]
- 推論：頁面的檔名是 reject，也可能是擋掉這個網路來源，而不是真的在維護。從回應分不出來。
- 所以這次沒有做「キキトリ」的称呼檢索，第 9、41、42 類都沒查。這是本研究最大的缺口（§3、§4）。

### 1.3 美國 USPTO

- 查法：Trademark Search [S4]。它的設定檔 `configuration.json` 指向檢索 API `https://tmsearch.uspto.gov/prod-stage-v1-0-0/tmsearch`，前端送的是 Elasticsearch 查詢 [S5]。我用前端用的欄位直接查。
- 索引是新的：依申請日排序，最新一筆的申請日是 2026-10-26 [S5]。

| 查詢 | 欄位 | 筆數 |
|---|---|---|
| `kikitori` | 商標文字（wordmark）與偽文字（wordmarkPseudoText） | 0 |
| `kiki*tori`、`kikitor*`、`kiki AND tori`、`kiki* AND tori*` | 同上 | 0 |
| `kikitory`、`kikitoli`、`kikidori`、`kikitri` | 同上 | 0 |
| `kikitori`、`kiki-tori` | 前端預設的六個欄位：指定商品、商標描述、權利人、譯文、商標文字、偽文字 | 0 |
| `kikitori OR "kiki tori" OR "kiki-tori"` | 譯文（translation）、商標描述、指定商品 | 0 |
| `*kitori*` | 商標文字 | 45 |

- `*kitori*` 的 45 筆全是 YAKITORI 系列，以及 NOKITORI（第 30 類）、YUKITORII 這類。落在第 9、41、42 類的只有 5 筆，都是已失效的舊制第 42 類餐廳商標，例如 HOUSE OF YAKITORI [S5]。
- 前端的預設檢索還會比對 `WMP5` 欄位。用 `kikitori` 查，回 958 筆，前 30 筆是 QICDRAW、QWIKTERM、QUICKDRAW 這類 [S5]。推論：WMP5 是讀音比對，這些字和 Kikitori 只是子音相近。
- 以 KIKI 開頭的商標很多（`kiki*` 共 566 筆），第 9 類就有 KIKI WORLD、KIKIHUB 等，但沒有接 TORI 的 [S5]。推論：它們和 Kikitori 共用的只是常見的 KIKI，近似程度低。

### 1.4 歐盟 EUIPO 與 TMview

- EUIPO 的 eSearch plus（`https://euipo.europa.eu/eSearch/`）兩次連線都沒有回應（`Empty reply from server`）[S6]。
- EUIPO 單筆商標的資料端點（例如 `/copla/trademark/data/withOppoRelations/018000001`）回得出資料，但要先知道號碼，不能用名稱檢索 [S6]。
- TMview 的網頁殼載得到。前端的檢索 API 是 `POST https://www.tmdn.org/tmview/api/search/results`，這支與其他 API 都沒有回應 [S8]。
- 我只送一般請求，沒有用偽裝瀏覽器之類的方式繞過網站的機器人防護。

### 1.5 WIPO

- Global Brand Database（`https://branddb.wipo.int/`）回的是 ALTCHA 驗證頁，要瀏覽器先算完驗證才能進去 [S7]。我沒有繞過它。
- 另一個入口 Madrid Monitor 的檢索端點 `jsp/select.jsp` 回 `{"error": "REQUIRE_COMPRESSED_REQUEST"}`，要前端壓縮過、帶查詢識別碼的請求 [S9]。我也沒有繞過它。

## 2. 撞名

### 2.1 同名的轉錄與字幕軟體

| 名稱 | 平台 | 做什麼 | 發布者 | 上架或發布 | 來源 |
|---|---|---|---|---|---|
| Kikitori（`clovenski/kikitori`） | Windows 10/11 安裝檔 `Kikitori-Setup-0.3.0.exe` | 本機轉錄日文影片或音檔，再翻譯與摘要。輸出 SRT 字幕與 Markdown 摘要 | clovenski | v0.1.0 與 v0.3.0 都寫「15 Oct」，沒寫年份 | [S14] [S15] |
| 听译 Kikitori（`biubiu223/Kikitori`） | Windows（WinUI 3） | 本機 Whisper 辨識電腦正在播放的聲音，用 LLM 翻成中文，顯示懸浮字幕。GPL-3.0 | biubiu223 | v1.0.0 寫「11 Oct 14:58」，沒寫年份 | [S16] [S17] |
| キキトリ 文字起こし・議事録を端末内で | iPhone、iPad（iOS 26.0 以上） | 端末內轉錄錄音與音檔，輸出 .txt 與 .srt。免費 | reiji onishi | 2026-10-04 | [S22] [S23] [S24] [S25] |
| Kikitori 文字起こし | iOS 26.0 以上 | 端末內轉錄與 AI 摘要。Pro 版可輸出 .srt | kazunari aoki | 2026-07-15 | [S23] [S26] |
| Kikitori 議事録 | iOS 26.0 以上（只在日本商店） | 端末內轉錄會議錄音。版本 6.1，2026-10-27 更新 | Yorihide Nitta | 2026-10-07 | [S23] [S27] |
| Kikitori | macOS | 本機 Whisper 語音輸入，99 種語言 | Tobias Wissmueller（Ramus Labs，德國） | 2026-08-27 | [S29] [S30] |
| `OkinawaJapan/kikitori` | 瀏覽器介面，macOS 與 Linux | 日文沉浸學習。沒有字幕時用 whisper.cpp 轉錄，可存 .srt。MIT | OkinawaJapan | 頁面沒寫 | [S18] |
| `davegallant/kikitori` | 頁面沒寫 | 「transcribe and translate Japanese podcasts」 | davegallant | 頁面沒寫 | [S19] |
| `yusaitajiri/kikitori` | Windows | 網址轉到 `yusaitajiri/chidori`：「Windows用のリアルタイム文字起こしアプリ（ローカルWhisper）」 | yusaitajiri | 頁面沒寫 | [S20] |

各筆的細節：

- **clovenski/kikitori**：發布頁寫「Download **`Kikitori-Setup-0.3.0.exe`** below (Windows 10 or 11, 64-bit).」，模型是「Whisper for speech, Hy-MT2 for translation, Qwen3 for names and summaries.」[S14]。輸出是「**Subtitle files** (`.srt`, Japanese, English and bilingual) and a Markdown summary written to `Documents\Kikitori`.」[S14]。硬體表有一列「NVIDIA GPU with 8 GB or more (driver 551+) | about 14 GB」[S14]。repo 描述是「Understand Japanese videos, on your own computer: local transcription, translation and summaries.」[S15]
- **biubiu223/Kikitori**：About 寫「Real-time speech translation subtitles for Windows (Whisper + LLM, WinUI 3).」[S16]。v1.0.0 的附件是 `Kikitori-1.0.0-setup.exe` 與 `Kikitori-1.0.0-win-x64.zip` [S17]。這個 zip 的檔名和 #26 定的 `Kikitori-v0.1.0-win64.zip` 只差在版本號與 `x64`。
- **キキトリ（reiji onishi）**：同一個 app 在各商店用不同名稱。美國商店叫「Kikitori: AI Transcribe Notes」，台灣商店叫「Kikitori 逐字稿・語音轉文字」，台灣版的說明是繁體中文：「把錄音變成逐字稿的App，語音轉文字全部在手機裡完成」[S23]。開發者的網站寫「キキトリは、会議・取材・講義の録音や手持ちの音声ファイルを、すべて端末の中だけで文字起こしする iOS アプリです。」[S25]
- **Kikitori 文字起こし（kazunari aoki）**：說明寫「録音・文字起こし・要約は、すべてお使いの端末の中で完結します。」，以及「Markdown・字幕(.srt)・音声ファイルの書き出しにも対応（Pro）」[S23]。
- **Kikitori 議事録（Yorihide Nitta）**：說明寫「Kikitori は、会議や打ち合わせの録音を iPhone の中だけで文字に起こすアプリです。」[S23]。美國商店的頁面回 404，只在日本商店 [S27]。
- **Kikitori（macOS）**：說明寫「Kikitori (聞き取り) is Japanese for catching what you hear: listening comprehension.」與「Transcription runs 100% on-device, powered by Whisper」[S29]。開發者頁面寫「Private voice dictation for the Mac.」[S30]
- **yusaitajiri/kikitori**：開啟後轉到 `yusaitajiri/chidori`，README 要使用者下載 `Chidori_x.y.z_x64-setup.exe` [S20]。推論：這個 repo 原本叫 kikitori，後來改名。頁面沒寫改名的原因。
- GitHub 發布頁的「15 Oct」「11 Oct」沒有年份 [S14] [S17]。推論：GitHub 對今年的日期不顯示年份，所以是 2026 年。

### 2.2 聽力學習與其他同名

- **ききとり帳（AKIHIRO WADA）**：iOS 教育類，2026-10-06 上架 [S23] [S28]。日本商店的名稱是「ききとり帳 - 英語リスニングと単語帳」，美國商店叫「Kikitori: Learn Korean by Ear」[S23]。功能是把麥克風收到的英文或韓文即時轉成字幕並翻譯，存成學習紀錄 [S23]。
- **kikitori Co., Ltd.**：App Store 上的賣家名稱。它上架的是農業流通平台 nimaru 的生產者 app（2024-05-27 上架）[S23]。推論：日本有一家公司用 kikitori 當商號。
- **「聞き取り」是聽力教材的常用詞**：在 App Store 用「聞き取り」「ききとり」搜尋，會出現大量日文聽力練習 app，例如「毎日聞き取り初級」「英語聞き取り王国」「SoundSteps 聞き取り練習」[S22]。
- **GitHub 組織 `kikitori`**：存在，頁面寫「This organization has no public repositories.」[S21]。
- **npm scope `@kikitori`**：只有 `@kikitori/create-database-url-from-json`，描述是「Create DATABASE_URL from DATABASE_JSON」。2022-03-10 建立，維護者 chelproc，MIT [S13]。和語音無關。

### 2.3 沒有撞名的地方

- **PyPI**：`https://pypi.org/pypi/kikitori/json` 回 404，`kiki-tori` 與 `kikitori-ai` 也是 404 [S10]。PyPI 的搜尋頁要先過 JavaScript 驗證，所以改讀 simple index 的 JSON 版（924,983 個專案）。把名稱裡的 `-`、`_`、`.` 去掉後比對，沒有含 `kikitor` 的專案 [S11]。
- **npm**：`https://registry.npmjs.org/kikitori` 與 `kiki-tori` 都回 `{"error":"Not found"}` [S12]。搜尋 API 只回上面那個 scope 套件 [S13]。
- **Microsoft Store**：用前端的搜尋 API，在 US、JP、TW 三個市集各查 `kikitori`、`kiki tori`、キキトリ、聞き取り、ききとり。每次回 18 到 20 筆，沒有名稱或發行者含這些字的 app [S31]。
- **Google Play**：搜尋頁在 en-US 與 ja-JP 各查同樣 5 個詞，結果裡沒有同名 app。頁面上出現的 kikitori 都是檢索詞本身 [S32]。

### 2.4 網域

| 網域 | 註冊 | 用途 | 來源 |
|---|---|---|---|
| `kikitori.com` | 2000-04-10 註冊，2027-04-10 到期。註冊商 Register.com - Network Solutions, LLC。狀態 client transfer prohibited | HTTPS 連線在收到回應前就被中斷，看不到網站 | [S34] [S35] |
| `kikitori.app` | 2025-09-04 註冊，2027-09-04 到期。註冊商 CloudFlare, Inc. | 首頁標題是「Welcome to Cloudflare」，寫「Hosted and protected by Cloudflare」，沒有產品內容 | [S36] [S37] |
| `kikitori.dev` | Google Registry 的 RDAP 回 404，描述是「kikitori.dev not found」 | 無 | [S38] |
| `kikitori.io` | IANA 的 RDAP 清單沒有 .io，.io 只有 WHOIS（whois.nic.io）。.io 的權威伺服器對 NS、A、SOA 查詢都回 NXDOMAIN | 無 | [S39] [S40] [S41] |

推論：`.dev` 與 `.io` 目前沒人註冊。`.io` 的判斷只靠 DNS，沒有 WHOIS 佐證（§4）。

## 3. 對 #26 的意思

**衝突程度：高。** 高的原因是撞名，不是已經查到的商標。

1. **同平台、同類的軟體已經用了這個名字。** `clovenski/kikitori` 是 Windows 的本機轉錄工具，處理日文影音，輸出 SRT 字幕，支援 NVIDIA GPU [S14]。`biubiu223/Kikitori` 也是 Windows 的本機 Whisper 字幕工具，發布檔名是 `Kikitori-1.0.0-win-x64.zip` [S17]。這兩個和本產品的平台、用途、發布形式幾乎一樣。
2. **App Store 至少有 3 款叫 Kikitori 的端末內轉錄 app**，主打的也是「音檔不出裝置」[S23]。其中一款在台灣商店叫「Kikitori 逐字稿・語音轉文字」，對象正是台灣要做逐字稿的人 [S23]。Mac 上也有一款 Kikitori 本機 Whisper 語音輸入 [S29]。這些都在 2026-07 到 10 月上架。
3. **#26 選自創詞的理由不成立。** #26 Q1 選「自創詞或少見的詞」，理由是好搜尋、好查商標。推論：現在搜尋 Kikitori 會先看到上面這些產品，使用者容易認錯。
4. **商標的風險查不完整。** 台灣與美國沒有查到 [S2] [S5]。日本是最重要的市場，這次查不到 [S3]。日本已有用 kikitori 當商號的公司 [S23]，也有多款叫「キキトリ」或「Kikitori」的日文轉錄 app [S23]。推論：日本已有登記或申請的可能不能排除。台灣與日本都採先申請先註冊，其他人日後去申請也有可能。
5. **網域**：`.com` 從 2000 年就有人註冊，`.app` 在 2025 年被註冊 [S34] [S36]。`.dev` 與 `.io` 看起來還空著（推論）。

建議（推論，由維護者決定）：照 #236 寫的「有衝突時，回 #26 換候選」，回 #26 換名稱。換候選時，先看 App Store 與 GitHub 有沒有同類產品，再查商標；這次用到的查法都寫在 §1 與 §2，可以直接照做。

## 4. 沒能查證的事

- **日本 J-PlatPat**：所有頁面都被轉到 `reject_sorry.html`，頁面寫維護中 [S3]。分不出是真的在維護，還是擋掉這個網路來源。所以「キキトリ」的称呼檢索與第 9、41、42 類都沒查。這是結論裡最大的不確定。
- **EUIPO eSearch plus 與 TMview**：連線沒有回應 [S6] [S8]。只送一般請求，沒有繞過防護。
- **WIPO Global Brand Database 與 Madrid Monitor**：一個是 ALTCHA 驗證頁 [S7]，一個要壓縮過的請求 [S9]。都沒有繞過。
- **GitHub 的清單可能不完整**：依規則沒有用 GitHub 的 API 或搜尋，只能打開一般搜尋引擎找到的頁面。這個 session 直接連 github.com 上其他 repo 會回 403，所以 GitHub 頁面是用 WebFetch 讀的。
- **`germineye/kikitori`**：搜尋引擎帶出這個 repo，標題寫它是日文聽力練習工具。頁面打不開（WebFetch 回 client_error），沒有確認，所以沒列進 §2。
- **GitHub 發布日期的年份**：頁面只寫「15 Oct」「11 Oct」[S14] [S17]。
- **`kikitori.com` 的用途**：HTTPS 連線被中斷 [S35]。WebFetch 回 robots_disallowed。RDAP 沒有註冊人資料 [S34]。
- **`kikitori.io` 的 WHOIS**：.io 沒有 RDAP [S39] [S40]。WHOIS 走 port 43，這裡連不到。nic.io 的網頁版 WHOIS 要 JavaScript 才會顯示結果。只能靠 DNS 的 NXDOMAIN [S41]。
- **Mac 版 Kikitori 的舊頁面**：搜尋引擎帶出 `wissmueller.vercel.app/en/kikitori.html`，這個網址回 404（DEPLOYMENT_NOT_FOUND）。改用 App Store 的賣家網址 [S30] 確認。
- **商店搜尋只看第一頁**：Microsoft Store 每次 18 到 20 筆 [S31]，Google Play 每次最多約 50 筆 [S32]。推論：同名 app 會排在前面，但沒有逐頁確認。
- **沒有申請商標的使用**：商標資料庫只看得到申請與註冊。上面這些產品有沒有在任何地方申請商標，這次都查不到。

## 5. 順帶發現（不屬本題）

- #26 的另一個候選 Kakitori 也撞名：用 `kikitori` 在 Google Play 搜尋，第一筆是「Kakitori: Learn Japanese」（`com.kakitori.learn`）[S32] [S33]。只是順帶看到，沒有查商標。
- 本研究的輸出和 `docs/adr/` 的決策沒有衝突。名稱只影響發布物的檔名，不改變 ADR 0004（只發布免安裝版）與 ADR 0006（Apache-2.0）。

## 來源

查詢日期都是 2026-10-28。API 類的網址列出一個代表性的查詢，同一支 API 的其他查詢寫在內文。

| 代號 | 頁面 | 網址 | 查詢日期 |
|---|---|---|---|
| S1 | TIPO 商標檢索系統 | <https://cloud.tipo.gov.tw/S282/S282WV1/> | 2026-10-28 |
| S2 | TIPO 商標檢索系統的 API（`search/wordSearch`、`result/list`、`common/dataUpdateDate`） | <https://cloud.tipo.gov.tw/S282/S282BV1/api/search/wordSearch> | 2026-10-28 |
| S3 | J-PlatPat（轉到 `reject_sorry.html`） | <https://www.j-platpat.inpit.go.jp/reject_sorry.html> | 2026-10-28 |
| S4 | USPTO Trademark Search | <https://tmsearch.uspto.gov/> | 2026-10-28 |
| S5 | USPTO Trademark Search 的檢索 API（設定檔：<https://tmsearch.uspto.gov/configuration.json>） | <https://tmsearch.uspto.gov/prod-stage-v1-0-0/tmsearch> | 2026-10-28 |
| S6 | EUIPO eSearch plus | <https://euipo.europa.eu/eSearch/> | 2026-10-28 |
| S7 | WIPO Global Brand Database | <https://branddb.wipo.int/> | 2026-10-28 |
| S8 | TMview | <https://www.tmdn.org/tmview/> | 2026-10-28 |
| S9 | WIPO Madrid Monitor | <https://www3.wipo.int/madrid/monitor/en/> | 2026-10-28 |
| S10 | PyPI JSON API：kikitori | <https://pypi.org/pypi/kikitori/json> | 2026-10-28 |
| S11 | PyPI simple index | <https://pypi.org/simple/> | 2026-10-28 |
| S12 | npm registry：kikitori | <https://registry.npmjs.org/kikitori> | 2026-10-28 |
| S13 | npm search API | <https://registry.npmjs.org/-/v1/search?text=kikitori> | 2026-10-28 |
| S14 | clovenski/kikitori：Release Kikitori 0.3.0 | <https://github.com/clovenski/kikitori/releases/tag/v0.3.0> | 2026-10-28 |
| S15 | clovenski/kikitori：Release Kikitori 0.1.0 | <https://github.com/clovenski/kikitori/releases/tag/v0.1.0> | 2026-10-28 |
| S16 | biubiu223/Kikitori | <https://github.com/biubiu223/Kikitori> | 2026-10-28 |
| S17 | biubiu223/Kikitori：Release 听译 Kikitori v1.0.0 | <https://github.com/biubiu223/Kikitori/releases/tag/v1.0.0> | 2026-10-28 |
| S18 | OkinawaJapan/kikitori | <https://github.com/OkinawaJapan/kikitori> | 2026-10-28 |
| S19 | davegallant/kikitori | <https://github.com/davegallant/kikitori> | 2026-10-28 |
| S20 | yusaitajiri/kikitori（轉到 yusaitajiri/chidori） | <https://github.com/yusaitajiri/kikitori> | 2026-10-28 |
| S21 | GitHub 組織 kikitori | <https://github.com/kikitori> | 2026-10-28 |
| S22 | iTunes Search API（iOS；也查 us、tw 與其他檢索詞） | <https://itunes.apple.com/search?term=kikitori&entity=software&country=jp> | 2026-10-28 |
| S23 | iTunes Lookup API（也查 us、tw） | <https://itunes.apple.com/lookup?id=6815954612,6787387708,6811917548,6818799396,6499123272&country=jp> | 2026-10-28 |
| S24 | App Store：キキトリ 文字起こし・議事録を端末内で | <https://apps.apple.com/jp/app/id6815954612> | 2026-10-28 |
| S25 | bbintroduction：キキトリ | <https://bbintroduction.com/apps/kikitori/> | 2026-10-28 |
| S26 | App Store：Kikitori 文字起こし | <https://apps.apple.com/jp/app/id6787387708> | 2026-10-28 |
| S27 | App Store：Kikitori 議事録 | <https://apps.apple.com/jp/app/id6811917548> | 2026-10-28 |
| S28 | App Store：ききとり帳 - 英語リスニングと単語帳 | <https://apps.apple.com/jp/app/id6818799396> | 2026-10-28 |
| S29 | iTunes Lookup API：Kikitori（macOS；由 `entity=macSoftware` 搜尋找到） | <https://itunes.apple.com/lookup?id=6802801772&country=jp> | 2026-10-28 |
| S30 | Ramus Labs：Kikitori | <https://ramuslabs.com/kikitori/> | 2026-10-28 |
| S31 | Microsoft Store 搜尋 API（也查 JP、TW 與其他檢索詞） | <https://apps.microsoft.com/api/products/search?query=kikitori&mediaType=all&age=all&price=all&category=all&subscription=all&gl=US&hl=en-US> | 2026-10-28 |
| S32 | Google Play 搜尋（也查 ja-JP 與其他檢索詞） | <https://play.google.com/store/search?q=kikitori&c=apps&hl=en&gl=US> | 2026-10-28 |
| S33 | Google Play：Kakitori: Learn Japanese | <https://play.google.com/store/apps/details?id=com.kakitori.learn> | 2026-10-28 |
| S34 | RDAP：kikitori.com（Verisign） | <https://rdap.verisign.com/com/v1/domain/kikitori.com> | 2026-10-28 |
| S35 | kikitori.com | <https://kikitori.com/> | 2026-10-28 |
| S36 | RDAP：kikitori.app（Google Registry） | <https://pubapi.registry.google/rdap/domain/kikitori.app> | 2026-10-28 |
| S37 | kikitori.app | <https://kikitori.app/> | 2026-10-28 |
| S38 | RDAP：kikitori.dev（Google Registry） | <https://pubapi.registry.google/rdap/domain/kikitori.dev> | 2026-10-28 |
| S39 | IANA RDAP bootstrap（DNS） | <https://data.iana.org/rdap/dns.json> | 2026-10-28 |
| S40 | IANA Root Zone Database：.io | <https://www.iana.org/domains/root/db/io.html> | 2026-10-28 |
| S41 | DNS 查詢：kikitori.io（Google Public DNS，回應來自 .io 的權威伺服器） | <https://dns.google/resolve?name=kikitori.io&type=NS> | 2026-10-28 |

[S1]: https://cloud.tipo.gov.tw/S282/S282WV1/
[S2]: https://cloud.tipo.gov.tw/S282/S282BV1/api/search/wordSearch
[S3]: https://www.j-platpat.inpit.go.jp/reject_sorry.html
[S4]: https://tmsearch.uspto.gov/
[S5]: https://tmsearch.uspto.gov/prod-stage-v1-0-0/tmsearch
[S6]: https://euipo.europa.eu/eSearch/
[S7]: https://branddb.wipo.int/
[S8]: https://www.tmdn.org/tmview/
[S9]: https://www3.wipo.int/madrid/monitor/en/
[S10]: https://pypi.org/pypi/kikitori/json
[S11]: https://pypi.org/simple/
[S12]: https://registry.npmjs.org/kikitori
[S13]: https://registry.npmjs.org/-/v1/search?text=kikitori
[S14]: https://github.com/clovenski/kikitori/releases/tag/v0.3.0
[S15]: https://github.com/clovenski/kikitori/releases/tag/v0.1.0
[S16]: https://github.com/biubiu223/Kikitori
[S17]: https://github.com/biubiu223/Kikitori/releases/tag/v1.0.0
[S18]: https://github.com/OkinawaJapan/kikitori
[S19]: https://github.com/davegallant/kikitori
[S20]: https://github.com/yusaitajiri/kikitori
[S21]: https://github.com/kikitori
[S22]: https://itunes.apple.com/search?term=kikitori&entity=software&country=jp
[S23]: https://itunes.apple.com/lookup?id=6815954612,6787387708,6811917548,6818799396,6499123272&country=jp
[S24]: https://apps.apple.com/jp/app/id6815954612
[S25]: https://bbintroduction.com/apps/kikitori/
[S26]: https://apps.apple.com/jp/app/id6787387708
[S27]: https://apps.apple.com/jp/app/id6811917548
[S28]: https://apps.apple.com/jp/app/id6818799396
[S29]: https://itunes.apple.com/lookup?id=6802801772&country=jp
[S30]: https://ramuslabs.com/kikitori/
[S31]: https://apps.microsoft.com/api/products/search?query=kikitori&mediaType=all&age=all&price=all&category=all&subscription=all&gl=US&hl=en-US
[S32]: https://play.google.com/store/search?q=kikitori&c=apps&hl=en&gl=US
[S33]: https://play.google.com/store/apps/details?id=com.kakitori.learn
[S34]: https://rdap.verisign.com/com/v1/domain/kikitori.com
[S35]: https://kikitori.com/
[S36]: https://pubapi.registry.google/rdap/domain/kikitori.app
[S37]: https://kikitori.app/
[S38]: https://pubapi.registry.google/rdap/domain/kikitori.dev
[S39]: https://data.iana.org/rdap/dns.json
[S40]: https://www.iana.org/domains/root/db/io.html
[S41]: https://dns.google/resolve?name=kikitori.io&type=NS
