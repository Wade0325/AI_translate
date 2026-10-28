# 產品名稱 Mimiji 的商標與撞名

研究票 #237，查的是 #26 的前置問題：暫定的產品名稱 **Mimiji**（自創，漢字寫作「耳字」：用耳朵聽、變成字）能不能用。產品是給 Windows 個人使用者的免費開源（Apache-2.0）轉錄工具，把日文與中文音檔轉成字幕與逐字稿，在本機 GPU 上執行，發布成 `Mimiji.exe`、`Mimiji-v0.1.0-win64.zip`。前一個候選 Kikitori 撞名程度高，見 #236。

- 要回答的問題：
  1. **撞名**（先查）：App Store（台灣、日本、美國）、Mac App Store、Microsoft Store、Google Play、GitHub、PyPI、npm 上，有沒有同名或很像的語音、轉錄、字幕或聽力相關產品。`mimiji.com`、`.app`、`.dev`、`.io` 有沒有被註冊、拿來做什麼。「Mimi」開頭的產品只記和語音、聽力、轉錄、字幕相關，而且名稱整體近似的。
  2. **商標**：台灣 TIPO、日本 JPO（J-PlatPat）、美國 USPTO、歐盟 EUIPO、WIPO Global Brand Database（與 TMview）裡，有沒有 `Mimiji` 或近似名稱的登記或申請。重點是第 9 類（下載的軟體）與第 42 類（線上軟體服務），第 41 類一併記下。近似名稱包括 `MimiJi`、`Mimi Ji`、「耳字」、「ミミジ」、「みみじ」。
- 查詢日期：2026-10-28，所有來源都在這天讀取。
- 只引用第一手來源：商標局的資料庫或它前端用的 API、套件註冊處、應用商店、RDAP 與 DNS、網站本身。搜尋引擎只用來找線索。段落後面的 [Sn] 連到該頁，並對到文末〈來源〉表。
- 「沒查到」只代表在寫明的查法下沒有結果，不等於「沒有登記」。查不到的資料庫寫在 §4。
- 這是查詢整理，不是法律意見。標「推論」的地方是我從資料推出來的，資料沒有逐字寫。

## 短答

| 資料庫或平台 | 查到什麼 | 來源 |
|---|---|---|
| App Store（iOS） | 沒有名稱或賣家含 Mimiji、ミミジ、みみじ、耳字的 app。用途和名稱最接近的是日本商店的「Mimifude 耳筆」：iPhone 端末內的轉錄與翻譯 app，2026-07-23 上架。另有會議轉錄 app「Mimi: AI Meeting Notes」（§1.1、§1.7）。 | [S15] [S16] |
| Mac App Store | 沒有。 | [S17] |
| Microsoft Store | 沒有。US、JP、TW 市集的搜尋結果都沒有同名 app。 | [S19] |
| Google Play | 沒有 Mimiji。有同一款「Mimi: AI Meeting Notes」（開發者 Fidelio Software）。 | [S20] [S21] |
| GitHub | 有一個使用者帳號 `mimiji`，公開的 repo 只有 lab5、lab6、lab8、lab9。網路搜尋沒找到名為 mimiji 的 repo（§1.5）。 | [S14] |
| PyPI | 沒有名稱含 mimiji 的專案。 | [S10] [S11] |
| npm | `mimiji` 回 404，搜尋 API 回 0 筆。 | [S12] [S13] |
| `mimiji.com` | 已註冊（2006-08-25，Alibaba Cloud）。沒有 A 記錄，沒有網站。 | [S22] [S23] |
| `mimiji.app` | 已註冊（2026-04-23，Squarespace）。網站是「Coming Soon」頁，只寫「mimiji.app」與「We're under construction.」。 | [S24] [S25] |
| `mimiji.dev` | Registry 的 RDAP 回「mimiji.dev not found」。推論：沒人註冊。 | [S26] |
| `mimiji.io` | .io 沒有 RDAP。.io 的權威 DNS 回 NXDOMAIN。推論：沒人註冊，但沒查到 WHOIS。 | [S27] [S28] |
| 台灣 TIPO | 沒有 `MIMIJI`，也沒有含「耳字」「ミミジ」「みみじ」的商標。拼法最接近的是 mimijidi（第 16、40 類）。第 9 類有 audio-technica MIMIO 的申請案（已核准），指定商品含聲音編輯軟體（§2.1）。 | [S1] [S2] |
| 日本 J-PlatPat | 沒能查。網址都被轉到 `reject_sorry.html`，這一頁回 403，內容有 `waf_block_id`。 | [S3] |
| 美國 USPTO | 沒有 `MIMIJI`、`MIMI JI` 或近似拼法，譯文欄位也沒有。最接近的是 MIMIJIEDIE（第 14 類，珠寶）。 | [S4] [S5] |
| 歐盟 EUIPO | 沒能查。eSearch plus 的連線沒有回應。 | [S6] |
| WIPO Global Brand Database | 沒能查。首頁是 ALTCHA 驗證頁。 | [S7] |
| TMview | 沒能查。網頁殼載得到，檢索 API 沒有回應。 | [S8] |

