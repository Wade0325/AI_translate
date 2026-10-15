# Gemini API 免費層與付費層的資料使用條款

研究票 #81，查的是 #16 Q6 的前置問題：使用者用自己的 API 金鑰、透過 Gemini 引擎轉錄私人音檔時，Google 怎麼使用送出的音檔、提示詞與回應。

- 查詢日期：2026-10-15，所有來源都在這天讀取。
- 只引用 Google 的第一手頁面，引文保留英文原文。段落後面的 [Sn] 連到該頁，並對到文末〈來源〉表，那裡列出網址、頁面上標示的日期與查詢日期。
- 範圍：Gemini Developer API 與 Google AI Studio 的條款。app 用 `genai.Client(api_key=...)` 呼叫 Gemini Developer API（`backend/app/provider/google/gemini.py`）。Vertex AI（Gemini Enterprise Agent Platform）是另一套條款，不在範圍內。
- 用詞：「免費層」指條款的 Unpaid Services（定價頁的 Free Tier），「付費層」指 Paid Services（Paid Tier）。
- 這是條款整理，不是法律意見。標「推論」的地方是我從條文推出來的，條文沒有逐字寫。

## 短答

| | 免費層 | 付費層 | 在 EEA、瑞士、英國用免費層 |
|---|---|---|---|
| 拿去改善產品、開發機器學習技術 | 會 [S1] [S4] | 不會 [S1] [S4]，例外見 §2 | 不會，套用付費層的資料條款 [S1] |
| 人工審閱 | 為了品質與改善產品，審閱者可能讀取、標註輸入與輸出；審閱前先和帳號、金鑰、專案脫鉤 [S1]。濫用監控的人工檢視也適用 [S6] | 不為改善產品審閱；被濫用偵測標記的內容，可能由授權員工檢視 [S6] | 同付費層 [S1] [S6] |
| Google 保存多久 | 濫用監控同樣 55 天 [S6]；用於改善產品的資料，條款沒寫期限 [S1] [S19] | 為了偵測濫用保存 55 天 [S6]；條款本身只寫「a limited period of time」[S1] | 同付費層 |
| 處理依據 | Google 隱私權政策 [S1] | 資料處理附約（DPA）[S1] [S18] | 同付費層 |
| Batch API、Flex | 不提供 [S4] | 可用，定價表標示不用於改善產品 [S4] | — |

濫用監控的 55 天不分層：監控頁的適用範圍是整個 Gemini API 與 AI Studio，沒有區分兩層 [S6]。另外，Files API 上傳的檔案 48 小時後自動刪除 [S10]，Batch API 的結果預設保存 6 週 [S11]，這兩項和濫用監控的保存是分開的（見 §4）。

## 1. 金鑰屬於哪一層，看專案的計費狀態

- 條款的定義：免費層是「Any Services that are offered free of charge like direct interactions with Google AI Studio or unpaid quota in Gemini API」；Gemini API 只有在「accessing the API through a Cloud Project associated with an active billing account」時才算付費層 [S1]。
- 金鑰本身沒有層級設定：「They have no independent billing settings; they inherit the tier limits and billing status of the project.」[S5]
- 使用者可以在 AI Studio 的 Projects 頁看層級：「you'll be able to see your project's tier and billing plan under the Billing Tier column」[S5]。
- 預付餘額用完時，服務會停止，不會自動退回免費層：「Your projects aren't automatically downgraded to the Free Tier.」要回到免費層，得把專案和計費帳戶解除連結 [S5]。
- 計費頁把「不拿去改善產品」列為升級付費層的理由之一：「ensure your prompts and responses are not used to improve Google products」[S5]。

本次讀過的頁面都只指向 AI Studio 的 Projects 頁，沒有提到用 API 判斷金鑰層級的方法。app 現在讀的 `x-gemini-service-tier` 回應 header，程式註解記載的值是 flex、standard、priority，看不出免費或付費（`backend/app/provider/google/gemini.py`）。

