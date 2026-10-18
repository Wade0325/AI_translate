# 研究：中文評測素材的來源與授權，並推薦中日文評測片段

回答 #121（#15 的延伸）。日文素材的來源與授權已經在 #79 研究過；這份補上中文，並把中日文的推薦片段落到具體檔案。

> 所有連結都在 2026-10-19 查詢。引用處標 [S 編號]，對應文末的來源清單；寫「#79」的地方指 #79 的報告（分支 `research/79-japanese-eval-material`）。
> 這份筆記整理授權原文、法條與官方頁面，不是法律意見。標「判斷」的是我從原文推論的結論，標「未查證」的是沒能從第一手資料確認的事。
> 沒有下載任何音檔或資料集壓縮檔。大小、長度與說話者數取自官方頁面、論文、metadata API 或 HEAD 回應的 Content-Length。

## 答案摘要

- **能放進 repo 的多人會議語料，只有 AliMeeting。** OpenSLR 標示 CC BY-SA 4.0，阿里巴巴自己的 ModelScope 標示 Apache License 2.0，兩邊都沒有 NC [S7][S8]。內容是真實會議，每段 15～30 分鐘、2～4 人，有遠場 8 聲道與每人一支頭戴麥克風，附含說話者與時間的逐字稿 [S7][S9]。說的是中國大陸的普通話。
- **AISHELL-4 的授權現在互相矛盾，先只留本機。** OpenSLR 從 2021 年到現在都標 CC BY-SA 4.0 [S1][S3]；擁有者希爾貝殼的頁面在 2021 到 2026 年間從 CC BY-SA 4.0 改成 CC BY 4.0、Apache 2.0，現在改成 CC BY-NC-SA 4.0，並列出商業用途的聯絡信箱 [S2][S3]。CC BY-SA 4.0 是不可撤回的授權 [S72]，但要把衍生的標準答案放進 repo 之前，先寫信請 AISHELL 確認。它值得留著：MOSS 的技術報告就是拿 AISHELL-4 測試集當長檔會議的基準 [S10]，可以用來核對我們的流程。
- **台灣華語的多人素材，附人工紀錄而且授權確定的，都只能留本機。**
  - 立法院 IVOD 的質詢片段最合用：多人快速對答，每段有人工整理的速記錄。但 IVOD 的著作權聲明限「個人、非商業用途」，立法院會議錄影錄音管理規則也禁止把影音訊號用於任何商業目的 [S28][S31]。
  - 地方議會與憲法法庭的情況類似：臺北市議會只允許合理使用，新北、臺中是版權所有，高雄限個人非商業；憲法法庭的筆錄可以依開放宣告使用，但影片放在 YouTube [S36][S37]。
- **台灣口音而且能放進 repo 的，目前只有朗讀。** 維基共享資源上有 66 個口音欄寫「台灣」的有聲維基百科檔案，共 12.75 小時，授權是 CC BY-SA，底稿是朗讀時的條目版本 [S52]。例如〈小雁塔〉長 15:20，女聲。
- **要台灣口音、多人、又能公開的素材，得自己聽打。** 國家文化記憶庫有 CC BY 3.0 TW+ 的座談與訪談 [S38]，g0v 零時小學校的雙人對談影片是 CC BY-SA 4.0 [S41]，都沒有官方下載，要向提供單位索取原始檔，再自己做標準答案。
- **Common Voice zh-TW 只能留本機。** 授權是 CC0，但 Mozilla Data Collective 的下載條款禁止再散布 [S44][S45]，和 #79 的日文結論一樣。它有 131.7 小時、2,336 位說話者，每段平均 3.4 秒 [S46]。
- **LibriVox 中文有聲書是公有領域，可以進 repo。** 共 26 部完整作品，例如魯迅的《徬徨》《吶喊》、《阿Q正傳》[S48]。底稿可以用維基文庫的原文 [S51]。但朗讀者的口音都查不到。
- **台灣的學術語料都是限學術或非營利，而且禁止轉給第三人。** 包括 NER 廣播語料、MATBN 公視新聞、中研院 MCDC 對話語料與政大口語語料庫 [S19][S20][S21]。其餘中國大陸的對話語料，包括 MagicData-RAMC、KeSpeech、WenetSpeech、MISP、CS-Dialogue，也都是 NC 或禁止散布 [S13][S14][S15][S17]。
- **日文：こころ沒有一章超過 15 分鐘，改用《坊っちゃん》第一章（24:45）。** LibriVox 日文的單人作品幾乎全由同一位朗讀者 ekzemplaro 錄製 [S57]，換聲音要從多語合集挑，例如《蜘蛛の糸》。唯一能進 repo 的日文多人自然對話，是國語研方言錄音的京都話 3 人閒談（CC BY 4.0）[S66]。國會審議影片只能留本機，会議録也不是逐字的 [S59][S63]。
- **推薦的評測片段**：中文 5 段，其中 2 段只留本機；日文 5 段，其中 1 段只留本機。每種語言都至少有一段多人對話與一段超過 15 分鐘的長檔（見「推薦的評測片段」）。

## 怎麼判斷

沿用 #79 的三道關卡：著作權授權允不允許再散布、取得管道的契約有沒有另外禁止、標準答案的文字本身。這次多了兩件事：

- **同一份資料有兩種授權說法時，以較嚴的處理。** AliMeeting 的 CC BY-SA 4.0 與 Apache 2.0 都允許再散布，衍生的標準答案用 CC BY-SA 4.0 就能同時滿足。AISHELL-4 的 CC BY-SA 4.0 與 CC BY-NC-SA 4.0 互相衝突，NC 會擋住進 repo（ADR 0006）。
- **CC 授權不能事後撤回。** CC BY-SA 4.0 的授與條款寫明是「irrevocable license」；第 6(c) 條說授權人可以改用別的條件或停止散布，「however, doing so will not terminate this Public License」[S72]。判斷：從 OpenSLR 依 CC BY-SA 4.0 取得的 AISHELL-4，原則上仍可依 CC BY-SA 4.0 使用；但擁有者現在的頁面寫 NC，為了避免爭議，進 repo 前先取得書面確認。

## 候選來源總表

| 來源 | 內容 | 口音 | 授權 | 進 repo | 本機評測 | 標準答案 |
|---|---|---|---|---|---|---|
| AliMeeting | 真實會議 2～4 人，118.75 小時 | 中國大陸 | CC BY-SA 4.0／Apache 2.0 | 可 | 可 | 人工逐字稿，含說話者與時間 |
| AISHELL-4 | 真實會議 4～8 人，120 小時 | 中國大陸 | OpenSLR CC BY-SA 4.0；擁有者現標 CC BY-NC-SA 4.0 | 先不要（待確認） | 可 | 人工逐字稿，含說話者與時間、贅詞 |
| 立法院 IVOD＋公報 | 質詢，多人對答 | 台灣 | 影音限個人非商業；公報文字為開放資料 | 不可（影音） | 可（非商業） | 人工速記錄，整理過，沒有逐句時間 |
| 地方議會、憲法法庭 | 質詢、言詞辯論 | 台灣 | 合理使用／版權所有／非商業；筆錄有開放宣告 | 不可（影音） | 視各機關條款 | 速記錄、筆錄，整理過 |
| 國家文化記憶庫 | 座談、訪談，2～8 人 | 台灣（未查證） | 逐件標示，部分 CC BY 3.0 TW+ | 可（CC BY 的件） | 可 | 沒有，要自己聽打 |
| g0v 零時小學校 | 雙人對談，20～129 分鐘 | 台灣（推定） | CC BY-SA 4.0 | 可（要先取得原始檔） | 可 | YouTube 上的人工字幕，是否逐字未查證 |
| 有聲維基百科（台灣口音） | 朗讀條目，66 檔 12.75 小時 | 台灣（自填） | CC BY-SA 3.0／4.0 | 可 | 可 | 條目原文，要對照校正 |
| LibriVox 中文 | 有聲書朗讀，26 部 | 未查證 | 公有領域 | 可 | 可 | 原著文字，要對照校正 |
| 美國之音（VOA） | 新聞、訪談 | 不一定；馬英九專訪的受訪者是台灣人 | VOA 自製者為公有領域 | 待判斷（受訪者的發言） | 可 | 部分節目有全文，未查證是否逐字 |
| Common Voice zh-TW | 短句朗讀 | 台灣 | CC0＋平台條款 | 不可 | 可 | 朗讀的提示句 |
| FLEURS cmn | 短句朗讀 | 未標示 | CC BY 4.0 | 可 | 可 | 朗讀的維基句子 |
| 科技大擂台 FLUD | 文章與題目朗讀，約 400 小時 | 未查證 | 政府資料開放授權條款 | 可 | 可 | 朗讀稿 |
| ASCEND | 中英夾雜對話，只有切好的句子 | 香港收錄 | CC BY-SA 4.0 | 可 | 可 | 人工逐句聽打 |
| MagicData-RAMC、KeSpeech、WenetSpeech 等 | 對話、朗讀、網路影音 | 中國大陸 | NC 或禁止散布 | 不可 | 視條款 | — |
| NER、MATBN、MCDC、政大口語語料 | 廣播、新聞、對話 | 台灣 | 限學術或非營利，禁止轉給第三人 | 不可 | 只限學術授權 | 人工聽打 |

## 各來源細節

### 中國大陸的會議語料

#### AliMeeting（M2MeT）