撞名方面，沒有同名的產品。用途相同、名稱結構相似的有一款日本的 iPhone app「Mimifude 耳筆」。商標方面，台灣與美國沒有查到同名或近似到需要擔心的登記，但日本、歐盟與 WIPO 這次都查不到。結論見 §3。

## 1. 撞名

### 1.1 App Store（iOS）

- 查法：iTunes Search API [S15]。台灣、日本、美國三個商店，各用 `mimiji`、`mimi ji`、耳字、ミミジ、みみじ 查，`limit=200`。API 有幾次回空內容或 403（含 Mac 的查詢），等 3 到 8 秒重試後都拿到結果。
- 每次回 22 到 180 筆。搜尋是模糊比對，例如 `mimiji` 在台灣回 150 筆、日本 150 筆、美國 158 筆 [S15]。
- 我把所有結果的 app 名稱、賣家名稱與開發者名稱合起來比對，條件是含 `mimi ji`（中間可有空白、`-`、`_`、`.`）、`mimizi`、耳字、ミミジ、みみじ。沒有任何一筆符合 [S15]。
- 另外補查 `mimizi`、`mimi transcribe`、`mimi transcription`、`mimi subtitle`、`mimi 文字起こし`、`mimi 逐字稿`、`mimi 字幕`、`耳 文字起こし`、`みみ 文字起こし`、`mimifude`。結果裡也沒有 Mimiji [S15]。
- 結果裡名稱含 Mimi、ミミ、みみ 的 app，再用 iTunes Lookup API 讀說明 [S16]。和語音、聽力、轉錄相關的列在 §1.7。

### 1.2 Mac App Store

- 查法：同一支 API，`entity=macSoftware` [S17]。
- `mimiji` 在三個商店各回 4 到 5 筆，都是 emoji 或游標工具，例如「Emojify - Swap words to Emoji」「Genemoji Book」[S17]。
- `mimi ji`、耳字、ミミジ、みみじ、`mimizi`、`mimi transcribe`、`mimi dictation` 的結果裡也沒有 Mimiji [S17]。

### 1.3 Microsoft Store

- 查法：商店前端用的搜尋 API [S19]。US、JP、TW 三個市集，各查 `mimiji`、`mimi ji`、耳字、ミミジ、みみじ、`mimi transcribe`、`mimi`。每次回 20 筆。
- 沒有名稱或發行者含 Mimiji 的 app [S19]。
- 名稱含 Mimi 的只有貓咪遊戲「Mimi the Cat」系列，以及 MimiWork（QUALITATI）。MimiWork 的說明是「Your desktop AI coworker for documents, presentations, spreadsheets, PDFs and data analysis.」[S19]。兩者都和語音無關。

### 1.4 Google Play

- 查法：搜尋頁 [S20]。en-US、ja-JP、zh-TW 三種語言與地區，各查 `mimiji`、`mimi ji`、耳字、ミミジ、みみじ、`mimi transcribe`、`mimifude`。
- 結果裡沒有 Mimiji。`mimiji` 在美國帶出的是 Mohanji、mommi、Onmyoji 這類拼法相近的 app [S20]。`mimifude` 在三個地區都沒有結果 [S20]。
- 和語音相關、名稱含 Mimi 的有三款 [S20]：
  - 「Mimi: AI Meeting Notes」（`com.fidelioware.mimi`，Fidelio Software）。說明的開頭是「Mimi is the AI meeting recorder that does the work for you.」，和 iOS 版逐字相同。下載數 100+ [S21]。
  - 「Mimi Translator」（BSS Saham Indonesia）：文字、語音與拍照翻譯 [S30]。
  - 「Mimi - Translate & Phrase」（marimoko）：旅遊片語、翻譯與文字轉語音 [S31]。

### 1.5 GitHub、PyPI、npm

- **GitHub**：依規則沒有用 GitHub 的 API 或搜尋。網路搜尋「mimiji github」「site:github.com mimiji」等，結果只有 mimicji、migimigi、mihoji 這類名稱相近的帳號，沒有名為 mimiji 的 repo。
- 我直接開 `https://github.com/mimiji`，是一個使用者帳號（不是組織）。頁面列出 4 個公開 repo：lab5、lab6、lab8、lab9，沒有描述。個人簡介只有一個 emoji [S14]。推論：這是個人的課堂作業帳號，和語音無關。
- **PyPI**：`https://pypi.org/pypi/mimiji/json` 回 404，`mimi-ji`、`mimiji-ai`、`mimizi` 也是 404 [S10]。讀 simple index 的 JSON 版（924,995 個專案），把名稱的 `-`、`_`、`.` 去掉後比對，沒有含 `mimij` 的專案。含 `mimiz` 的只有 `mimizuku` [S11]。
- **npm**：`mimiji`、`mimi-ji`、`mimizi`、`@mimiji/core` 都回 `{"error":"Not found"}` [S12]。搜尋 API 用 `mimiji` 查，`total` 是 0 [S13]。

### 1.6 網域