### 條款版本

- 現行版「Effective March 23, 2026」[S1]。和前一版（Effective December 18, 2025）[S3] 相比，資料使用的段落只改了付費層記錄的用途：從「solely for the purpose of detecting violations of the Prohibited Use Policy」改成「solely for detecting and preventing violations of the Prohibited Use Policy to maintain the safety and security of the Services」。免費層的用途、人工審閱與 EEA 條款都沒變。
- 存檔頁列了 17 個舊版，其中 2025 年的有 8 個 [S2]。
- 搜尋引擎會帶出 `https://ai.google.dev/gemini-api/terms_preview`，那頁顯示的是「Effective December 13, 2024」的舊版，不是即將生效的新條款，不要引用。

## 2. 會不會拿去改善產品、訓練模型

### 免費層：會

- 「Google uses the content you submit to the Services and any generated responses to provide, improve, and develop Google products and services and machine learning technologies」[S1]
- 授權範圍明確包含檔案：「(e.g., prompts, including associated system instructions, cached content, and files such as images, videos, or documents)」[S1]
- 定價頁的免費卡片寫「Content used to improve our products」，各模型表格「Used to improve our products」那一列，免費層是 Yes [S4]。app 清單裡有免費層的模型都是如此：gemini-2.5-flash、gemini-2.5-pro，以及 gemini-3.5-flash 實際導向的 gemini-3.6-flash [S4] [S15]。
- 條款用的詞是 improve、develop，沒有逐字寫 train。不過 Google 在說明「依免費層條款處理」的 dataset 時，寫的是「including improving and training our models」[S8]。

### 付費層：不會

- 「Google doesn't use your prompts (including associated system instructions, cached content, and files such as images, videos, or documents) or responses to improve our products」，並依資料處理附約（DPA）處理 [S1]。DPA 的服務清單列有「Gemini API Paid Services」，處理的是「Personal data processed by Gemini API Paid Services in submitted prompts and responses to those prompts.」[S18]
- 定價頁的付費卡片寫「Content not used to improve our products」，表格的付費層欄是 No [S4]。

### 付費層的三個例外

1. **Contributor Tier**：邀請制的私人預覽（「invite-only private preview」），以最多 50% 的 token 折扣換取資料使用權：「By enabling the Contributor Tier for a project, your data from participating model use in your project will be used in accordance with our terms for "Unpaid Services."」[S8] 定價表的 Contributor 那一欄，付費層標 Yes [S4]。支援的模型包含 app 清單裡的 gemini-3.1-pro-preview [S8]。
2. **主動分享給 Google 的 dataset**：付費專案可以把 AI Studio 的 logs 存成 dataset 分享給 Google，分享出去的部分依免費層條款處理 [S8]。
3. **濫用監控的記錄**：「It is not used to train or fine-tune any AI/ML models besides those used specifically for policy enforcement.」[S6] 條文排除的只是政策執法以外的模型；推論：這些記錄可能被拿來訓練政策執法用的模型。

### API 條款的授權

Google APIs Terms of Service 對兩層都要求授權，用途是「to provide, secure, and improve the APIs」，授權是「perpetual, irrevocable, worldwide, sublicensable, royalty-free, and non-exclusive」[S16]。同一份條款也寫明，和附加條款衝突時以附加條款為準（「the additional terms will control for that conflict」）[S16]。依這條，付費層「不用於改善產品」的承諾優先於這裡的 improve。

這份條款還要求送出內容的人先取得必要權利（「including the necessary rights from your end users」）[S16]。推論：會議錄音裡有其他人的聲音，取得權利是送出音檔的使用者的責任。

## 3. 會不會有人工審閱