- **授權**：
  - OpenSLR 頁面：「License: CC BY-SA 4.0」[S7]。
  - 阿里巴巴的 ModelScope 頁面：metadata 的 License 欄與 README 的「数据集版权信息」都寫「Apache License 2.0」[S8]。
  - 我沒有找到任何 NC 聲明。M2MeT 挑戰賽的規則（Wayback 存檔）只約束比賽，例如不得用測試集訓練 [S9]。
- **取得**：阿里雲 OSS 直接下載，不必註冊 [S7]。
  - `Eval_Ali.tar.gz`：3,673,718,355 bytes，含遠場與近場 [S7]。
  - `Test_Ali.tar.gz`：9,555,497,666 bytes [S7]。
  - 訓練集的遠場與近場檔各 78.6 GB 與 24.5 GB [S7]。
- **規模**：
  - 共 118.75 小時：訓練 104.75 小時 212 段、驗證（Eval）4 小時 8 段、測試 10 小時 20 段；「each session consists of a 15 to 30-minute discussion by 2-4 participants」[S7]。
  - 遠場是 8 聲道麥克風陣列，近場是每位與會者的頭戴麥克風 [S7]；取樣率 16 kHz [S8]。
  - 論文：「All participants are native Chinese speakers speaking Mandarin without strong accents.」[S9]
- **標準答案**：每段一個 TextGrid，含說話者編號、時間與文字；論文說原始的聽打稿也標出停頓、雜音與重疊 [S9]。判斷：說話者標記與時間都有，可以算 cpMER。
- **驗證集各段的人數**（取自 ModelScope 的 `Eval_Ali.csv` 與近場檔名）[S8]：
  - 4 人：R8001_M8004_MS801、R8003_M8001_MS801、R8007_M8010_MS803、R8007_M8011_MS806
  - 3 人：R8008_M8013_MS807
  - 2 人：R8009_M8018_MS809、R8009_M8019_MS810、R8009_M8020_MS810
- **未查證**：每段的確切長度沒有公開；TextGrid 的標記規則與簡繁。

#### AISHELL-4

- **授權的三種說法**：
  - OpenSLR：「License: CC BY-SA 4.0」[S1]。
  - 擁有者希爾貝殼的頁面（2026-10-10 版的頁面腳本）：「License: CC BY-NC-SA 4.0」，下方列「商业用途：bd@aishelldata.com」[S2]。
  - Wayback Machine 的存檔顯示，擁有者頁面在 2021 年 7 月是 CC BY-SA 4.0，2021 年 12 月是 CC BY 4.0，2022 年 8 月到 2026 年 5 月是「Apache License v.2.0」[S3]。
  - Hugging Face 上帳號名為 AISHELL 的鏡像標 `apache-2.0`（2024-01 建立）[S5]。未查證：這個帳號是不是希爾貝殼官方的。
- **判斷**：改成 NC 的時間落在 2026 年 5 月中到 10 月之間，原因沒有公告。依「怎麼判斷」一節，先只留本機；要把衍生的標準答案放進 repo，先寫信給 tech@aishelldata.com 確認。
- **取得**：OpenSLR 的 `test.tar.gz`，5,241,010,904 bytes，三個鏡像都可直接下載 [S1]。只要一段也得下載整包；Hugging Face 鏡像有逐段的 FLAC，但來源未經確認 [S5]。
- **規模**：
  - 211 段、120 小時，每段 4～8 人 [S1]。測試集 20 段、12.72 小時 [S4]。
  - 論文：「All participants are native Chinese speakers speaking Mandarin without strong accents」[S4]。
- **標準答案**：每段一個 TextGrid，每位說話者一層，層名如 `001-M` [S5]。
  - 我讀了 M_R003S02C01 的 TextGrid：簡體、全形標點，保留「呃」「嗯」等贅詞與「才能才能才能」這類重複，並有 `<sil>` 等記號 [S5]。記號的意義沒有文件說明（未查證）。
  - 基線程式另附測試集 20 段去掉標點與記號的參考文字（STM 格式）[S6]。
  - 判斷：這是真正的逐字稿，比速記錄或原著底稿更接近我們要的標準答案。
- **和 MOSS 的關係**：
  - MOSS Transcribe Diarize 技術報告用 AISHELL-4 測試集評測：長 2,195.4～2,393.9 秒、平均 2,290.6 秒、5～7 人 [S10]。
  - 它取遠場 8 聲道的平均：「We use the averaged channel of the far-field signals for both training and evaluation.」[S10] 同一節也說 AISHELL-4 用在訓練。
  - MOSS 在 AISHELL-4 的 CER 是 14.84%、cpCER 15.83%；在 AliMeeting 是 24.86% 與 22.17% [S10]。
  - 判斷：照報告的做法（8 聲道平均）跑一段，可以核對我們的流程有沒有把 MOSS 用歪。

#### 其他中國大陸語料

| 語料 | 授權原文 | 內容 | 結論 |
|---|---|---|---|
| ASCEND | Hugging Face 卡片 `cc-by-sa-4.0` [S11] | 香港收錄的中英夾雜雙人對話，10.62 小時；只釋出切好的句子，平均 3.1 秒 [S11] | 可進 repo；沒有整段對話，不適合測長檔 |
| FLEURS cmn_hans_cn | 卡片 `cc-by-4.0` [S12] | 朗讀維基句子；測試集 945 句、約 3.07 小時；`test.tar.gz` 525,346,466 bytes [S12] | 可進 repo；只適合短句煙霧測試 |
| AISHELL-1、AISHELL-3、THCHS-30 | OpenSLR「Apache License v.2.0」[S16] | 朗讀 | 可進 repo；短句朗讀 |
| AISHELL-2 | 頁面寫 Apache 2.0，但同時限學術研究、商用要許可 [S16] | 朗讀 1,000 小時 | 不要用 |
| MagicData-RAMC | 「Attribution-NonCommercial-NoDerivatives 4.0 International Public License (CC BY-NC-ND 4.0)」[S13] | 手機錄的雙人對話 180 小時，每段約 30 分鐘，663 人來自各地 [S13] | 只留本機或不要用（NC、ND） |
| KeSpeech | 自訂授權：「不得将本数据集用于任何商业目的」「不得对本数据集进行演绎」「不得向任何第三方分发本数据集」[S14] | 朗讀，普通話與 8 種次方言 | 不要用 |
| WenetSpeech（含 TEST_MEETING） | 「available to download for non-commercial purposes under a Creative Commons Attribution 4.0 International」；「WenetSpeech doesn't own the copyright of the audios」[S15] | YouTube 與 podcast；TEST_MEETING 15 小時 | 不要用 |
| ST-CMDS、Primewords、MAGICDATA 朗讀、SHALCAS22A | OpenSLR 標 CC BY-NC-ND 4.0 [S16] | 朗讀 | 不要用；aidatatang_200zh 已依擁有者要求下架 [S16] |
| AISHELL-5、MISP、CS-Dialogue、Emilia、SpeechIO | NC、授權互相矛盾或沒有授權 [S17] | 車內、居家、中英對話等 | 不要用 |
| YODAS zh000 | `cc-by-3.0`；299.37 小時，只有上傳者字幕 [S18] | YouTube | 同 #79：無法回溯創作者，只建議留本機 |

### 台灣華語

#### 立法院議事轉播（IVOD）與立法院公報

- **內容**：IVOD 的「委員發言片段」是「每位立法委員上台發言的獨立剪接片段影片」[S29]，委員和院長、部長多人對答，說的是台灣華語，偶爾夾英文。
- **例子**：第 11 屆第 2 會期第 2 次會議（2024-10-01，對行政院院長施政報告繼續質詢）楊瓊瓔委員的片段，影片長度 00:30:43 [S30]。發言紀錄標出 9 位發言者：委員、主席、行政院院長，以及 4 位部長、1 位主委與 1 位次長；約 1 萬字 [S30]。
- **影音的授權**：
  - IVOD 著作權聲明：「使用者下載或拷貝『立法院議事轉播網際網路多媒體隨選視訊系統』網站（以下簡稱本網站）的內容或服務僅供個人、非商業用途之使用」，並且「不可變更、發行、播送、轉賣、重製、改作、散布、表演、展示或利用本網站上局部或全部內容及服務以賺取利益」[S28]。
  - 立法院會議錄影錄音管理規則第 2 條第 2 項：「前項影音訊號不得做為任何形式之商業目的、廣告、促銷、宣傳、政治目的、選舉或訴訟使用。」[S31] IVOD 的公告事項也寫了同一句 [S29]。
- **取得**：
  - 播放頁只有串流，沒有下載鈕 [S30]。
  - 立法院開放資料服務平台的「委員發言片段相關影片資訊」提供每一段的 `videoUrl` 與 `speechRecordUrl`，共 34,885 筆 [S35]。
- **發言紀錄是怎麼來的**：
  - 立法院組織法第 18 條：公報處掌理「關於本院會議及委員會會議之錄影錄音及轉播事項」「關於本院會議及委員會會議之速記事項」「關於公報編印及發行事項」[S33]。
  - 立法院議事規則第 56 條：「院會中出席委員及列席人員之發言，應由速記人員詳為記錄，並將速記錄印送全體委員。」[S32]
  - 錄影錄音管理規則第 5 條第 2 項：公開會議的錄音「於速記錄刊印公報後，保存一個月」[S31]。
  - IVOD 片段頁：「發言紀錄連結未出現，表示人工作業中，請耐心等候。」[S30]
  - 樣本的樣子：每一輪標出職稱與姓名（如「楊委員瓊瓔：」「卓院長榮泰：」），保留被打斷的句子（「……」）、重複的追問、句尾的「欸」與夾雜的英文；只有開頭標了「（9 時 1 分）」，沒有逐句時間；數字寫成阿拉伯數字 [S30]。
  - 判斷：這是人工整理的速記錄，接近逐字，但不是逐字稿。有沒有刪掉「嗯」「那個」之類的贅詞，要對照錄音才知道。