| 網域 | 註冊 | 用途 | 來源 |
|---|---|---|---|
| `mimiji.com` | 2006-08-25 註冊，2027-08-25 到期，最後變更 2026-04-02。註冊商 Alibaba Cloud Computing (Beijing) Co., Ltd.。名稱伺服器是 DNS21、DNS22.HICHINA.COM | apex 沒有 A 記錄（DNS 回 NOERROR，沒有答案），`www.mimiji.com` 回 NXDOMAIN。所以沒有網站 | [S22] [S23] |
| `mimiji.app` | 2026-04-23 註冊，2027-04-23 到期。註冊商 Squarespace Domains II LLC.。狀態 client delete prohibited、client transfer prohibited | 頁面標題「Coming Soon」，內文是「mimiji.app」與「We're under construction. Please check back for an update soon.」，有 `noindex` | [S24] [S25] |
| `mimiji.dev` | Google Registry 的 RDAP 回 404，描述是「mimiji.dev not found」 | 無 | [S26] |
| `mimiji.io` | IANA 的 RDAP 清單沒有 .io [S27]。.io 的權威伺服器對 NS、A、SOA 查詢都回 NXDOMAIN | 無 | [S27] [S28] |

- 推論：`.dev` 與 `.io` 目前沒人註冊。`.io` 的判斷只靠 DNS，沒有 WHOIS 佐證（§4）。
- 推論：`mimiji.app` 是今年 4 月才註冊的，有人可能正準備用這個名字。頁面沒有寫用途，也看不到註冊人。

### 1.7 名稱含 Mimi 的語音、聽力、轉錄產品

下表只列和語音、聽力、轉錄或字幕相關的。近似程度都是推論，理由寫在表後。

| 名稱 | 平台 | 做什麼 | 發布者 | 上架 | 近似程度（推論） | 來源 |
|---|---|---|---|---|---|---|
| Mimifude 耳筆 - ローカルAI議事録・翻訳 | iPhone，iOS 26 以上。只在日本商店（美國、台灣的 Lookup 沒有回這筆） | 端末內即時轉錄日文與英文、翻譯、摘要。免費 | Takashi Seino | 2026-07-23 | 中 | [S16] [S18] |
| Mimi: AI Meeting Notes | iOS（台灣、日本、美國）、Android | 錄會議、逐字稿、說話者分離、AI 摘要 | Ata Tan Dagidir（iOS）、Fidelio Software（Google Play） | 2026-03-28（iOS） | 低 | [S16] [S21] |
| ミミガートーク | iOS 26 以上 | 離線語音辨識、翻譯與書き起こし | Evixar Inc. | 2025-09-15 | 低 | [S16] |
| みみサポ ~ 会話を文字にするアプリ | iOS | 把會話轉成文字放大顯示，輔助聽力 | yoshitomo ishii | 2026-10-06 | 低 | [S16] |
| ミミカルテ 診察を録音文字起こし！… | iOS | 錄下看診內容並轉成文字 | NUMOMENT K.K. | 2023-08-13 | 低 | [S16] |
| Mimi聴力検査（美國商店叫 Mimi Hearing Test） | iOS | 聽力檢查 | Mimi Hearing Technologies GmbH | 2014-11-03 | 低 | [S16] |
| mimi - 音声読み上げ・テキスト読み上げアプリ | iOS | 文字轉語音，方向和轉錄相反 | Bouzer LLC | 2025-06-15（日本商店） | 低 | [S16] |
| Mimi（Kyutai） | 模型 | 音訊編碼器：「Mimi codec is a state-of-the-art audio neural codec, developped by Kyutai」 | Kyutai | 頁面沒寫 | 低 | [S29] |

- **Mimifude 耳筆**：
  - 說明寫「耳筆（みみふで）は、聴いたそばから墨が走るように、会話を文字にしていく議事録アプリです。」[S16]
  - 也寫「文字起こし・翻訳・要約のすべてを iPhone の中だけで処理する「完全ローカル」設計。」[S16]
  - 網站寫「完全ローカルのAI議事録・翻訳アプリ。」，作者是 Takashi Seino [S18]。
  - 判斷理由（推論）：名稱的構成和 Mimiji 一樣，都是「耳（みみ）」加上一個和書寫有關的字：耳筆是筆，耳字是字。用途也幾乎一樣，主打本機轉錄、日文、音檔不出裝置。不同的是讀音（mi-mi-fu-de 與 mi-mi-ji）、字形與平台（iPhone 與 Windows）。所以整體近似程度是中，用途重疊高。日本使用者搜尋時，兩者可能並列出現。
- **Mimi: AI Meeting Notes**：說明寫「Mimi doesn't just transcribe, it understands.」與「Full word-for-word transcript with speaker separation」[S16]。判斷理由（推論）：Mimiji 的前四個字母就是 Mimi，用途也是轉錄。但 Mimi 是很常見的名稱。App Store 就有 Mimi Hearing Test、Mimi IME、Mimi: Learn Japanese 等多款 [S16]，Google Play 還有 Mimi Translator [S30]。Mimiji 多出的 ji 讓字尾與讀音不同。所以近似程度低。
- **ミミガートーク**：說明寫「ミミガートークは、音声認識と翻訳機能、文字の書き起こし機能が備わったアプリです。」[S16]。名稱是「ミミガー」加「トーク」，和 Mimiji 只共用ミミ。
- **みみサポ**、**ミミカルテ**：用途是轉文字，名稱只共用みみ、ミミ [S16]。
- **Mimi Hearing Test** 與 **Kyutai 的 Mimi**：名稱只有 Mimi，用途是聽力檢查與音訊編碼，不是轉錄 [S16] [S29]。