- **免費層**：「To help with quality and improve our products, human reviewers may read, annotate, and process your API input and output.」審閱前會「disconnecting this data from your Google Account, API key, and Cloud project」[S1]。條款緊接著要求「Do not submit sensitive, confidential, or personal information to the Unpaid Services.」[S1]
- **兩層都有：濫用監控**。監控頁的適用範圍是「the use of the Gemini API and AI Studio」，沒有區分兩層 [S6]。
  - 自動偵測會掃描違規，例如「hate speech, harassment, sexually explicit content, and dangerous content」[S6]。
  - 被標記的內容，「authorized Google employees may assess the flagged content」；持續有可疑活動的專案，「may be flagged for manual review by authorized Google personnel」[S6]。
- **付費層**：沒有為了改善產品的人工審閱。分享出去的 dataset 例外：「human reviewers may read, annotate, and process the API inputs and outputs you share」[S8]。

和 ASMR 有關的推論：禁止使用政策把「Sexually explicit content -- for example, content created for the purpose of pornography or sexual gratification」列為不得產生或散布的內容 [S20]。轉錄成人向 ASMR 算不算違反，條文沒有直接回答；但自動偵測的掃描類別包含 sexually explicit content，所以這類音檔不論哪一層都可能被標記，進入人工檢視。

## 4. 會保存多久

| 資料 | 保存期間 | 適用 | 來源 |
|---|---|---|---|
| 濫用監控：提示詞（頁面寫「The text prompts」）、隨提示詞附上的上下文、回應 | 55 天 | 整個 Gemini API 與 AI Studio，沒有區分兩層 | [S6] |
| 免費層用於改善產品的資料 | 條款沒寫；隱私權政策只說依資料種類、用途與設定而定 | 免費層 | [S1] [S19] |
| Files API 上傳的檔案 | 48 小時後自動刪除，可提前手動刪除 | 兩層 | [S10] [S7] |
| Batch API 的結果 | 預設 6 週後永久刪除；pending 或 running 超過 48 小時的 batch job 會過期 | 只有付費層能用 | [S11] [S4] |
| AI Studio 的 logs | 預設最長 55 天，可改成 7、14、28 天；存成 dataset 的不會過期。generateContent 預設不存，要逐筆或在專案層級開啟 | 只有付費專案 | [S9] [S8] |
| 隱含快取 | 只在記憶體、依專案隔離、24 小時 TTL | 預設開啟 | [S7] |
| Interactions API（app 沒用） | 預設會存：付費層 55 天、免費層 1 天；`store=false` 可關 | — | [S13] |
| 以 Google 搜尋或地圖建立依據（app 沒用） | 30 天，無法關閉 | — | [S1] [S7] |

其他和保存有關的條文：

- 付費層的資料「may be stored transiently or cached in any country in which Google or its agents maintain facilities」[S1]。
- Developer API 不保證零資料保留：「If your workload requires guaranteed zero data retention or enterprise data processing agreements, use Vertex AI.」[S7]
- AI Studio 的 logs 和濫用監控的記錄是兩回事：「These logs which are private to your Google Cloud project are separate from any logs held solely for abuse monitoring purposes.」[S8]
- 付費層適用的 DPA 規定：服務本身有刪除功能、而且使用者用它刪了資料時，「Google will delete such Partner Personal Data from its systems as soon as reasonably practicable, unless applicable laws require storage」[S17]。這是通用條文，沒有說它和濫用監控的 55 天怎麼互動。

## 5. Files API、Batch API 與 Flex

- **Files API**：兩層的資料範圍都寫進了「files such as images, videos, or documents」[S1]。音檔沒有被點名，但 such as 是舉例；推論：上傳的音檔依所屬的層處理。檔案 48 小時後自動刪除 [S10]。檔案儲存和濫用監控的記錄是兩回事：「Usage of the File API is independent of ZDR logging; users must manually delete files to ensure a zero-data footprint.」[S7]
- **Batch API**：各模型定價表的免費層欄寫 Not available，付費卡片也把「Batch API (50% cost reduction)」列為付費功能 [S4]。所以送進 Batch API 的請求一定是付費層，定價表標示不用於改善產品 [S4]。結果預設保存 6 週 [S11]。刪除 batch job 時，頁面只寫「it stops processing new requests and is removed from the list of batch jobs」，沒有說結果會不會一起刪 [S11]。AI Studio 的 logs 也支援 BatchGenerateContent [S9]。零資料保留那頁沒有提到 Batch API [S7]。
- **Flex**：定價表的免費層欄同樣是 Not available [S4]，Flex 說明頁沒有另外的資料條款 [S12]。