- **文字的授權**：
  - 立法院開放資料服務平台的授權條款是「政府資料開放授權條款－第1版」，平台提供「公報原始檔案」（院會公報的 doc 檔，自第 8 屆第 1 會期起）[S35]。這個資料集的 API 在查詢當天顯示「系統維護中」。
  - 立法院全球資訊網的資料開放宣告也以「無償、非專屬，得再授權之方式提供公眾使用」，但排除「部份的影音、圖像、樂譜、專人專案撰文或其他著作，經機關特別聲明須經同意方可使用者」[S34]。
- **著作權法** [S69]：
  - 第 62 條：「政治或宗教上之公開演說、裁判程序及中央或地方機關之公開陳述，任何人得利用之。但專就特定人之演說或陳述，編輯成編輯著作者，應經著作財產權人之同意。」第 63 條第 3 項允許依第 62 條利用的人散布；第 64 條要求明示出處。
  - 第 9 條：公文不得為著作權之標的；「前項第一款所稱公文，包括公務員於職務上草擬之文告、講稿、新聞稿及其他文書。」
  - 第 50 條：「以中央或地方機關或公法人之名義公開發表之著作，在合理範圍內，得重製、公開播送或公開傳輸。」
- **判斷**：
  - 委員與官員在會議上的發言內容屬於第 62 條的公開陳述，任何人都可以利用，要註明出處。公報文字另有開放授權，可以進 repo。
  - IVOD 的錄影錄音是立法院製作的另一份著作，受它的聲明與管理規則約束，實際上等於非商業授權。第 50 條只允許「合理範圍內」的重製，長期放在公開 repo 算不算合理，沒有把握。所以影音只留本機。
  - 本機評測屬於非商業用途；但 ADR 0006 保留了商業化的可能，真的商業化時要停用這批影音，或先取得立法院的書面同意。
  - 未查證：智慧局對議事錄影適用第 50 條或第 62 條的函釋；我沒有找到。
- **以 IVOD 做成的衍生資料集**（只記錄，不建議用）[S27]：
  - ETH 的 WorldSpeech `zh_tw` 約 1,482 小時，CC BY-NC 4.0；用 Whisper 的輸出在全文紀錄裡定位切段，沒有說話者標記。
  - lianghsun/ly-ivod-asr-zhtw 的文字由模型產生、未經人工校對，限非商業研究。
  - openfun/ivod-fine-tune 標 CC BY 4.0，但沒有說明文字的來源；Luigi/ivod-zhtw-10min-maps 與 FetchieAI/MinHeng_ivod 把 IVOD 影音標成 MIT，卡片沒有出示權利人的授權。

#### 地方議會與憲法法庭

- **憲法法庭** [S36]：
  - 網站資料開放宣告以「無償、非專屬，得再授權之方式」開放網站上的資料，但排除「經機關特別聲明須經同意方可使用」的部分影音；司法院的宣告明寫採「政府資料開放授權條款-第1版」。
  - 每件言詞辯論都有「言詞辯論筆錄」PDF，逐輪標出審判長、大法官、代理人等角色與姓名；內容完整但經過整理，沒有贅詞。
  - 影片放在司法院的 YouTube 頻道，網站沒有下載。宣告是否涵蓋 YouTube 上的影片，沒有寫。
  - 例子：108 年度憲二字第 214 號，2024-03-12，長 2:14:28，筆錄 46 頁，約 20 位發言者。
  - 判斷：筆錄可以進 repo；影音要先取得憲法法庭的書面確認。
- **地方議會** [S37]：
  - 臺北市議會：「本會網站之內容，得依著作權法規定為合理使用；引用時，請註明出處。」影片是串流。
  - 新北市議會：頁尾「新北市議會版權所有」，沒有找到著作權聲明。它的會議紀錄最接近逐字，保留重複與自我更正；每個影片段落旁邊就是對應的文字，影片是可直接存取的 MP4。例如 2026-04-07 第 4 屆第 7 次定期會「各機關聯合業務報告及質詢」：約 6.5 萬字、1,011 輪、33 個發言者標記；其中一段 MP4 為 654,509,537 bytes。
  - 臺中市議會：「本網站之所有版權屬臺中市議會所有，未經授權不得轉載。」會議紀錄只是摘要。
  - 高雄市議會：「使用者下載或拷貝網站的內容或服務僅供個人、非商業用途之使用。」有近似逐字的譯文稿。
  - 判斷：四個議會的影音都不能進 repo。

#### 國家文化記憶庫、g0v 與研討會錄影

這一類的授權允許進 repo，但沒有標準答案，也沒有官方下載。

- **國家文化記憶庫** [S38]：
  - 「如您欲使用本站素材及故事進行各項創作或分享，其權利標示仍須以原始資料來源之權利標示為準。」每件分別標示「數位物件授權」與「描述文字授權」；沒有標示的件「應被理解為僅限公開瀏覽」。
  - 「目前國家文化記憶庫網站未提供影片下載功能。…是否可取得原始檔案或進一步利用，請依資料提供單位之規定辦理。」
  - 例子：286223「綜合討論與座談」（2019 宜蘭縣社區總體營造論壇），數位物件授權「CC BY 3.0 TW +」，建檔單位宜蘭縣政府文化局；主持人與 4 位與談人，加上民眾提問。頁面沒有標長度；把串流播放清單的片段長度加總，約 53:49。
  - 判斷：CC BY 3.0 TW+ 的件可以進 repo，但要向建檔單位索取原檔，標準答案要自己聽打；說的是不是華語要先聽過（未查證）。
- **g0v 零時小學校** [S41]：
  - 「零時小學校數位授課影片將以姓名標示-相同方式分享 4.0 國際 (CC BY-SA 4.0) 授權條款釋出。」
  - 有雙人對談，例如 KNmTMs1GTV4（94:31）與 pvjAhP3Bf4c（21:44）；YouTube 上有人工的中文字幕軌，是否逐字未查證。
  - 只放在 YouTube。YouTube 條款禁止未經授權下載，要向 g0v 索取原始檔。
- **研討會**：COSCUP 2024 年起以 CC BY 4.0 釋出錄影，PyCon TW 的影片在 YouTube 上標 CC BY [S41]。多為單人演講，沒有人工字幕。

#### 政府記者會與公共媒體

| 來源 | 條款 | 影音 | 文字 | 結論 |
|---|---|---|---|---|
| 總統府 | 網站採「政府資料開放授權條款-第1版」，排除經特別聲明的影音 [S39] | 只放 YouTube | 問答全文經過整理，不是逐字 | 文字可進 repo；影音要另外確認 |
| 行政院 | 同上 [S39] | 院會後記者會只放 YouTube | 沒有逐字稿 | 只留本機 |
| 疾管署 | 開放宣告與著作權聲明互相矛盾 [S39] | YouTube，有人工中文字幕 | 只有新聞稿 | 只留本機 |
| 公共電視、國家教育廣播電臺 | 版權所有；使用要先取得同意 [S40] | — | — | 不要用 |
| 中央廣播電臺 | 授權要申請；「政府部門或基於學術研究、教育推廣等公益目的使用者，得申請免費使用」[S42] | — | — | 要用就先申請 |
| 臺大、陽明交大開放式課程 | 創用 CC「姓名標示-非商業性-相同方式分享」[S40] | 單人授課 | — | 只留本機 |
| archive.tw（SayIt） | 「除另有標示外，內容以 CC0 釋出」[S43] | 沒有錄音 | 會議逐字稿，經過整理 | 沒有音檔，用不上 |

#### 台灣的學術語料

全部限學術或非營利，而且禁止轉給第三人，所以都不能進 repo。

| 語料 | 內容 | 授權原文與價格 |
|---|---|---|
| NER-Trs／NER-Pro（國立教育廣播電臺） | 談話性節目為主，切成約 15～30 秒；Trs 是辨識結果再經兩次人工校正 [S19][S20] | 「本人僅能將 NER-Trs 音檔使用於學術研究、教育或公益用途，不得以此牟利或從事商業行為。」「本人不得將 NER-Trs 音檔之全部或部份轉移給第三人。」每集 NT$1,000 [S20] |
| FSR 挑戰賽（2018 年起） | 2018 用 NER；2020 起是台語與客語 [S19] | 「Non-Commercial Use Only」[S19] |
| MATBN | 公視新聞 198 小時，標出說話者輪替與時間 [S20] | 「non-exclusive, non-transferable right to use MATBN for scientific research purposes only」；NT$40,000 [S20] |
| 中研院 MCDC8／SPCCSD | 8 段對話，每段約 1 小時，兩人分錄左右聲道 [S20][S22] | 「不得包含／引用於任何商業產品中」「不得…移轉給第三人」；學術 NT$50,000 起 [S20] |
| 政大口語語料庫 | 大學生對話約 3.5 小時 [S21] | TalkBank：「the use of TalkBank data is governed by the Creative Commons CC BY-NC-SA 3.0 copyright license」[S21] |
| TCC-300、MAT 系列 | 朗讀、電話 [S20] | 有商用版，但「不得將…之全部或部份轉移給第三人」[S20] |