## 2. 商標

### 2.1 台灣 TIPO

- 查法：和 #236 相同。商標檢索系統 [S1] 的「文字」檢索，前端把檢索詞送到 `POST /api/search/wordSearch`（body 是 `{"tmarkDraft": "<檢索詞>"}`），再用 `POST /api/result/list`（body 是 `{"docs": [<docid>…]}`）取回每筆的詳細資料 [S2]。
- 系統的資料更新日期是 2026-10-27（`/api/common/dataUpdateDate`）[S2]。
- 這個檢索會回傳拼法或讀音相近的商標，不限類別。例如用 `mimiji` 查，前三筆是 audio-technica MIMIO 的三件申請案，第四筆是 mijia [S2]。

| 檢索詞 | 回傳筆數 | 有沒有含 MIMIJI 或日文、漢字寫法的商標 |
|---|---|---|
| `mimiji` | 898 | 只有 mimijidi |
| `MimiJi` | 898（和上一列相同） | 同上 |
| `Mimi Ji` | 898（和上一列相同） | 同上 |
| 耳字 | 0 | 沒有 |
| ミミジ | 129 | 沒有 |
| みみじ | 53 | 沒有 |
| `mimizi`（補查） | 745 | 只有 mimijidi |

- 七次共 3,621 筆，去掉重複是 1,073 筆。我篩選商標名稱與圖樣英文，條件是含 `mimi ji`（中間可有空白或符號）、`mimizi`、耳字、ミミジ、みみじ。只篩出 mimijidi 兩筆 [S2]：
  - mimijidi（申請號 108078818，註冊 02069946，龍璟興業股份有限公司）：第 40 類，印刷等。期限 2030-06-30。
  - mimijidi（申請號 108078819，註冊 02071723，同一權利人）：第 16 類，貼紙、卡片等。期限 2030-07-15。
- 耳字回 0 筆。補查「耳」回 5 筆，其中有「Q 爾」「爾及圖」；「耳文字」回 15 筆，多是「頭文字D」[S2]。推論：中文的檢索是比對讀音或整個詞，不是比對單字。這次沒有找到其他方式查含「耳字」的圖樣中文。
- 第 9、41、42 類裡，名稱含 MIMI 而且還有效的，最接近的幾筆如下 [S2]。推論：它們和 Mimiji 只共用 MIMI，後半不同，近似程度低。

| 商標 | 號碼 | 權利人 | 類別與指定商品（摘錄） | 狀態 |
|---|---|---|---|---|
| audio-technica MIMIO（另有「及圖（一）」「及圖（二）」兩件） | 申請 114077131、114077132、114077133 | 鐵三角有限公司（AUDIO-TECHNICA CORPORATION，日本） | 第 9 類：頭戴式耳機、麥克風、「紀錄、傳送、複製及編輯聲音及影像用電腦軟體」「可下載之電腦軟體」「音頻設備用應用軟體」等 | 申請案，申請日 2025-10-20，優先權 2025-04-22 日本。審查結果「核准」，2026-10-16 |
| mimini 及圖 | 註冊 01711578（申請 103056789） | 泛亞國際文化科技股份有限公司 | 第 9 類：電腦程式、電腦軟體、手機應用軟體、電子書等；另有第 16、28 類 | 註冊，期限 2035-05-31 |
| mimimamo | 註冊 01667733（申請 103017025） | 林雅之（HAYASHI, MASAYUKI） | 第 9 類：錄音筆、麥克風、耳機等 | 註冊，期限 2034-09-30 |
| mimiker及圖 | 註冊 01950914（申請 107034283） | 三穩國際股份有限公司 | 第 9 類：電腦軟體、行動電話應用程式、耳機等 | 註冊，期限 2028-11-15 |
| MimicFit | 註冊 01533047（申請 101005009） | 西凡圖私人有限公司（SIVANTOS PTE. LTD.） | 第 9 類：助聽器用電腦軟體；第 10 類：助聽器 | 註冊，期限 2032-08-15 |
| Mimicry 擬態科技及圖 | 註冊 02143664（第 9 類）、02145676（第 42 類） | 蘇敏傑 | 第 9 類：電腦軟體、可下載之應用軟體等；第 42 類：電腦軟體設計等 | 註冊，期限 2031-05-31 |
| 米米的家mimi family及圖 | 註冊 01338837（申請 097011220） | 和英出版社　周逸芬 | 第 9 類：電腦硬體、電子書等；第 41 類：書刊出版等 | 註冊，期限 2028-11-15 |
| Mimi 及圖 | 註冊 02527198（申請 114053422） | 曹敏玲 | 第 41 類：語文補習班、教育服務等 | 註冊，期限 2036-04-15 |