對 app 來說：

- 處理模式選批次時，送出的一定是付費層的請求：免費層沒有 Batch API [S4]，而 app 建立 batch job 失敗時不會改用其他方式送出（`backend/app/tasks/batch_core.py`）。
- 選 Flex 則不一定。層級看的是金鑰所屬專案的計費狀態（§1），不是處理模式；免費層沒有 Flex [S4]，而 app 在 Flex 失敗時會改用標準重送一次（`backend/app/provider/google/gemini.py`）。所以免費層金鑰選 Flex，最後送出的是免費層的標準請求（推論：免費層的 Flex 請求會失敗）。這個改送是 app 自己做的；Google 端在 Flex 容量滿時不會自動改用標準（「No server-side fallback」）[S12]。

## 6. 地區差異

- **EEA、瑞士、英國**：「If you're in the European Economic Area, Switzerland, or the United Kingdom, the terms under "How Google uses Your Data" in "Paid Services" apply to all Services, including Google AI Studio and unpaid quota in the Gemini API, even though they are offered free of charge.」[S1]
- 同樣這三地：「You may use only Paid Services when making API Clients available to users in the European Economic Area, Switzerland, or the United Kingdom.」[S1] 在自備金鑰的模式下，誰算「making API Clients available」，條文沒有直接說，要由維護者判斷。
- 計費 FAQ 說這三地也有免費層（「Yes, we make the free tier and paid tier available in many regions.」）[S5]。
- 分享 dataset 的選項「Options are dependent on your location.」[S8]
- 只能在可用地區使用：「You may only access the Services (or make API Clients available to users) within an available region.」[S1] 可用地區清單有台灣、日本，沒有香港、澳門與中國大陸 [S14]。
- 條款沒有說明怎麼判定使用者「在」這三地。

## 7. 和 app 的關係

### app 現況

依 2026-10-15 的 `origin/main`（d3e617f）：

- 標準與 Flex：先用 Files API 上傳，再呼叫 `generate_content`（Flex 失敗時改用標準重送一次，見 §5）；任務結束時呼叫 `files.delete`（`backend/app/provider/google/gemini.py`、`backend/app/services/transcription/flows.py`）。上傳時的 `display_name` 是送出那個檔案的檔名去掉副檔名；暫存檔保留原檔名，去靜音後的檔名也沿用它，所以原檔名會一起送到 Google（`backend/app/api/upload.py`、`backend/app/utils/audio.py`、`backend/app/services/vad/flows.py`）。
- 批次：同樣先上傳，再用 Batch API 送出；結束時刪除上傳的檔案，但後端沒有呼叫 `batches.delete`。依 [S11]，轉錄結果預設會在 Google 端留 6 週（`backend/app/tasks/batch_core.py`）。
- 沒有用 Google 搜尋依據、明確快取或 Interactions API，也沒有設定 `store`。
- 模型清單（`frontend/src/constants/modelConfig.js`）：gemini-3.5-flash、gemini-3.1-pro-preview、gemini-2.5-flash、gemini-2.5-pro。gemini-3.1-pro-preview 沒有免費層，也是 Contributor Tier 支援的模型 [S4] [S8]。

### 給 #16 Q6 的參考（推論，由維護者決定）