#### Hugging Face 上的台灣華語資料集

- **科技大擂台 FLUD**：SciDM 標示 `OGL-TW-1.0`（政府資料開放授權），發布者科技政策研究與資訊中心，「現有語音資料量約400小時」[S23]。內容是朗讀文章、題目與選項，部分加了雜訊；文字是朗讀稿，不是逐字稿。下載要填同意表。判斷：可以進 repo，但它是朗讀；朗讀者的口音與人數都沒有說明（未查證）。
- **臺大機器學習 2021 課程**：卡片寫 MIT，文字由 20 多位標註者人工聽打 [S24]。長檔版本把同一堂課的片段接起來，14 個檔、每檔 16.6～71.8 分鐘 [S24]。但卡片沒有出示臺大或授課者的授權；要進 repo 先取得書面確認。
- **Breeze-ASR-25 的評測集**：自建的 Formosa-Go 等測試集沒有釋出 [S25]。
- **重新標授權的資料集**：formospeech 組織的 `matbn`、`eat_mic16k` 等都設了存取審核，但 MATBN 與 EAT 的權利屬交大與計算語言學學會，卡片沒有出示授權 [S26]。不要用。

### 朗讀與廣播

#### Common Voice zh-TW／zh-CN

- **授權**：Mozilla Data Collective（MDC）的頁面標「CC0-1.0」[S44]。
- **平台條款**：
  - 下載對話框：「You agree that you will not re-host or re-share this dataset」[S44]。
  - MDC 資料使用者條款（Last Updated: May 06, 2026）第 2(b)(ix) 條禁止「hosting, storing or making the Dataset available on any platform, server or repository other than the Platform, except as expressly permitted under the applicable Data Consumer License for that Dataset」；附錄 1 第 8 條禁止「scrape, mirror, or redistribute the Dataset」[S45]。
  - MDC 的 FAQ 說明，CC0 仍是運算使用的授權，但禁止鏡像是平台條款 [S45]。
- **規模**（27.0 版）[S46]：

  | 項目 | zh-TW | zh-CN |
  |---|---|---|
  | 段數 | 140,996 | 852,410 |
  | 總時數／驗證過 | 131.7／79.92 小時 | 1,074.96／240.11 小時 |
  | 說話者 | 2,336 | 7,601 |
  | 平均長度 | 3.363 秒 | 4.54 秒 |
  | 壓縮檔 | 3,173,160,333 bytes | 22,978,420,467 bytes |

- **口音**：口音欄是說話者自填的出生地。zh-TW 有 39.7% 的段落填了，最多的是臺北市（19,691 段、108 人）[S46]。
- **自由說話**：Spontaneous Speech 5.0 的 80 種語言裡，普通話只有 zh-CN 的 1 段，沒有 zh-TW；漢語族另外只有莆仙話與閩東話 [S46]。
- **判斷**：同 #79，只能留本機；而且是短句朗讀。

#### LibriVox 中文有聲書

- **授權**：LibriVox 的錄音捐入公有領域，可以任意使用、不必取得許可；但它只保證在美國是公有領域 [S47]。archive.org 的 `licenseurl` 多為 Public Domain Mark 1.0 [S49]。
- **數量**：錄音語言是中文的完整作品共 26 部（不含多語合集裡的單篇）[S48]。中文沒有多人分飾的廣播劇；唯一的劇本《長生殿》是單人朗讀 [S48]。
- **原文**：
  - 魯迅 1936 年歿 [S51]。台灣著作權法第 30 條規定保護到作者死亡後五十年 [S69]，中國著作權法第 23 條也是「作者终生及其死亡后五十年」[S70]。判斷：兩地都已過保護期。
  - 中文維基文庫：「您可以複製屬於公有領域的文章，並根據您的需要任意使用」[S51]。Project Gutenberg 的文字去掉它的標頭與商標後可以自由使用 [S50]。
- **朗讀者**：LibriVox 的朗讀者頁只有名稱，沒有地區或性別；論壇個人頁要登入 [S48]。判斷：口音只能聽了才知道。
- **可用的章節**（archive.org metadata）[S49]：
  - 《徬徨》〈祝福〉（Tina Ding）37:13，17,886,648 bytes。
  - 《吶喊》〈狂人日記〉（Jing Li）20:34，9,875,330 bytes。
  - 《老殘遊記》第一回（HC）19:04，9,159,284 bytes。
  - 《阿Q正傳》第一章（Vivienne Wong）07:46，3,736,064 bytes。

#### 維基共享資源的有聲維基百科

- 「Spoken Chinese Wikipedia」分類有 302 個檔案，其中 202 個超過 5 分鐘 [S52]。
- 每個檔案頁都有朗讀者自填的性別、語言與口音欄。口音寫「台灣」「臺灣」或 Taiwan 的有 66 個、共 12.75 小時；授權是 CC BY-SA 4.0（61 個）與 CC BY-SA 3.0（5 個）[S52]。
- 有些檔案在口音欄寫明是 TTS，要排除 [S52]。
- **例子**：File:Zh-tw-小雁塔.ogg，8,053,876 bytes，920.3 秒，CC BY-SA 4.0，朗讀者 Yu chuan，「sex=female」「accent=台灣」，朗讀的是 oldid 36693535 的條目版本 [S52]。
- **判斷**：
  - 條目文字是 CC BY-SA，可以當標準答案的底稿；朗讀者可能跳過表格與參考資料，要對照錄音校正。
  - 口音是自填的，也只有單人朗讀，但這是唯一授權乾淨、又能超過 15 分鐘的台灣口音音檔。

#### 美國之音（VOA）

- **條款**：「All text, audio and video material produced exclusively by the Voice of America is in the public domain.」同一條也說，網站上有些授權素材不是公有領域；美聯社、法新社、路透社的內容另有限制 [S54]。
- **例子**：維基共享資源的 File:VOA專訪馬英九200603.webm，847.3 秒、22,311,691 bytes，標示公有領域；記者與馬英九兩人對答，原網頁有問答全文 [S53]。
- **現況**：USAGM 在 2025-03-15 宣布把所屬媒體縮減到法定最低限度 [S55]；voachinese.com 仍在發布節目。
- **判斷**：記者與 VOA 自製的部分是公有領域；受訪者自己的發言算不算「produced exclusively by the Voice of America」，條款沒寫。要進 repo 先處理這個問題。

### 日文的補充

#### 國會：審議影片只能留本機，会議録不是逐字

- **影片**：
  - 衆議院インターネット審議中継：「個々の情報（文字、写真、映像等）は著作権の対象となっています。ご利用にあたっては、著作権法の範囲内でご使用ください。」[S59] 参議院的說法相同；兩院都只提供串流 [S59]。
  - 兩院網站只允許私人使用、引用、學校授課等著作權法上認可的行為，並禁止擅自改變 [S60]。
- **会議録**：
  - 国会会議録検索システムの利用条件：「その他の発言の著作権は個々の発言者に帰属し、その利用については、原則として、著作権者の許諾が必要となります。」但「政治上の演説又は陳述に該当する箇所の利用」等權利限制規定適用時不必許諾 [S61]。
  - 衆議院規則第 203 條允許發言者更正字句，「ただし、演説の趣旨を変更することはできない。」参議院規則第 156 條：「会議録には、速記法によつて、すべての議事を記載しなければならない。」[S62]
  - 河原達也等人的論文：正式紀錄與實際發言的用詞差異在 10～20%，平均 13%；刪除贅詞占所有修改的 50.1%，刪除話語標記占 23.5% [S63]。判斷：会議録是整理過的紀錄，當標準答案要對照錄音校正。
- **著作權法** [S64]：
  - 第 40 條第 1 項：「公開して行われた政治上の演説又は陳述…は、同一の著作者のものを編集して利用する場合を除き、いずれの方法によるかを問わず、利用することができる。」
  - 第 102 條把部分權利限制準用到著作鄰接權，但沒有包括第 40 條。
  - 判斷：議員與大臣的發言內容大致可以利用，但院方製作的影像另有權利，第 40 條管不到；委員會形式上不公開（國會法第 52 條），政府參考人的發言也未必算「政治上」。結論同台灣：影音只留本機。本機評測可能適用第 30 條之 4（技術開發的試驗），但維護者不在日本時未必適用（#79）。
- **例子**：第 221 屆國會，衆議院 沖縄及び北方問題に関する特別委員会 第3号（2026-06-29）。審議中継的影片長 49 分鐘；会議録有 30 則發言、14,165 字、7 位發言者（委員長、3 位議員、大臣與 2 位政府參考人）[S65]。会議録開頭委員長說「速記を止めてください」，記為〔速記中止〕，下一則才「速記を起こしてください」，所以有一段沒有記錄 [S65]。

#### LibriVox 日文：換朗讀者要從多語合集挑

- 單人完整作品 37 部，除了兩部古典由 kaseumin 朗讀，其餘全由 ekzemplaro 朗讀 [S57]。
- 《こころ》分成 110 段，每段 3:57～5:31，沒有一段超過 15 分鐘 [S57]。
- 《坊っちゃん》11 章都在 17:55～31:56 之間；第一章長 24:45、11,959,808 bytes [S57]。
- 多語合集裡有其他朗讀者，例如《蜘蛛の糸》（tibimama，11:08）、《青い時計台》（ryoko，09:58）、《羅生門》（dill，19:36）[S57]。朗讀者的性別頁面上沒寫。
- 原文：青空文庫對著作權已消滅的作品說「ファイルは、有償・無償であるかを問わず、自由に複製・再配布・共有することができます。」[S58]