- 狀態欄的依據：API 的 `item_name` 寫「註冊案」或「申請案」，`deadline` 是專用期限，`cancel_text` 是空的。已消滅的案子，`cancel_text` 會寫「到期消滅」，例如大眾電信的 MiMi（第 42 類，註冊 00162710）與秘密基地數位科技的 MIMIGIGI 及設計圖（第 41 類，註冊 01626005）[S2]。
- 推論：audio-technica MIMIO 是第 9 類裡唯一指定商品含聲音軟體、而且還在進行中的近似案。MIMIO 和 MIMIJI 前四個字母相同、都是三個音節，但字尾不同，而且前面帶著 audio-technica 的公司名。用途是音響硬體與它的軟體，不是轉錄。所以近似程度低，但值得記下。
- 補查 `mimi`：系統回 `numFound` 2,132，但 API 只回前 1,000 筆的 docid [S2]。這 1,000 筆裡，第 9、42 類、名稱含 MIMI、而且沒有消滅的，除了上表，還有 mimi 與 mimi charme（眼鏡）、MiMiPPi（鼓室溫度計）、DreamMimity設計字（安全頭盔、電腦軟體等，期限 2026-06-30），以及兩件核駁案。推論：都只共用 MIMI，近似程度低。

### 2.2 日本 JPO（J-PlatPat）

- 沒能查。首頁 `https://www.j-platpat.inpit.go.jp/` 與商標檢索頁 `/t0100` 都回 302，轉到 `/reject_sorry.html` [S3]。03:08 與 03:09（UTC）各試一次，結果相同。
- 這次直接開 `reject_sorry.html`，回 403 Forbidden。頁面沒有 #236 看到的維護說明，只有「403 Forbidden」、請求的網址、這個網路來源的 IP、`waf_block_id` 與用戶端名稱 `curl/8.5.0` [S3]。
- 推論：J-PlatPat 的 WAF 擋下了這個網路來源或用戶端，不是在維護。我沒有換用戶端或偽裝瀏覽器去繞過它。
- 所以這次沒有做「ミミジ」的称呼檢索，第 9、41、42 類都沒查。這是本研究最大的缺口（§3、§4）。

### 2.3 美國 USPTO

- 查法：和 #236 相同。Trademark Search [S4] 的設定檔 `configuration.json` 指向檢索 API `https://tmsearch.uspto.gov/prod-stage-v1-0-0/tmsearch`，前端送的是 Elasticsearch 查詢 [S5]。我用前端用的欄位直接查。
- 索引是新的：依申請日排序，最新一筆的申請日是 2026-10-26 [S5]。

| 查詢 | 欄位 | 筆數 |
|---|---|---|
| `mimiji`、`"mimi ji"`、`mimi-ji`、`mimi*ji`、`mimi AND ji` | 商標文字（wordmark）與偽文字（wordmarkPseudoText） | 0 |
| `mimizi`、`mimigi`、`mimijee`、`mimijy` | 同上 | 0 |
| `mimiji` | 前端預設的六個欄位：指定商品、商標描述、權利人、譯文、商標文字、偽文字 | 0 |
| `mimiji OR "mimi ji"` | 譯文（translate）、商標描述、指定商品 | 0 |
| `mimiji*` | 商標文字與偽文字 | 1（MIMIJIEDIE） |
| `mimij*` | 商標文字 | 7 |
| `*imiji*` | 商標文字 | 9 |

- `mimij*` 的 7 筆是 MIMIJUMI（3 筆，第 10 類奶瓶）、MIMIJUDE（第 25 類，已撤銷）、MIMIJOY! DESIGNS 與 MJ MIMIJOY!（第 18 類）、MIMIJIEDIE（第 14 類，珠寶，SHENZHEN YIJIE TECHNOLOGY CO., LTD.，註冊 7911782）[S5]。都不在第 9、41、42 類。
- `*imiji*` 的 9 筆是 JIMIJIA、YIMIJIA、SIMIJIA、MIMIJIEDIE 這類，第 9 類只有 YIMIJIA（攝影機）與已放棄的 AIMIJIA [S5]。
- 前端的預設檢索還會比對 `WMP5` 欄位。用 `mimiji` 查回 89 筆，前幾筆是 MAOMAOJIA、MOMIJI、MAMAJOO、MIMOJI [S5]。推論：WMP5 是讀音比對，這些字和 Mimiji 只是子音相近。其中第 9、41 類有效的是 Apple 的 MEMOJI（第 9 類，emoji 軟體，註冊 7019160 與 6915052）與 MUMOJI（第 9、41 類，申請中）[S5]。推論：字形與讀音都和 Mimiji 有明顯差異，近似程度低。
- 名稱以 MIMI 開頭、指定商品和語音或聽力有關的有效商標如下 [S5]。推論：都只共用 MIMI，近似程度低。
  - MIMI（Mimi Hearing Technologies GmbH，註冊 5567566 與 5582647）：第 9 類含「computer software applications, downloadable, for measuring user data to create individualized hearing profiles」；5582647 另有第 42 類的軟體服務。
  - AUDIO-TECHNICA MIMIO 與 A AUDIO-TECHNICA MIMIO（Audio-Technica Corporation，申請號 79442916、79442917、79442918）：第 9 類，2025-10-15 申請，狀態「RESPONSE AFTER NON-FINAL ACTION - ENTERED」。
  - MIMIO（BOXLIGHT CORPORATION，註冊 2388693）：第 9 類「computer hardware and software for transcribing and storing handwritten text on a computer system」，是手寫轉文字，不是語音。
  - MIMICFIT（Sivantos Pte. Ltd.，註冊 4287358）：第 9 類「Software for operating hearing aids」。