1. 免費層和 app 的用途正面衝突：條款要求「Do not submit sensitive, confidential, or personal information to the Unpaid Services.」[S1]，而 app 處理的是會議、ASMR 這類私人音檔。要在 Settings 或模型選單放說明的話，這句最需要讓使用者看到。
2. 層級由金鑰所屬專案的計費狀態決定 [S1] [S5]，app 目前沒有判斷的方法（§1）。說明文字只能請使用者自己到 AI Studio 的 Projects 頁看 Billing Tier。
3. 付費層也不是零保留：濫用監控保存 55 天 [S6]，Developer API 不保證零資料保留 [S7]。「付費就不留資料」是錯的說法，介面文字要避開。
4. 條款常改（§1），說明文字最好連到條款原文，不要把條文抄進介面。
5. 條款規定使用者要滿 18 歲，而且「Use of Google AI Studio and Gemini API is for developers building with Google AI models for professional or business purposes, not for consumer use.」[S1] 自備金鑰的使用者要自己接受這份條款；README 要不要提醒，由維護者決定。

### 可以另開 ticket 的改動（本研究不處理）

- 批次的結果寫進資料庫後，呼叫 `batches.delete`。動手前要先確認刪除 batch job 會不會連結果一起刪：[S11] 只寫 job 會從清單移除。
- 在 `generate_content` 明確設 `store=False`，避免使用者在 AI Studio 開了專案層級 logs 時被存下來。[S9] 把專案設定稱為「the default storage behavior for a project」，暗示逐筆設定可以覆寫，但沒有明講。另外，app 釘選的 google-genai 2.6.0，`GenerateContentConfig` 沒有 `store` 欄位（2026-10-15 在主 checkout 的 `backend/.venv` 檢查），要先升級 SDK 或另找做法。

## 8. 文件沒寫清楚的地方

- 免費層用於改善產品的資料保存多久。
- 刪除 Files API 的檔案後，濫用監控記錄裡的內容會不會一起刪；[S7] 只說兩者互相獨立。
- 濫用監控是否記錄音檔本身：[S6] 列的是「Prompts: The text prompts you submit to the API.」、「Contextual Information: Any additional context you provide with your prompts.」與「Output」。音檔應屬後者，但沒有逐字寫出。
- 刪除 batch job 會不會一起刪除結果。
- 怎麼判定使用者「在」EEA、瑞士或英國。
- Contributor Tier 怎麼啟用：[S8] 寫的是「By enabling the Contributor Tier for a project」，受邀者「will be invited by email and see a callout in AI Studio」。從用語看要專案端主動啟用，但頁面沒有說明流程。

## 9. 順帶發現（不屬本題）

- gemini-3.5-flash 已經不是獨立的模型：「the endpoint is not shutting down and automatically routes API requests to gemini-3.6-flash」[S15]。定價頁也沒有 gemini-3.5-flash 這一節 [S4]，所以它的資料條款要看 gemini-3.6-flash 那一列。
- 2.5 系列只開放給用過的人：「we are limiting access to the 2.5 models to users who have actively used them in the past」[S15]。README 推薦的預設模型 gemini-2.5-flash，新使用者可能用不了。

## 來源

「頁面日期」照抄頁面上的標示：條款類寫生效日或修改日；ai.google.dev 的文件頁沒有生效日，只有頁尾的「Last updated」。內文的 [Sn] 可以直接點到該頁。