#### JVNV 的檔案

- 壓縮檔 1,778,635,432 bytes，CC BY-SA 4.0 [S56]。
- 論文：核心台本 356 句由 4 人都錄；每種情緒各 10 句是由說話者自己決定非語言表現的 Phrase-free 台本 [S56]。
- 平均每句約 8.8 秒（由論文的表格推算）。
- 檔案結構只見於第三方程式碼：`jvnv_v1/<說話者>/<情緒>/<regular|free>/…_<編號>.wav`，台本在 `jvnv_v1/transcription.csv`（未查證）。

#### 國語研方言錄音

- 授權：「方言録音資料シリーズ3～15のテキストファイルと音声ファイルは クリエイティブ・コモンズ 表示 4.0 国際 ライセンス の下に提供されています。」[S66]
- 第 11 集「京都市方言」（1964 年錄音）：音檔壓縮檔 237,607,956 bytes，文字壓縮檔 70,999 bytes [S66]。
- 場面 (15)「鳴門のみやげ話」是 3 位京都出身的女大學生的閒談 [S66]。
- 維基共享資源上有同一集的 34.6 秒摘錄（兩位女性的對話），CC BY 4.0，只夠當煙霧測試 [S67]。
- 文字以羅馬字記錄方言的音韻，每行下面附標準語的漢字假名對譯 [S66]。判斷：要換成漢字假名，或重新聽打，才能算錯字率。

#### 政府広報「明日への声」

- 下載頁仍寫「非営利目的でのご利用に限り、自由に再生・ダウンロード・複製いただけます」；但網站條款的預設是公共データ利用規約，音聲廣報 CD 的規則又說可以自由利用 [S68]。
- 判斷：條款互相矛盾，保守起見只留本機。

## 推薦的評測片段

每種語言 5 段。「只留本機」的片段，repo 只記識別碼與官方 URL，不放音檔與文字。

### 中文

| 代號 | 內容 | 檔名／識別碼 | 下載 URL | 大小 | 長度 | 說話者 | 授權 |
|---|---|---|---|---|---|---|---|
| ZH-1 | AliMeeting 驗證集會議 | `Eval_Ali/Eval_Ali_far/audio_dir/R8008_M8013_MS807.wav` 與 `textgrid_dir/R8008_M8013.TextGrid`；近場各人一檔 | https://speech-lab-share-data.oss-cn-shanghai.aliyuncs.com/AliMeeting/openlr/Eval_Ali.tar.gz | 整包 3,673,718,355 bytes | 15～30 分鐘（官方只給範圍） | 3 | CC BY-SA 4.0／Apache 2.0；可進 repo |
| ZH-2 | AISHELL-4 測試集會議 | `M_R003S02C01`（FLAC 與 TextGrid） | https://openslr.elda.org/resources/111/test.tar.gz | 整包 5,241,010,904 bytes | 38:41（2,321.3 秒） | 6（2 男 4 女） | 授權衝突；先只留本機 |
| ZH-3 | 立法院質詢（台灣華語） | IVOD 委員發言片段 155034 | https://ivod.ly.gov.tw/Play/Clip/1M/155034（串流）；發言紀錄 https://ivod.ly.gov.tw/Demand/Speech/155034 | 串流，沒有檔案大小 | 30:43 | 9 | 個人、非商業；只留本機 |
| ZH-4 | 有聲維基百科〈小雁塔〉（台灣口音） | File:Zh-tw-小雁塔.ogg | https://upload.wikimedia.org/wikipedia/commons/7/78/Zh-tw-%E5%B0%8F%E9%9B%81%E5%A1%94.ogg | 8,053,876 bytes | 15:20 | 1（女） | CC BY-SA 4.0；可進 repo |
| ZH-5 | LibriVox《阿Q正傳》第一章 | `trueQ_01_lu_64kb.mp3` | https://archive.org/download/truestoryahq_1612_librivox/trueQ_01_lu_64kb.mp3 | 3,736,064 bytes | 07:46 | 1 | 公有領域；可進 repo |

| 代號 | 選它的理由 | 標準答案要做什麼 |
|---|---|---|
| ZH-1 | 唯一沒有 NC 聲明的多人會議語料。3 人是驗證集裡唯一的 3 人場次。判斷：遠場陣列錄音接近把錄音機放在會議桌中央的情境。MOSS 報告也有 AliMeeting 的數字可以對照 [S10]。 | 資料集的 TextGrid 已是人工逐字稿，含說話者與時間；抽查即可。標準答案是簡體，#36 的工具會先做繁轉簡正規化再比對。 |
| ZH-2 | 長檔加多人，而且是 MOSS 技術報告的基準 [S10]。照報告取 8 聲道平均，可以核對我們的流程。 | TextGrid 是逐字稿，保留「呃」「嗯」與 `<sil>` 等記號；要先定好記號與贅詞的正規化規則。AISHELL 確認授權前，標準答案不進 repo。 |
| ZH-3 | 目前唯一同時有台灣華語、多人快速對答、人工紀錄的公開素材，最接近「中文會議」的用途。 | 速記錄經過整理，也沒有逐句時間；要對照錄音校正並補上時間。 |
| ZH-4 | 唯一授權乾淨的台灣口音長檔，超過 15 分鐘。 | 以 oldid 36693535 的條目文字起草，對照錄音聽打校正。 |
| ZH-5 | 短檔，適合 #99 的快速回歸檢查；公有領域，沒有署名負擔。 | 以維基文庫〈阿Q正傳〉第一章起草，去掉注號；LibriVox 錄音開頭通常有固定的開場白（未查證），要切掉或寫進標準答案。 |

### 日文

| 代號 | 內容 | 檔名／識別碼 | 下載 URL | 大小 | 長度 | 說話者 | 授權 |
|---|---|---|---|---|---|---|---|
| JA-1 | LibriVox《坊っちゃん》第一章（ekzemplaro） | `botchan_01_natsume_64kb.mp3` | https://archive.org/download/botchan_1310_librivox/botchan_01_natsume_64kb.mp3 | 11,959,808 bytes | 24:45 | 1 | 公有領域；可進 repo |
| JA-2 | LibriVox《蜘蛛の糸》（tibimama） | `msw001_05_kumonoito_akutagawa_cs_64kb.mp3` | https://archive.org/download/mshortworks_001_1202_librivox/msw001_05_kumonoito_akutagawa_cs_64kb.mp3 | 5,350,570 bytes | 11:08 | 1 | archive.org 標 CC0；可進 repo |
| JA-3 | JVNV 子集 | Regular 台本每種情緒 01～05 × 4 人（120 句），加上全部 240 句 Phrase-free | https://ss-takashi.sakura.ne.jp/corpus/jvnv/jvnv_ver1.zip | 整包 1,778,635,432 bytes | 約 17～18 分鐘＋約 35 分鐘（由平均句長推算） | 每句 1 人，共 4 人 | CC BY-SA 4.0；可進 repo |
| JA-4 | 國語研方言錄音 第 11 集 場面 (15)「鳴門のみやげ話」 | `D0010_11_wav.zip` 與 `D0010_11.zip` 內的場面 15 | https://mmsrv.ninjal.ac.jp/hogenrokuon_siryo/data/D0010_11_wav.zip、https://mmsrv.ninjal.ac.jp/hogenrokuon_siryo/data/D0010_11.zip | 237,607,956 與 70,999 bytes | 未知（要解開壓縮檔才知道） | 3 | CC BY 4.0；可進 repo |
| JA-5 | 衆議院 沖縄及び北方問題に関する特別委員会 第3号（2026-06-29） | 審議中継 deli_id=56361；会議録 122103895X00320260629 | https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=56361&media_type=（串流）；https://kokkai.ndl.go.jp/txt/122103895X00320260629 | 串流，沒有檔案大小 | 49 分鐘（会議録涵蓋 45 分鐘） | 7 | 著作權法範圍內；只留本機 |

| 代號 | 選它的理由 | 標準答案要做什麼 |
|---|---|---|
| JA-1 | 超過 15 分鐘的長檔，測分段轉錄、掉尾與接續。《こころ》沒有一段超過 15 分鐘。 | 以青空文庫図書カード No.752 的文字起草，去掉ルビ與注記，對照錄音聽打校正。 |
| JA-2 | 換一位朗讀者。LibriVox 日文單人作品幾乎都是 ekzemplaro 朗讀。 | 以青空文庫 No.92 起草，對照錄音校正。 |
| JA-3 | 情緒語音與笑聲、啜泣等非語言聲，最接近 ASMR 與角色配音（#79）。Phrase-free 可以測模型會不會把非語言聲轉成文字。 | 台本就是底稿；Phrase-free 的非語言聲不在台本裡，要決定計分時納不納入。 |
| JA-4 | 唯一能進 repo 的日文多人自然對話，可以測說話者分離。 | 附的是羅馬字的方言記錄與標準語對譯，要換成漢字假名或重新聽打。 |
| JA-5 | 多人加長檔，標準日語；這是日文唯一同時符合兩個條件的片段。 | 会議録是整理過的紀錄，用詞約有 13% 不同 [S63]；要對照錄音校正，並刪掉開頭沒有紀錄的空白。 |