### 2.4 歐盟 EUIPO 與 TMview

- EUIPO 的 eSearch plus（`https://euipo.europa.eu/eSearch/`）連線沒有回應（`Empty reply from server`）[S6]。
- EUIPO 單筆商標的資料端點（例如 `/copla/trademark/data/withOppoRelations/018000001`）回 200，但要先知道號碼，不能用名稱檢索 [S6]。
- TMview 的網頁殼載得到 [S8]。前端的檢索 API `POST https://www.tmdn.org/tmview/api/search/results` 沒有回應（`Empty reply from server`）[S8]。前端程式裡有 `captcha_verification_` 與 `captchaSession`，推論：檢索要先過驗證碼。
- 我只送一般請求，沒有用偽裝瀏覽器之類的方式繞過網站的機器人防護。

### 2.5 WIPO

- Global Brand Database（`https://branddb.wipo.int/`）回的是 ALTCHA 驗證頁，要瀏覽器先算完驗證才能進去 [S7]。我沒有繞過它。
- Madrid Monitor 的檢索端點 `jsp/select.jsp` 回 `{"error": "REQUIRE_COMPRESSED_REQUEST"}`，要前端壓縮過的請求 [S9]。我也沒有繞過它。

## 3. 對 #26 的意思

**衝突程度：需要注意。** 沒有查到同名的產品或商標。需要注意的原因是日本的商標沒查到，以及一款日本的轉錄 app 名稱結構相似。

1. **沒有同名的產品。** App Store（三個商店）、Mac App Store、Microsoft Store、Google Play 都沒有叫 Mimiji、ミミジ、みみじ或耳字的 app [S15] [S17] [S19] [S20]。PyPI 與 npm 沒有這個名字 [S10] [S11] [S12] [S13]。GitHub 只有一個同名的個人帳號，repo 是 lab5、lab6、lab8、lab9（推論：課堂作業）[S14]。這和 Kikitori（#236）差很多：Kikitori 有兩個同平台的 Windows 轉錄工具與三款同名轉錄 app。
2. **有一款用途相同、名稱結構相似的 app。** 日本商店的「Mimifude 耳筆」是 iPhone 的端末內轉錄 app，名稱也是「耳＋書寫的字」[S16] [S18]。推論：讀音與平台不同，不算撞名。但日本使用者可能覺得兩者有關，也可能以為是同一家的產品。
3. **Mimi 開頭的名稱很擁擠。** 已有會議轉錄 app「Mimi: AI Meeting Notes」[S16] [S21]，也有聽力的 MIMI 商標（Mimi Hearing Technologies）[S5]。推論：搜尋「Mimi」的人會先看到這些。但 Mimiji 多了 ji，自己搜尋「Mimiji」時目前不會被它們淹沒。
4. **商標的查證不完整。** 台灣與美國沒有 MIMIJI，最接近的第 9 類案是 audio-technica MIMIO，推論近似程度低 [S2] [S5]。日本是主要市場，這次 J-PlatPat 被 WAF 擋下 [S3]。推論：日本的第 9、42 類有沒有「ミミジ」或「耳字」，現在還不能排除。台灣與日本都採先申請先註冊，其他人日後去申請也有可能。
5. **網域**：`.com` 從 2006 年就有人註冊，但沒有網站 [S22] [S23]。`.app` 在 2026-04-23 被註冊，是 Squarespace 的「Coming Soon」頁 [S24] [S25]。推論：有人可能正準備用這個名字，現在看不出用途。`.dev` 與 `.io` 看起來還空著（推論）[S26] [S28]。

建議（推論，由維護者決定）：

- 用一般瀏覽器到 J-PlatPat 做一次「ミミジ」的称呼檢索與「耳字」的文字檢索，看第 9、42 類。如果沒有結果，推論衝突程度可以降到低。
- Mimifude 耳筆是否算太像，由維護者判斷。它只在日本商店、只有 iPhone 版，2026-07-23 才上架 [S16]。
- 如果定案，`mimiji.dev` 與 `mimiji.io` 看起來還能註冊（推論）。

## 4. 沒能查證的事