| 代號 | 頁面 | 網址 | 頁面日期 | 查詢日期 |
|---|---|---|---|---|
| S1 | Gemini API Additional Terms of Service | <https://ai.google.dev/gemini-api/terms> | Effective March 23, 2026（Last updated 2026-04-28 UTC） | 2026-10-15 |
| S2 | Additional Terms of Service archive | <https://ai.google.dev/gemini-api/terms-archive> | Last updated 2026-04-28 UTC | 2026-10-15 |
| S3 | Gemini API Additional Terms of Service（前一版） | <https://ai.google.dev/gemini-api/terms-archive/terms_12_18_25> | Effective December 18, 2025 | 2026-10-15 |
| S4 | Gemini Developer API pricing | <https://ai.google.dev/gemini-api/docs/pricing> | Last updated 2026-10-14 UTC | 2026-10-15 |
| S5 | Billing | <https://ai.google.dev/gemini-api/docs/billing> | Last updated 2026-09-28 UTC | 2026-10-15 |
| S6 | Abuse monitoring | <https://ai.google.dev/gemini-api/docs/usage-policies> | Last updated 2026-06-09 UTC | 2026-10-15 |
| S7 | Zero data retention in the Gemini Developer API | <https://ai.google.dev/gemini-api/docs/zdr> | Last updated 2026-09-14 UTC | 2026-10-15 |
| S8 | Data logging and sharing | <https://ai.google.dev/gemini-api/docs/logs-policy> | Last updated 2026-10-14 UTC | 2026-10-15 |
| S9 | Logs and datasets | <https://ai.google.dev/gemini-api/docs/logs-datasets> | Last updated 2026-09-23 UTC | 2026-10-15 |
| S10 | Files API | <https://ai.google.dev/gemini-api/docs/files> | Last updated 2026-10-14 UTC | 2026-10-15 |
| S11 | Batch API | <https://ai.google.dev/gemini-api/docs/batch-api> | Last updated 2026-09-17 UTC | 2026-10-15 |
| S12 | Flex inference | <https://ai.google.dev/gemini-api/docs/flex-inference> | Last updated 2026-10-13 UTC | 2026-10-15 |
| S13 | Interactions API | <https://ai.google.dev/gemini-api/docs/interactions-overview> | Last updated 2026-10-13 UTC | 2026-10-15 |
| S14 | Available regions for Google AI Studio and Gemini API | <https://ai.google.dev/gemini-api/docs/available-regions> | Last updated 2026-04-28 UTC | 2026-10-15 |
| S15 | Gemini deprecations | <https://ai.google.dev/gemini-api/docs/deprecations> | Last updated 2026-10-12 UTC | 2026-10-15 |
| S16 | Google APIs Terms of Service | <https://developers.google.com/terms> | Last modified: November 9, 2021 | 2026-10-15 |
| S17 | Google Data Processing Addendum for Products Where Google is a Data Processor | <https://business.safety.google/processorterms/> | Version 10, 7 May 2026 | 2026-10-15 |
| S18 | Google Data Protection Terms - Service Information | <https://business.safety.google/services/> | Last update: 27 April 2026 | 2026-10-15 |
| S19 | Google Privacy Policy | <https://policies.google.com/privacy> | Effective October 1, 2026 | 2026-10-15 |
| S20 | Generative AI Prohibited Use Policy | <https://policies.google.com/terms/generative-ai/use-policy> | Last Modified: December 17, 2024 | 2026-10-15 |

[S1]: https://ai.google.dev/gemini-api/terms
[S2]: https://ai.google.dev/gemini-api/terms-archive
[S3]: https://ai.google.dev/gemini-api/terms-archive/terms_12_18_25
[S4]: https://ai.google.dev/gemini-api/docs/pricing
[S5]: https://ai.google.dev/gemini-api/docs/billing
[S6]: https://ai.google.dev/gemini-api/docs/usage-policies
[S7]: https://ai.google.dev/gemini-api/docs/zdr
[S8]: https://ai.google.dev/gemini-api/docs/logs-policy
[S9]: https://ai.google.dev/gemini-api/docs/logs-datasets
[S10]: https://ai.google.dev/gemini-api/docs/files
[S11]: https://ai.google.dev/gemini-api/docs/batch-api
[S12]: https://ai.google.dev/gemini-api/docs/flex-inference
[S13]: https://ai.google.dev/gemini-api/docs/interactions-overview
[S14]: https://ai.google.dev/gemini-api/docs/available-regions
[S15]: https://ai.google.dev/gemini-api/docs/deprecations
[S16]: https://developers.google.com/terms
[S17]: https://business.safety.google/processorterms/
[S18]: https://business.safety.google/services/
[S19]: https://policies.google.com/privacy
[S20]: https://policies.google.com/terms/generative-ai/use-policy