### 備選

- **台灣口音、多人、又能進 repo**：g0v 零時小學校的雙人對談（CC BY-SA 4.0）、國家文化記憶庫 286223 座談（CC BY 3.0 TW+，53:49）、VOA 專訪馬英九（標公有領域，14:07，2 人）[S38][S41][S53]。前兩者要先索取原始檔並自己聽打；VOA 要先釐清受訪者發言的權利。
- **公有領域的中文長檔**：《徬徨》〈祝福〉（Tina Ding，37:13）或〈孤獨者〉（52:52）[S49]。後者接近一小時，可以測更長的分段轉錄與接續。
- **台灣口音短句**：Common Voice zh-TW（只留本機）或科技大擂台 FLUD（可進 repo）[S23][S46]。
- **台灣議會，最接近逐字的紀錄**：新北市議會 2026-04-07 的質詢（只留本機）[S37]。
- **日文換聲音**：《青い時計台》（ryoko，9:58）、《羅生門》（dill，19:36）[S57]。

### 標準答案的處理

- **簡繁**：AliMeeting 與 AISHELL-4 的標準答案是簡體。#36 的工具在比對前做繁轉簡正規化，字形不成問題。判斷：用詞差異（如「软件」與「軟體」）不會被字形轉換抵銷；評測時要嘛關掉輸出端的用詞轉換，要嘛維護一份對照表。
- **贅詞與記號**：AISHELL-4 保留贅詞，速記錄、会議録與原著底稿多半刪掉了。同一個評測集內要用同一套規則，否則錯字率會反映的是聽打習慣，不是模型的差別。
- **人工的工作量**：AliMeeting 與 AISHELL-4 只要抽查；其他 8 段都要對照錄音聽打校正。

### 給 #99 的回歸檢查

#99 只要求 main 與 PR 對同一批音檔的輸出相同，不需要標準答案。判斷：全部 10 段加起來超過 4 小時音檔，每次 PR 都跑太久。可以只跑涵蓋多人、長檔與短檔的子集，例如 ZH-1（多人）、ZH-4 與 JA-1（長檔）、ZH-5 與 JA-3 的 Regular 子集（短檔）；全部 10 段留給 #15 的評測。

## 放進 repo 的規則

- **標準答案不是使用者聽打的**：每一段都要寫明是誰做的、是不是逐字、有沒有經過我們校正。
- **音檔大，官方又提供下載**：GitHub 對超過 50 MiB 的檔案會警告、超過 100 MiB 直接擋下，並建議 repo「ideally less than 1 GB」[S74]。AISHELL-4 與 AliMeeting 的官方管道只提供整包下載。
- **回歸檢查要求輸入完全相同**：#99 要比對 main 與 PR 的輸出，每段音檔都要能重建成同一個位元組序列。

### 建議的做法

1. **repo 只放清單與標準答案，不放音檔。**
   - 每一段寫一份清單：官方下載 URL、壓縮檔內的路徑、剪輯的起訖時間與聲道處理、轉檔參數，以及剪好的音檔的 SHA-256。
   - 評測工具照清單下載、剪輯，再核對 SHA-256；對不上就停下來。
   - 這樣不必散布音檔，也保證 main 與 PR 吃到同一個檔案。
2. **第三方的檔案另放一個目錄，不適用 repo 的 Apache-2.0。** 例如：

   ```
   evaluation_sets/
     README.md         這個目錄的檔案各有授權，不適用 Apache-2.0
     ATTRIBUTION.md    署名清單
     zh/<片段代號>/manifest.json, reference.txt
     ja/<片段代號>/manifest.json, reference.txt
   LICENSES/
     CC-BY-SA-4.0.txt ...
   ```

   目錄名稱照 GLOSSARY 的英文名稱 evaluation set。#36 的工具目前預設從 `lab/data/eval` 讀標準答案；公開素材的標準答案要放哪裡，由 #36 與 #37 決定。標準答案依素材的授權公開：
   - CC BY-SA 素材（AliMeeting、有聲維基百科、JVNV）：整理或校正過的標準答案是改作物，用 CC BY-SA 4.0 [S72]。
   - CC BY 素材（國語研方言錄音）：註明出處與修改即可。
   - 公有領域素材（LibriVox）：校正後的標準答案可以用 CC0。
   - 政府資料開放授權條款的文字（立法院公報）：照它附件的「顯名聲明」格式標示 [S71]。
3. **只留本機的素材，repo 裡只留識別碼。** 立法院 IVOD、國會審議影片、Common Voice，以及授權確認前的 AISHELL-4：repo 只記官方 URL、識別碼與 SHA-256，不放音檔、不放標準答案；PR 與 issue 只貼數字。這和 #15 Q4 對 rec17 的處理方向一致。
4. **NC 授權不進 repo。** 理由同 #79：ASF 把「Creative Commons Non-Commercial variants」列在 Category X [S73]，也和 ADR 0006 保留的商業化選項衝突。
5. **商業化之前重新盤點。** 「個人、非商業用途」與 NC 的素材，在專案真的商業化時要停用，或先取得權利人的書面同意。

### 署名清單的欄位

- 片段代號、官方頁 URL、下載 URL、取得日期。
- 作者或權利人、授權（SPDX 識別碼與授權連結）。
- 修改：剪輯起訖時間、聲道（例如 8 聲道取平均）、轉檔參數。CC BY 與 CC BY-SA 都要求註明修改 [S72]。
- 標準答案的來源與處理：資料集附的逐字稿、整理過的速記錄或原著文字；做過哪些正規化（簡繁、標點、數字、贅詞）；誰在何時校正。
- 音檔與標準答案各自的 SHA-256。

CC 授權允許「in any reasonable manner」滿足署名條件，例如連到載有這些資訊的頁面 [S72]，所以一份集中的署名清單就夠了。REUSE 規範提供機器可讀的寫法：授權全文放在 `LICENSES/`，無法加註解的檔案用同名的 `.license` 檔，或在目錄放 `REUSE.toml` [S75]；這不是必要條件。

## 與 ADR 和詞彙表的關係

- **ADR 0002**：兩種語言各有評測集，這份研究提供中文的素材與兩種語言的具體片段。沒有衝突。
- **ADR 0003**：「中文與日文各用哪個本機模型，依評測集的數據決定」。MOSS 的技術報告說 AISHELL-4 用在訓練與評測 [S10]。判斷：拿 AISHELL-4 比較 MOSS 與其他模型，MOSS 佔了見過同類資料的便宜；它適合當回歸檢查與「不准變差」的基準，選模型時要以 AliMeeting 與台灣素材為主。
- **ADR 0006**：NC 不進 repo。立法院 IVOD 的影音等同非商業授權，只留本機；AISHELL-4 在授權確認前也一樣。
- **GLOSSARY.md**：
  - 「標準答案」定義為「使用者親手聽打、作為比對基準的正確文字」。公開素材的標準答案由資料集作者製作，或以速記錄、原著文字為底稿。建議用 `/domain-modeling` 把定義改成「人工聽打並經使用者確認、作為比對基準的正確文字」，並在署名清單註明來源。
  - 「評測集」定義為「附有標準答案的一組短音檔」。這張要求至少一段超過 15 分鐘的長檔，用來測分段轉錄、掉尾與接續。建議定義裡拿掉「短」，或另外說明長檔的用途。

## 沒能查證的事

- **AISHELL-4**：擁有者為什麼、在哪一天改成 NC；Hugging Face 上 AISHELL 帳號是不是官方的；TextGrid 記號（`<sil>`、`<%>`、`<#>`、`<$>`、`<->`）的意義；`test.tar.gz` 裡有沒有頭戴麥克風的音檔。
- **AliMeeting**：每段的確切長度、TextGrid 的標記規則與簡繁、檔名裡 `MS###` 的意義。
- **立法院**：速記錄與錄音的逐字程度；開放資料平台的影片資訊資料集是否涵蓋影片本身；智慧局對議事錄影的函釋；「公報原始檔案」API 當天維護中，沒有讀到資料。
- **口音**：LibriVox 朗讀者的口音與性別；有聲維基百科的口音是自填的；國家文化記憶庫各件說的是哪種語言。
- **字幕與紀錄是否逐字**：g0v 零時小學校的人工字幕、總統府與 VOA 的問答全文、新北市議會的會議紀錄、憲法法庭筆錄，都沒有對照錄音。
- **VOA**：受訪者的發言是否也是公有領域；VOA 中文部 2025 年後的正式營運狀態（官方頁面互相矛盾）。
- **Common Voice**：在 repo 放少量片段算不算「re-host or re-share」；保守解讀是算。
- **其他台灣素材**：科技大擂台 FLUD 的朗讀者與科政中心對音檔的權利；臺大機器學習課程的授權；計算語言學學會是否願意以商用條件授權 MCDC8；政大口語語料庫官網的授權（網站暫停）。
- **JVNV**：檔案結構與台本格式只見於第三方程式碼；Phrase-free 的台本是否含非語言聲。
- **國語研方言錄音**：第 11 集壓縮檔裡各場面的檔名、長度、聲道數與文字檔格式。
- **國會**：審議中継的串流有沒有技術保護措施；院方影像是否屬於「映画の著作物」；49 分鐘影片與 45 分鐘会議録的對齊；参議院的整理規則。
- **明日への声**：哪一份條款優先；確切長度。
- **MOSS**：技術報告說 Podcast 與 Movies 兩個測試集會公開在 Hugging Face；查詢當天 OpenMOSS-Team 的資料集清單裡沒有 [S10]。