- **日本 J-PlatPat**：所有頁面都被轉到 `reject_sorry.html`，這一頁回 403 與 `waf_block_id` [S3]。所以「ミミジ」的称呼檢索與第 9、41、42 類都沒查。這是結論裡最大的不確定。
- **EUIPO eSearch plus 與 TMview**：連線沒有回應 [S6] [S8]。TMview 的前端需要驗證碼（推論）。只送一般請求，沒有繞過防護。
- **WIPO Global Brand Database 與 Madrid Monitor**：一個是 ALTCHA 驗證頁 [S7]，一個要壓縮過的請求 [S9]。都沒有繞過。
- **TIPO 的「耳字」**：檢索回 0 筆 [S2]。中文檢索看起來是比對讀音或整個詞（推論），所以含「耳字」的圖樣中文可能沒被找出來。`mimi` 的補查只拿到 2,132 筆中的前 1,000 筆 [S2]。
- **GitHub 的清單可能不完整**：依規則沒有用 GitHub 的 API 或搜尋，只能看一般搜尋引擎找到的頁面。`github.com/mimiji` 不是搜尋找到的，是我直接用網址開的。它的 repo 分頁（`?tab=repositories`）WebFetch 回 robots_disallowed，所以看不到 repo 的語言與更新日期 [S14]。
- **`mimiji.com` 與 `mimiji.app` 的註冊人**：RDAP 只有註冊商，沒有註冊人資料 [S22] [S24]。看不出是誰、要做什麼。
- **`mimiji.io` 的 WHOIS**：.io 沒有 RDAP [S27]。WHOIS 走 port 43，這裡連不到。只能靠 DNS 的 NXDOMAIN [S28]。
- **商店搜尋只看第一頁**：App Store 每次最多 200 筆 [S15]，Microsoft Store 每次 20 筆 [S19]，Google Play 每次最多約 50 筆 [S20]。推論：同名 app 會排在前面，但沒有逐頁確認。
- **Google Play 的上架日期**：詳細頁有日期，但頁面沒有標明是上架日還是更新日，所以 §1.4 沒寫 [S21]。
- **沒有申請商標的使用**：商標資料庫只看得到申請與註冊。Mimifude 耳筆、Mimi: AI Meeting Notes 這些產品有沒有在日本或其他地方申請商標，這次都查不到。

## 5. 順帶發現（不屬本題）

- J-PlatPat 這次的回應和 #236 不同：#236 的 `reject_sorry.html` 顯示維護中，這次直接開這一頁回 403 與 `waf_block_id` [S3]。推論：#236 遇到的「維護中」也可能是同一個 WAF 擋下。之後的研究票查日本商標時，要準備由人用瀏覽器查。
- 本研究的輸出和 `docs/adr/` 的決策沒有衝突。名稱只影響發布物的檔名，不改變 ADR 0004（只發布免安裝版）與 ADR 0006（Apache-2.0）。

## 來源

查詢日期都是 2026-10-28。API 類的網址列出一個代表性的查詢，同一支 API 的其他查詢寫在內文。