## 來源

全部在 2026-10-19 查詢。

**中國大陸的語料**

- **S1** OpenSLR SLR111 AISHELL-4（授權、檔案大小）：<https://www.openslr.org/111/>；`test.tar.gz` 的 HEAD：<https://openslr.elda.org/resources/111/test.tar.gz>
- **S2** 希爾貝殼 AISHELL-4 頁面：<https://www.aishelltech.com/aishell_4>（文字取自頁面腳本 `486048_zh-cn.html.Body.js?version=20261010183722`）
- **S3** Wayback Machine 存檔：擁有者頁面 2021-07-24（CC BY-SA 4.0）<https://web.archive.org/web/20210724050751/http://www.aishelltech.com/aishell_4>、2021-12-07（CC BY 4.0）<https://web.archive.org/web/20211207193344/http://www.aishelltech.com/aishell_4>、2022-08-11 起到 2026-05-15（Apache License v.2.0）<https://web.archive.org/web/20220811014652/http://www.aishelltech.com/aishell_4>、<https://web.archive.org/web/20260515/http://www.aishelltech.com/aishell_4>；OpenSLR 111 頁面 2021-07-05 <https://web.archive.org/web/20210705203022/https://www.openslr.org/111/>
- **S4** Fu et al., "AISHELL-4"（Interspeech 2021）：<https://arxiv.org/abs/2104.03603>
- **S5** Hugging Face AISHELL/AISHELL-4（卡片授權、逐段檔案、M_R003S02C01 與 S_R004S03C01 的 TextGrid）：<https://huggingface.co/datasets/AISHELL/AISHELL-4>
- **S6** AISHELL-4 基線程式（程式碼的 Apache-2.0、測試集 20 段的參考 STM）：<https://github.com/felixfuyihui/AISHELL-4>
- **S7** OpenSLR SLR119 AliMeeting（授權、規模、下載連結）：<https://www.openslr.org/119/>；壓縮檔的 HEAD：<https://speech-lab-share-data.oss-cn-shanghai.aliyuncs.com/AliMeeting/openlr/Eval_Ali.tar.gz>
- **S8** ModelScope AliMeeting（授權、`Eval_Ali.csv`、`Test_Ali.csv`）：<https://modelscope.cn/datasets/modelscope/AliMeeting>、<https://modelscope.cn/api/v1/datasets/modelscope/AliMeeting>
- **S9** Yu et al., "M2MeT"（ICASSP 2022）與挑戰賽總結：<https://arxiv.org/abs/2110.07393>、<https://arxiv.org/abs/2202.03647>；挑戰賽網頁的 Wayback 存檔（2022、2023）：<https://web.archive.org/web/2022*/https://www.alibabacloud.com/m2met-alimeeting>
- **S10** MOSS Transcribe Diarize Technical Report（v7，2026-07-17）：<https://arxiv.org/abs/2601.01554>；OpenMOSS-Team 的資料集清單：<https://huggingface.co/api/datasets?author=OpenMOSS-Team>
- **S11** ASCEND：<https://huggingface.co/datasets/CAiRE/ASCEND>、<https://arxiv.org/abs/2112.06223>
- **S12** FLEURS：<https://huggingface.co/datasets/google/fleurs>、<https://arxiv.org/abs/2205.12446>
- **S13** MagicData-RAMC：<https://www.openslr.org/123/>、<https://arxiv.org/abs/2203.16844>
- **S14** KeSpeech 授權（`dataset_license.md`）：<https://github.com/tzyll/KeSpeech>
- **S15** WenetSpeech：<https://wenet-e2e.github.io/WenetSpeech/>、<https://www.openslr.org/121/>、<https://arxiv.org/abs/2110.03370>
- **S16** OpenSLR 其他中文語料：<https://www.openslr.org/33/>、<https://www.openslr.org/93/>、<https://www.openslr.org/18/>、<https://www.openslr.org/38/>、<https://www.openslr.org/47/>、<https://www.openslr.org/62/>、<https://www.openslr.org/68/>、<https://www.openslr.org/138/>；AISHELL-2：<https://www.aishelltech.com/aishell_2>
- **S17** 其他語料：AISHELL-5 <https://www.openslr.org/159/>；MISP <https://mispchallenge.github.io/>；CS-Dialogue <https://huggingface.co/datasets/BAAI/CS-Dialogue>；Emilia <https://huggingface.co/datasets/amphion/Emilia-Dataset>；SpeechIO <https://github.com/SpeechColab/Leaderboard>
- **S18** YODAS 資料卡：<https://huggingface.co/datasets/espnet/yodas>

**台灣的學術語料與 Hugging Face**

- **S19** Formosa Speech in the Wild（NER 語料、FSR 挑戰賽）：<https://sites.google.com/nycu.edu.tw/fsw>
- **S20** 中華民國計算語言學學會語料目錄與授權書：<https://www.aclclp.org.tw/use_mat_c.php>、<https://www.aclclp.org.tw/use_mat.php>、<https://www.aclclp.org.tw/doc/>（`ner_trs_c.pdf`、`matbn_edu_agr_e.pdf`、`mcdc_agr_c.pdf`、`tcc300com_ag_c.pdf` 等）
- **S21** TalkBank 政大語料與使用規則：<https://talkbank.org/ca/access/TaiwanMandarin.html>、<https://talkbank.org/0share/rules.html>
- **S22** 中研院語言所口語語料：<https://tmc.ling.sinica.edu.tw>
- **S23** 科技大擂台 FLUD：<https://scidm.nchc.org.tw/dataset/grandchallenge>（API：<https://scidm.nchc.org.tw/api/3/action/package_show?id=grandchallenge>）；鏡像 <https://huggingface.co/datasets/MediaTek-Research/formosaspeech>
- **S24** 臺大機器學習 2021：<https://huggingface.co/datasets/ky552/ML2021_ASR_ST>、<https://huggingface.co/datasets/generative-fusion-decoding/ml-lecture-2021-long>、<https://arxiv.org/abs/2401.00273>
- **S25** Breeze-ASR-25：<https://huggingface.co/MediaTek-Research/Breeze-ASR-25>、<https://arxiv.org/abs/2506.11130>
- **S26** FormoSpeech 組織：<https://huggingface.co/spaces/formospeech/README>、<https://huggingface.co/datasets/formospeech/matbn>
- **S27** IVOD 衍生資料集：<https://huggingface.co/datasets/disco-eth/WorldSpeech>、<https://arxiv.org/abs/2605.09167>、<https://huggingface.co/datasets/lianghsun/ly-ivod-asr-zhtw>、<https://huggingface.co/datasets/openfun/ivod-fine-tune>、<https://huggingface.co/datasets/Luigi/ivod-zhtw-10min-maps>、<https://huggingface.co/datasets/FetchieAI/MinHeng_ivod>

**立法院、法院、議會與其他公部門**

- **S28** IVOD 著作權聲明：<https://ivod.ly.gov.tw/Copyright>
- **S29** IVOD 公告事項與常見問題：<https://ivod.ly.gov.tw/News>、<https://ivod.ly.gov.tw/Faq>
- **S30** IVOD 片段 155034 與發言紀錄：<https://ivod.ly.gov.tw/Play/Clip/1M/155034>、<https://ivod.ly.gov.tw/Demand/Speech/155034>
- **S31** 立法院會議錄影錄音管理規則（109-03-13）：<https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=A0030139>
- **S32** 立法院議事規則（105-11-11）：<https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=A0020059>
- **S33** 立法院組織法（112-12-27）：<https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=A0010044>
- **S34** 立法院網站資料開放宣告：<https://www.ly.gov.tw/Pages/List.aspx?nodeid=10772>
- **S35** 立法院開放資料服務平台：授權條款 <https://data.ly.gov.tw/principle.action>；公報原始檔案 <https://data.ly.gov.tw/getds.action?id=41>；委員發言片段相關影片資訊 <https://data.ly.gov.tw/getds.action?id=421>
- **S36** 憲法法庭與司法院：<https://cons.judicial.gov.tw/docdata.aspx?fid=2122>、<https://www.judicial.gov.tw/tw/cp-1327-84674-d8e05-1.html>、<https://cons.judicial.gov.tw/docdata.aspx?fid=89&cat=1>、<https://cons.judicial.gov.tw/docdata.aspx?fid=2204&id=351175>、憲法法庭錄音錄影及其利用保存辦法 <https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=A0020199>
- **S37** 地方議會：臺北 <https://www.tcc.gov.tw/cp.aspx?n=13900>；新北 <https://vod.ntp.gov.tw/VodCloudV2/>、<https://ntpbook.ntp.gov.tw/Home/BookAgenda/ViewRecord?cBookAgendaID=3b5d6acb-67fc-4356-9e92-19bffaf10d3c>；臺中 <https://vod.tccc.gov.tw/index.asp>；高雄 <https://www.kcc.gov.tw/cp.aspx?n=104>
- **S38** 國家文化記憶庫：<https://tcmb.culture.tw/zh-tw/license>、<https://tcmb.culture.tw/zh-tw/termsofuse>、<https://tcmb.culture.tw/zh-tw/FAQ/1780>、<https://tcmb.culture.tw/zh-tw/detail?indexCode=Culture_Media&id=286223>
- **S39** 總統府 <https://www.president.gov.tw/Page/18>；行政院 <https://www.ey.gov.tw/Page/2EADDBFEDDB6357E>；疾管署 <https://www.cdc.gov.tw/Category/Fpage/TxkBIR9agw_IBRRmvn9TcQ>、<https://www.cdc.gov.tw/Category/Fpage/rvmij-b1qdDYyX_Olv67VQ>
- **S40** 公共電視 <https://www.pts.org.tw/zh_tw/about/terms>；國家教育廣播電臺 <https://www.ner.gov.tw/Copyright/>；臺大開放式課程 <https://ocw.aca.ntu.edu.tw/about/copyright>；陽明交大開放式課程 <https://ocw.nycu.edu.tw/?openedu=copyright-declaration>
- **S41** g0v 零時小學校 <https://g0v.hackmd.io/@jothon/Sch001courses>；COSCUP 2025 徵稿 <https://blog.coscup.org/2025/02/coscup-2025-call-for-participation.html>；PyCon TW 錄影說明 <https://tw.pycon.org/2025/en-us/speaking/recording/>
- **S42** 中央廣播電臺授權辦法：<https://www.rti.org.tw/content?uid=24>
- **S43** archive.tw：<https://archive.tw/>