| 代號 | 頁面 | 網址 | 查詢日期 |
|---|---|---|---|
| S1 | TIPO 商標檢索系統 | <https://cloud.tipo.gov.tw/S282/S282WV1/> | 2026-10-28 |
| S2 | TIPO 商標檢索系統的 API（`search/wordSearch`、`result/list`、`common/dataUpdateDate`） | <https://cloud.tipo.gov.tw/S282/S282BV1/api/search/wordSearch> | 2026-10-28 |
| S3 | J-PlatPat（轉到 `reject_sorry.html`，該頁回 403） | <https://www.j-platpat.inpit.go.jp/reject_sorry.html> | 2026-10-28 |
| S4 | USPTO Trademark Search | <https://tmsearch.uspto.gov/> | 2026-10-28 |
| S5 | USPTO Trademark Search 的檢索 API（設定檔：<https://tmsearch.uspto.gov/configuration.json>） | <https://tmsearch.uspto.gov/prod-stage-v1-0-0/tmsearch> | 2026-10-28 |
| S6 | EUIPO eSearch plus | <https://euipo.europa.eu/eSearch/> | 2026-10-28 |
| S7 | WIPO Global Brand Database | <https://branddb.wipo.int/> | 2026-10-28 |
| S8 | TMview | <https://www.tmdn.org/tmview/> | 2026-10-28 |
| S9 | WIPO Madrid Monitor | <https://www3.wipo.int/madrid/monitor/en/> | 2026-10-28 |
| S10 | PyPI JSON API：mimiji | <https://pypi.org/pypi/mimiji/json> | 2026-10-28 |
| S11 | PyPI simple index | <https://pypi.org/simple/> | 2026-10-28 |
| S12 | npm registry：mimiji | <https://registry.npmjs.org/mimiji> | 2026-10-28 |
| S13 | npm search API | <https://registry.npmjs.org/-/v1/search?text=mimiji> | 2026-10-28 |
| S14 | GitHub 使用者 mimiji | <https://github.com/mimiji> | 2026-10-28 |
| S15 | iTunes Search API（iOS；也查 jp、us 與其他檢索詞） | <https://itunes.apple.com/search?term=mimiji&entity=software&country=tw> | 2026-10-28 |
| S16 | iTunes Lookup API（也查 us、tw） | <https://itunes.apple.com/lookup?id=6793203040,6758508178,6747191021,6759178173,6451367877,6752370485,1255363631,932496645,6789568667,6815067746,6815771741,6811910022,6763214146,6773571974&country=jp> | 2026-10-28 |
| S17 | iTunes Search API（macOS；也查 jp、tw 與其他檢索詞） | <https://itunes.apple.com/search?term=mimiji&entity=macSoftware&country=us> | 2026-10-28 |
| S18 | 耳筆（Mimifude）網站 | <https://seino-ta.github.io/mimifude-site/> | 2026-10-28 |
| S19 | Microsoft Store 搜尋 API（也查 JP、TW 與其他檢索詞） | <https://apps.microsoft.com/api/products/search?query=mimiji&mediaType=all&age=all&price=all&category=all&subscription=all&gl=US&hl=en-US> | 2026-10-28 |
| S20 | Google Play 搜尋（也查 ja-JP、zh-TW 與其他檢索詞） | <https://play.google.com/store/search?q=mimiji&c=apps&hl=en&gl=US> | 2026-10-28 |
| S21 | Google Play：Mimi: AI Meeting Notes | <https://play.google.com/store/apps/details?id=com.fidelioware.mimi> | 2026-10-28 |
| S22 | RDAP：mimiji.com（Verisign） | <https://rdap.verisign.com/com/v1/domain/mimiji.com> | 2026-10-28 |
| S23 | DNS 查詢：mimiji.com（Google Public DNS；也查 MX 與 www.mimiji.com） | <https://dns.google/resolve?name=mimiji.com&type=A> | 2026-10-28 |
| S24 | RDAP：mimiji.app（Google Registry） | <https://pubapi.registry.google/rdap/domain/mimiji.app> | 2026-10-28 |
| S25 | mimiji.app | <https://mimiji.app/> | 2026-10-28 |
| S26 | RDAP：mimiji.dev（Google Registry） | <https://pubapi.registry.google/rdap/domain/mimiji.dev> | 2026-10-28 |
| S27 | IANA RDAP bootstrap（DNS） | <https://data.iana.org/rdap/dns.json> | 2026-10-28 |
| S28 | DNS 查詢：mimiji.io（Google Public DNS，回應來自 .io 的權威伺服器；也查 A、SOA） | <https://dns.google/resolve?name=mimiji.io&type=NS> | 2026-10-28 |
| S29 | Hugging Face：kyutai/mimi | <https://huggingface.co/kyutai/mimi> | 2026-10-28 |
| S30 | Google Play：Mimi Translator | <https://play.google.com/store/apps/details?id=com.global.jing.trans> | 2026-10-28 |
| S31 | Google Play：Mimi - Translate & Phrase | <https://play.google.com/store/apps/details?id=com.marimoko.mimi> | 2026-10-28 |

[S1]: https://cloud.tipo.gov.tw/S282/S282WV1/
[S2]: https://cloud.tipo.gov.tw/S282/S282BV1/api/search/wordSearch
[S3]: https://www.j-platpat.inpit.go.jp/reject_sorry.html
[S4]: https://tmsearch.uspto.gov/
[S5]: https://tmsearch.uspto.gov/prod-stage-v1-0-0/tmsearch
[S6]: https://euipo.europa.eu/eSearch/
[S7]: https://branddb.wipo.int/
[S8]: https://www.tmdn.org/tmview/
[S9]: https://www3.wipo.int/madrid/monitor/en/
[S10]: https://pypi.org/pypi/mimiji/json
[S11]: https://pypi.org/simple/
[S12]: https://registry.npmjs.org/mimiji
[S13]: https://registry.npmjs.org/-/v1/search?text=mimiji
[S14]: https://github.com/mimiji
[S15]: https://itunes.apple.com/search?term=mimiji&entity=software&country=tw
[S16]: https://itunes.apple.com/lookup?id=6793203040,6758508178,6747191021,6759178173,6451367877,6752370485,1255363631,932496645,6789568667,6815067746,6815771741,6811910022,6763214146,6773571974&country=jp
[S17]: https://itunes.apple.com/search?term=mimiji&entity=macSoftware&country=us
[S18]: https://seino-ta.github.io/mimifude-site/
[S19]: https://apps.microsoft.com/api/products/search?query=mimiji&mediaType=all&age=all&price=all&category=all&subscription=all&gl=US&hl=en-US
[S20]: https://play.google.com/store/search?q=mimiji&c=apps&hl=en&gl=US
[S21]: https://play.google.com/store/apps/details?id=com.fidelioware.mimi
[S22]: https://rdap.verisign.com/com/v1/domain/mimiji.com
[S23]: https://dns.google/resolve?name=mimiji.com&type=A
[S24]: https://pubapi.registry.google/rdap/domain/mimiji.app
[S25]: https://mimiji.app/
[S26]: https://pubapi.registry.google/rdap/domain/mimiji.dev
[S27]: https://data.iana.org/rdap/dns.json
[S28]: https://dns.google/resolve?name=mimiji.io&type=NS
[S29]: https://huggingface.co/kyutai/mimi
[S30]: https://play.google.com/store/apps/details?id=com.global.jing.trans
[S31]: https://play.google.com/store/apps/details?id=com.marimoko.mimi