**Common Voice、LibriVox、維基與 VOA**

- **S44** MDC「Common Voice Scripted Speech 27.0 - Chinese (Taiwan)」與「- Chinese (China)」：<https://mozilladatacollective.com/datasets/cmu5wkw5i00c6o107jnm3t51u>、<https://mozilladatacollective.com/datasets/cmu5lcunh00qimh078sdd5so8>（授權與下載對話框的文字取自頁面原始碼）
- **S45** MDC Data Consumer Terms of Use（Last Updated: May 06, 2026）：<https://mozilladatacollective.com/terms/consumers>；FAQ：<https://community.mozilladatacollective.com/faq-why-cant-i-re-host-or-share-common-voice-datasets-that-i-download-from-mdc/>
- **S46** Common Voice 統計：<https://github.com/common-voice/cv-dataset>（`datasets/scripted-speech/cv-corpus-27.0-2026-09-11.json`、`datasets/spontaneous-speech/sps-corpus-5.0-2026-09-11.json`）
- **S47** LibriVox「Copyright, Public Domain & LibriVox」：<https://librivox.org/pages/public-domain/>
- **S48** LibriVox 搜尋（錄音語言中文 = 14、日文 = 35）與專案頁，例如 <https://librivox.org/the-true-story-of-ah-q-by-xun-lu/>、<https://librivox.org/wandering-by-xun-lu/>、<https://librivox.org/call-to-arms-by-xun-lu/>、<https://librivox.org/lao-can-you-ji-by-liu-o/>
- **S49** archive.org metadata API：<https://archive.org/metadata/truestoryahq_1612_librivox>、<https://archive.org/metadata/panghuang_1910_librivox>、<https://archive.org/metadata/call_to_arms_jl_librivox>、<https://archive.org/metadata/lao_can_you_ji_hc_librivox>
- **S50** Project Gutenberg 授權：<https://www.gutenberg.org/policy/license.html>；《阿Q正傳》<https://www.gutenberg.org/ebooks/25332>
- **S51** 中文維基文庫：Wikisource:版权信息 <https://zh.wikisource.org/wiki/Wikisource:%E7%89%88%E6%9D%83%E4%BF%A1%E6%81%AF>、作者:魯迅 <https://zh.wikisource.org/wiki/%E4%BD%9C%E8%80%85:%E9%AD%AF%E8%BF%85>、阿Q正傳 <https://zh.wikisource.org/wiki/%E9%98%BFQ%E6%AD%A3%E5%82%B3>
- **S52** 維基共享資源「Spoken Chinese Wikipedia」分類與 File:Zh-tw-小雁塔.ogg（Commons API 的 imageinfo 與檔案頁原始碼）：<https://commons.wikimedia.org/wiki/Category:Spoken_Chinese_Wikipedia>、<https://commons.wikimedia.org/wiki/File:Zh-tw-%E5%B0%8F%E9%9B%81%E5%A1%94.ogg>
- **S53** File:VOA專訪馬英九200603.webm 與原網頁：<https://commons.wikimedia.org/wiki/File:VOA%E5%B0%88%E8%A8%AA%E9%A6%AC%E8%8B%B1%E4%B9%9D200603.webm>、<https://www.voachinese.com/a/a-21-w2006-03-27-voa37-57839972/1059121.html>
- **S54** VOA 使用條款：<https://www.voanews.com/p/5338.html>、<https://www.voachinese.com/p/3874.html>
- **S55** USAGM 新聞稿（2025-03-15）：<https://www.usagm.gov/2025/03/15/u-s-agency-for-global-media-complies-with-presidential-executive-order-to-reduce-the-federal-bureaucracy/>

**日文**

- **S56** JVNV corpus：<https://sites.google.com/site/shinnosuketakamichi/research-topics/jvnv_corpus>；壓縮檔的 HEAD：<https://ss-takashi.sakura.ne.jp/corpus/jvnv/jvnv_ver1.zip>；論文 <https://arxiv.org/abs/2310.06072>
- **S57** LibriVox 日文：<https://librivox.org/botchan-by-soseki-natsume-2/>、<https://librivox.org/kokoro-by-soseki-natsume/>、<https://librivox.org/librivox-multilingual-short-works-collection-001-by-various/>、<https://librivox.org/multilingual-short-works-collection-009-by-various/>；archive.org metadata：<https://archive.org/metadata/botchan_1310_librivox>、<https://archive.org/metadata/mshortworks_001_1202_librivox>、<https://archive.org/metadata/multilingual_short_works_collection_009_1310_librivox>
- **S58** 青空文庫「収録ファイルの取り扱い規準」：<https://www.aozora.gr.jp/guide/kijyunn.html>；図書カード <https://www.aozora.gr.jp/cards/000148/card752.html>、<https://www.aozora.gr.jp/cards/000879/card92.html>
- **S59** 衆議院インターネット審議中継：<https://www.shugiintv.go.jp/jp/index.php?ex=CR>；参議院インターネット審議中継：<https://www.webtv.sangiin.go.jp/webtv/howto.php>
- **S60** 衆議院：<https://www.shugiin.go.jp/internet/itdb_annai.nsf/html/statics/link.html>；参議院：<https://www.sangiin.go.jp/jpn/footer/chosaku.html>
- **S61** 国会会議録検索システム：<https://kokkai.ndl.go.jp/api.html>、<https://kokkai.ndl.go.jp/help.html>
- **S62** 衆議院規則：<https://www.shugiin.go.jp/internet/itdb_annai.nsf/html/statics/shiryo/dl-rules.htm>；参議院規則：<https://www.sangiin.go.jp/jpn/shiryo/houki/03saninkisoku/kisoku.html>
- **S63** Kawahara, "Transcription System Using Automatic Speech Recognition for the Japanese Parliament (Diet)"（IAAI 2012）：<https://ojs.aaai.org/index.php/AAAI/article/view/18962>；Kawahara, Ueno & Morikawa（Tiro 2020）：<https://tiro.intersteno.org/2020/05/transcription-system-using-automatic-speech-recognition-in-the-japanese-parliament/>
- **S64** 日本 著作権法（e-Gov 法令 API）：<https://laws.e-gov.go.jp/api/1/lawdata/345AC0000000048>；国会法：<https://laws.e-gov.go.jp/api/1/lawdata/322AC1000000079>
- **S65** 衆議院 沖縄及び北方問題に関する特別委員会 第3号（2026-06-29）：<https://www.shugiintv.go.jp/jp/index.php?ex=VL&deli_id=56361&media_type=>、<https://kokkai.ndl.go.jp/txt/122103895X00320260629>、<https://kokkai.ndl.go.jp/api/meeting?issueID=122103895X00320260629&recordPacking=json>
- **S66** 國立國語研究所「方言録音資料シリーズ」：<https://mmsrv.ninjal.ac.jp/hogenrokuon_siryo/>；第 11 集書冊 PDF：<https://repository.ninjal.ac.jp/record/3047/files/kk_hgrs_011.pdf>
- **S67** File:Kyoto_women_conversation_in_1964.ogg：<https://commons.wikimedia.org/wiki/File:Kyoto_women_conversation_in_1964.ogg>
- **S68** 政府広報「明日への声」vol.111 第 2 軌與條款：<https://www.gov-online.go.jp/media/cd/202609/202609_02.html>、<https://www.gov-online.go.jp/tos/>、<https://www.gov-online.go.jp/tos/content_rules/>

**法規、授權與其他**

- **S69** 台灣 著作權法（修正日期：民國 111 年 06 月 15 日）：<https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=J0070017>
- **S70** 中華人民共和國著作權法（2020 年修正），WIPO Lex：<https://www.wipo.int/wipolex/zh/legislation/details/21065>
- **S71** 政府資料開放授權條款－第1版：<https://data.gov.tw/license>
- **S72** CC BY-SA 4.0 Legal Code：<https://creativecommons.org/licenses/by-sa/4.0/legalcode.en>
- **S73** ASF 3rd Party License Policy：<https://www.apache.org/legal/resolved.html>
- **S74** GitHub「About large files on GitHub」：<https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github>
- **S75** REUSE Specification 3.3：<https://reuse.software/spec-3.3/>
