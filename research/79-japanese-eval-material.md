# 研究：日文評測素材的來源與授權

回答 #79，也就是 #15 的 Q1。

> 所有連結都在 2026-10-15 查詢。引用處標 [S 編號]，對應文末的來源清單。
> 這份筆記整理授權原文、法條與官方頁面，不是法律意見。標「判斷」的是我從原文推論的結論，標「未查證」的是沒能從第一手資料確認的事。

## 結論

- **能放進 repo、又最接近 ASMR 與角色配音語感的公開素材，只有 JVNV。** 授權是 CC BY-SA 4.0。內容是 4 位說話者、6 種情緒的語音，含笑聲、啜泣等非語言聲音，共 3.94 小時 [S2]。要署名、附授權連結並註明修改 [S34]；剪出來的片段和它的標準答案，都維持 CC BY-SA 4.0。
- **測長檔（分段轉錄、掉尾、接續）可以用 LibriVox 的日文有聲書。** 錄音捐入公有領域，LibriVox 說可以任意使用、不必取得許可 [S4]。錄音語言是日文的有 127 筆 [S5]，例如長 8 小時 46 分的《こころ》[S6]。原文多半來自青空文庫，著作權已消滅的作品檔案可以自由複製與改作 [S7]，可以拿來起草標準答案，再對照錄音聽打校正。
- **耳語只有 JVS 的 whisper10 有，但只能留本機。** JVS 有 100 位專業說話者，每人錄了 10 句耳語 [S1]。音檔只限學術研究、非商用研究與個人使用，並且禁止再散布；頁面只允許在網頁或部落格公開約 10 句 [S1]。要放進 repo 或用於商業用途，要先寫信問作者。
- **影音字幕類的合法來源是 YODAS／YODAS2，但只建議留本機。** 這是 YouTube 上標 CC 的影片，授權 CC BY 3.0；日文有手動字幕 1,094 小時、自動字幕 2,930 小時 [S12][S13]。本機評測沒有問題，可是資料集不保留 YouTube 影片 ID [S13]；我抽查的 9 部影片全部查不到 [S15]，無法回溯創作者，也無法自己確認授權。
- **Common Voice 日文雖然是 CC0，下載條款卻禁止再散布，也禁止嘗試識別說話者** [S17][S18]，所以只能留本機。而且它是平均 4.5 秒的短句朗讀 [S19]，離 ASMR 很遠。
- **市售 ASMR（以 DLsite 為例）只能留本機，最好先取得社團的書面許可。**
  - DLsite 規約只給使用者「利用權」，並禁止「予定されている利用態様」以外的複製與改變 [S29]。
  - 日本著作權法第 30 條之 4（技術開發或實用化的試驗）可能適用 [S30]。但文化庁的整理是利用行為發生在日本時適用日本法 [S31]，維護者不在日本時未必適用；而且這條不處理違反契約的問題。
  - 台灣現行法沒有對應的專門條款，只能依第 51、65 條個案判斷 [S32]。
- **自己錄製或委託錄製，是唯一能同時貼近 ASMR（耳語、雙耳錄音）又能公開的做法。** 要取得說話者的錄音同意與腳本的權利 [S30 第 91 條][S32 第 22 條]，並請對方以 CC BY 4.0 或 CC0 授權，才能進 repo。
- **不要用：**
  - ReazonSpeech：電視節目，限著作權法第 30 條之 4 的情報解析 [S20]。
  - J-CHAT：CC BY-NC 4.0，而且同樣限第 30 條之 4 的用途 [S21]。
  - Emilia：CC BY-NC 4.0，另有免責賠償條款 [S16]。
  - Hugging Face 上的 ASMR 存檔與動畫、視覺小說遊戲的語音資料集：卡片沒有出示權利人授權 [S42][S43]。
  - JTubeSpeech：只有影片 ID，下載違反 YouTube 條款 [S41][S38]。
  - 青空朗読：錄音保有著作鄰接權，禁止複製 [S46]。
- **政府內容的授權最寬，但拿不到合適的檔案。** 公共データ利用規約 PDL1.0 可以依 CC BY 4.0 使用 [S25]，可是政府広報オンライン不允許下載影片 [S27]；唯一能下載的「明日への声」MP3 限非營利使用 [S28]，只能留本機。
- **放進 repo 的素材要另放一個目錄，附各自的授權與署名清單。** Apache-2.0 只涵蓋專案自己的程式碼。NC（非商業）授權的素材不進 repo：Apache 軟體基金會把 CC NC 列在 Category X [S37]，也和 ADR 0006 保留的商業化選項衝突。

### 對照 #15 Q1 的四個選項

| #15 的選項 | 查到的狀況 |
|---|---|
| 市售 ASMR 作品 | 最貼近用途，但平台規約限制複製與改變 [S29]，法定例外是否適用不確定 [S30][S31][S32]。取得社團的書面許可後只留本機，公開時只附數字。 |
| 自己錄製的素材 | 權利最乾淨，可以指定耳語、雙耳錄音；要自己控制錄音條件，才不會和真實作品差太遠。 |
| 授權明確的素材 | 能公開又夠貼近的只有 JVNV；LibriVox 適合長檔測試；耳語的 JVS 不能公開；影音類的 YODAS 無法回溯創作者。 |
| 經同意的他人錄音 | 要取得錄音同意（表演人的錄音權 [S30 第 91 條][S32 第 22 條]）、寫清楚能不能公開；要進 repo 就請對方以 CC BY 4.0 或 CC0 授權。 |

## 判斷「進 repo」或「留本機」的三道關卡

1. **著作權授權允不允許再散布。** CC0、公有領域、CC BY、CC BY-SA 都允許重製與散布 [S33][S34]；NC 限非商業用途 [S36]；「研究用、禁止再散布」之類的自訂授權不允許。
2. **取得管道的契約有沒有另外禁止。** 授權允許，不代表下載平台允許。Common Voice 是 CC0，但 Mozilla Data Collective（MDC）的條款禁止把資料集放到平台以外的地方 [S18]。YouTube 條款禁止未經授權下載 [S38]。DLsite 規約禁止預定用途以外的複製 [S29]。
3. **標準答案的文字本身。** 判斷：標準答案記下的是說話內容，等於重製講稿或台詞。素材能公開時，標準答案依素材的授權一起公開，例如 CC BY-SA 素材的標準答案也用 CC BY-SA。市售作品的台詞不公開，只附數字；這和 #15 Q4 對 rec17 的處理方向一致。

## 候選來源總表

| 來源 | 內容 | 授權 | 進 repo | 本機評測 | 取得方式 |
|---|---|---|---|---|---|
| JVNV | 情緒語音＋非語言聲，4 人 3.94 小時 | CC BY-SA 4.0 | 可（署名、同授權） | 可 | 直接下載 zip（1.7 GB） |
| LibriVox 日文 | 有聲書朗讀，127 筆 | 公有領域（美國；原文要在當地也已過保護期） | 可 | 可 | 網站或 Internet Archive 下載 |
| 國語研「方言録音資料シリーズ」 | 1965–1973 年的方言對話，部分附文字稿 | 第 1–2 集 PDM 1.0；第 3–15 集 CC BY 4.0 | 可（署名） | 可 | 網頁直接下載 WAV |
| Wikimedia Commons | 零星的日文語音 | 逐檔標示（PD、CC BY、CC BY-SA 等） | 依各檔授權 | 可 | 逐檔下載 |
| JVS whisper10 | 耳語，100 人各 10 句 | 自訂：研究或個人使用，禁止再散布 | 不可（約 10 句可公開，含不含 repo 要問） | 可 | Google Drive zip（3.5 GB） |
| YODAS／YODAS2 日文 | YouTube 的 CC 影片＋字幕 | CC BY 3.0 | 不建議（無法回溯創作者） | 可 | Hugging Face |
| Common Voice 日文 27.0 | 短句朗讀，726 小時 | CC0＋平台條款 | 不可（平台條款） | 可 | MDC 註冊帳號、同意條款後下載 |
| 「明日への声」 | 政府廣報，雙人旁白＋講稿 | 限非營利 | 不建議（NC） | 可 | 政府広報オンライン的 MP3 |
| 市售 ASMR | 真實作品 | 作品權利＋DLsite 規約 | 不可 | 先取得許可 | 購買，並向社團取得許可 |
| 自錄或委託錄製 | 可以指定耳語、雙耳錄音 | 自己決定（建議 CC BY 4.0 或 CC0） | 可（取得授權後） | 可 | 自己錄，或與說話者簽約 |

## 各來源細節

### 可以進 repo

#### JVNV

- **內容**：4 位說話者（F1、F2、M1、M2），6 種情緒（anger、disgust、fear、happiness、sadness、surprise），含笑聲、啜泣等日常對話裡的非語言表現；共 1,615 句、3.94 小時，48 kHz、24-bit、單聲道 WAV；分成指定非語言台詞的 Regular session 與說話者自己決定台詞的 Phrase-free session [S2]。
- **授權**：頁面的「License / ライセンス」一欄只寫「CC BY-SA 4.0」，沒有分開標示文字與音檔 [S2]。
- **放進 repo 時**：CC BY-SA 4.0 要求保留作者標示、授權與免責聲明的連結、作品 URI，並註明修改 [S34 §3(a)(1)]。散布改作物時，改作物也要用相同授權 [S34 §3(b)]。
- **取得**：<https://ss-takashi.sakura.ne.jp/corpus/jvnv/jvnv_ver1.zip>（1.7 GB）；引用論文是 arXiv 2310.06072 [S2]。
- **判斷**：演出的情緒語音與非語言聲，比朗讀語料更接近角色配音；但它不是耳語，也不是雙耳錄音。

#### LibriVox 日文有聲書

- **授權**：LibriVox 寫道 "if you record for LibriVox, all your recordings will be donated to the public domain"、"you may do whatever you like with our recordings – you don't need permission"，並說不必署名，但希望署名 [S4]。它也提醒："all our recordings are public domain in the USA, but not necessarily in other countries"，在美國以外要自己確認作品在當地的著作權狀態 [S4]。
- **數量**：以錄音語言 Japanese 搜尋，2026-10-15 共有 127 筆；其中 37 筆是單人朗讀的完整作品，其餘收在多語合集裡 [S5]。
- **例子**：《こころ》由 ekzemplaro 朗讀，長 8:46:41，可以下載 64 kbps 的 MP3 zip（248 MB）或 M4B，頁面連到青空文庫的原文 [S6]。作者夏目漱石 1916 年歿 [S8]。日本的保護期間是作者死後 70 年 [S30 第 51 條]，台灣是死後 50 年 [S32 第 30 條]；判斷：兩地都已過保護期。
- **起草標準答案**：青空文庫規定著作權已消滅作品的檔案「有償・無償であるかを問わず、自由に複製・再配布・共有することができます」，也可以「実演・口述・翻案など自由に活用」[S7]。判斷：可以用原文起草標準答案，再對照錄音聽打校正，因為朗讀者可能讀錯或漏讀。
- **衍生資源**：Kokoro Speech Dataset 已把其中 14 本小說切段並自動對齊 [S9]。判斷：對齊是自動做的，不能直接當標準答案。
- **判斷**：單人朗讀、錄音品質不一，適合測長檔的分段轉錄、掉尾與接續，不代表 ASMR 的錄音條件。

#### 國立國語研究所「方言録音資料シリーズ」

- **授權**：「方言録音資料シリーズ1～2のテキストファイルと音声ファイルは クリエイティブ・コモンズ パブリック・ドメイン・マーク 1.0 ライセンスの下に提供されています」；第 3～15 集則是「クリエイティブ・コモンズ 表示 4.0 国際 ライセンス」[S10]。
- **內容**：1965–1973 年錄製的各地方言，包括鹿兒島、宮崎、岐阜、高知、秋田、石川、愛知、京都、靜岡與沖繩；卡帶數位化成 16-bit、16 kHz 的 WAV。文字稿只有第 1、2、3、4、5、8、11 集有 [S10]。
- **取得**：網頁上直接下載 zip [S10]。
- **判斷**：這是多人自然對話，可以測說話者分離；但內容是方言、錄音是老卡帶，離目標使用者很遠，只適合當補充。

#### Wikimedia Commons

- 每個檔案各自標示授權。「Audio files in Japanese」分類只有 36 個檔案和 7 個子分類；Lingua Libre 的日文發音有 1,180 個檔案，多半是單字或短語 [S11]。
- 例子：「Kyoto women conversation in 1964.ogg」是 CC BY 4.0，出自國語研方言録音資料的第 11 集「京都市方言」[S11]。
- **判斷**：量少、內容零散，只能偶爾補一兩段。

### 只能留本機

#### JVS（唯一的耳語語料）

- **內容**：100 位專業說話者（「100人のプロフェッショナル話者」），每人錄了 parallel100、nonpara30、whisper10（「ささやき声 10 発話」）與 falsetto10 [S1]。
- **授權原文（音檔）**：「音声データは，以下の場合に限り使用可能です」，可用的場合是「アカデミック機関での研究」「非商用目的の研究（営利団体での研究も含む）」「個人での利用（ブログなどを含む）」。再散布的規定是「この音声データの再配布は認められていませんが，あなたのウェブページやブログなどでコーパスの一部（例えば，10文程度）を公開することは可能です」[S1]。
- **文字與商用**：文字來自 JSUT，授權依 JSUT 的規定 [S1]；JSUT 頁面說文字是「CC-BY-SA 4.0などにて」授權 [S3]。商用部分，頁面寫「我々は本コーパスの商用利用を歓迎します」，並提供 48 kHz、24-bit 的高品質版本 [S1]。
- **判斷**：
  - 目前開源、不收費的用途，大致落在「非商用目的の研究」。ADR 0006 保留了未來自架服務或企業版的可能，真的商業化時要另外洽談。
  - 公開的 GitHub repo 算不算「ウェブページやブログなど」，頁面沒寫。要把那約 10 句放進 repo，先寫信問作者，頁面上有聯絡方式。
- **取得**：Google Drive 上的 zip（3.5 GB）；引用論文是 arXiv 1908.06248 [S1]。

#### YODAS／YODAS2（YouTube 的 CC 影片）

- **授權**：兩份資料卡都標 `license: cc-by-3.0` [S12][S13]；論文的表格也列 CC BY 3.0 [S14]。
- **收集方式**：論文說他們搭配 YouTube 的篩選功能搜尋，讓結果「(mostly) possess subtitles and adhere to the Creative Commons license」[S14]。資料卡寫「We made sure that our dataset only consisted of videos with CC licenses during our downloading」，並提供刪除請求的信箱 [S12]。
- **日文量**：ja000（手動字幕）1,094.18 小時、ja100（自動字幕）2,929.94 小時。資料卡說明，手動字幕只代表字幕是上傳者上傳的，不一定是人工聽打 [S12]。YODAS2 是同一批資料的長檔版，不切段、24 kHz [S13]。
- **署名的問題**：
  - YODAS2 資料卡寫明 `video_id` 這個欄位「is not the video_id in Youtube」[S13]。
  - 我取 ja000 第一個文字檔的前 9 個 `audio_id`，用 YouTube oEmbed 查詢，9 個全部回傳 404 或 400。對照組是已知影片回傳 200、隨便打的 ID 回傳 404 [S15]。
  - CC BY 3.0 要求在授權人有提供時，署名原作者、作品名稱與 URI [S35 §4(b)]。判斷：這批片段沒辦法照原作者署名，也沒辦法回到原影片確認授權。
- **YouTube 這端**：YouTube 的說明頁現在連到 CC BY 4.0 [S39]，和 YODAS 標的 3.0 不同。未查證：各影片實際標的是哪一版。
- **判斷**：
  - 本機評測可以，CC BY 允許重製。
  - 不建議進 repo。要公開影音類的片段，比較乾淨的做法是自己在 YouTube 用「Creative Commons」篩選找影片 [S39]，再向創作者索取原始檔，因為 YouTube 條款禁止未經 YouTube 授權下載 [S38]。
- **Emilia-YODAS**：它從 YODAS2 再處理而來，自稱 CC BY 4.0，日文約 1.1k 小時；但要先同意含免責賠償條款的存取條件 [S16]。判斷：不比直接用 YODAS2 好。

#### Common Voice 日文

- **授權**：MDC 上的「Common Voice Scripted Speech 27.0 - Japanese」標示「Creative Commons Zero v1.0 Universal (CC0-1.0)」，2026-09-17 上架 [S17]。
- **平台條款**：
  - 下載對話框要求同意「You agree that you will not re-host or re-share this dataset」與「You agree not to attempt to determine the identity of speakers in the Common Voice dataset」[S17]。
  - MDC 的資料使用者條款第 2(b)(ix) 條禁止「hosting, storing or making the Dataset available on any platform, server or repository other than the Platform, except as expressly permitted under the applicable Data Consumer License for that Dataset」。附錄 1 第 8 條也禁止「scrape, mirror, or redistribute the Dataset」，這一條沒有例外 [S18]。
  - 自 2025 年 10 月起，Common Voice 只在 MDC 發布，下載要註冊帳號並同意條款 [S19]。
- **規模**：27.0 版的日文有 585,330 段錄音、7,852 位說話者，總長 726.23 小時、驗證過的 372.6 小時，平均每段 4.47 秒 [S19]。另一個自由說話的 Spontaneous Speech 5.0 涵蓋 80 種語言，沒有日文 [S19]。
- **判斷**：CC0 在著作權上沒有問題，但平台條款是下載時答應的契約，放進 repo 就違約，所以只能留本機。內容又是短句朗讀，離 ASMR 很遠。

#### 政府內容

- **PDL1.0**：可以「複製、公衆送信、翻訳・変形等の翻案等、自由に利用できます」，「商用利用も可能です」；使用時要註明出處，加工時要另外註明；第三者有權利的部分要自己取得許可。這套規約與 CC BY 4.0 相容，國家「利用者がCC BYに従って利用することを許諾します」[S25]。
- **首相官邸**：網站與官方社群帳號的內容，除非另有標示，都適用 PDL1.0（2025-03-31 更新）[S26]。記者會頁面有嵌入政府広報オンライン的影片，也有文字紀錄 [S26]。
- **拿不到影片**：政府広報オンライン的規則寫明「動画や音声ファイルについては、音声広報CD「明日への声」の音声ファイルを除き、ダウンロードはできません」[S27]；YouTube 上的影片則受 YouTube 條款限制 [S38]。
- **「明日への声」**：每期 5 軌 MP3 可以下載，並附 HTML 版講稿 [S28]。例如 vol.111 第 2 軌標示「Q.女性ナレーター / A.男性ナレーター」，是雙人旁白 [S28]。但下載頁寫「非営利目的でのご利用に限り、自由に再生・ダウンロード・複製いただけます」[S28]。
- **判斷**：
  - 「明日への声」只能留本機（NC）。它有講稿可以起草標準答案，又有兩位說話者，可以測說話者分離；但這是錄音室的朗讀，不是 ASMR。
  - 記者會影片在授權上可以進 repo，但沒有合法的下載管道；要用就得向內閣広報室索取原始檔。未查證：內閣広報室是否提供。

#### 免費聲音素材（例：あみたろの声素材工房）

- **條款（2026-08-11 更新）**：商用與收益化都可以；免費使用時必須署名；明文寫「音声合成モデルやAIの学習もOK」[S45]。
- **再散布**：台詞素材在「ゲームやアプリへの同梱・研究目的など、「何かを作るための材料として使う」場合」可以再散布，條件是附上它的 Readme 或連到條款頁，並在一個月內寄信告知。但「声素材ファイルそのものを配布・販売の対象にすること」是禁止的 [S45]。
- **判斷**：本機評測可以。評測集放在 repo 裡，算「材料」還是「素材檔本身」，條款沒寫清楚；放進 repo 前先寄信確認。未查證：有沒有耳語素材。

### 市售 ASMR 作品

- **DLsite 規約**（2025-04-21 最終改定）：
  - 第 12 條：「本コンテンツに関する知的財産権はユーザーに移転せず、ユーザーには利用権のみが付与されます」，以及「ユーザーは、本サービスにおいて予定されている利用態様以外の態様で本コンテンツを利用（複製、譲渡、転載、貸与、送信、上映、改変、再許諾等の行為を含みます）することはできません」[S29]。
  - 第 17 條禁止刪除、迴避或使 DRM 等技術保護手段失效 [S29]。
  - 未查證：剪出評測片段、聽打成標準答案，算不算「予定されている利用態様」；規約沒寫。
- **日本著作權法**：
  - 第 30 條之 4：不以「著作物に表現された思想又は感情を自ら享受し又は他人に享受させること」為目的時，在必要限度內可以用任何方法利用；第 1 號列舉「著作物の録音、録画その他の利用に係る技術の開発又は実用化のための試験の用に供する場合」。但書排除「著作権者の利益を不当に害することとなる場合」[S30]。
  - 第 102 條把第 30 條之 4 準用到表演與錄音等著作鄰接權 [S30]。
- **文化庁的整理**（文件本身說明沒有法律拘束力 [S31 封面]）：
  - 第 30 條之 4 也涵蓋「生成 AI 以外の AI(認識、識別、人の判断支援等を行う AI)を開発する学習のための著作物の利用、技術開発・実用化試験のための著作物の利用」[S31 第 17 頁]。
  - 只要同時有「享受」的目的，就不適用 [S31 第 10、19 頁]。
  - 權利人表示反對，本身不會讓第 30 條之 4 不適用 [S31 第 26 頁]。
  - 利用行為地在日本時，適用日本的著作權法 [S31 第 7 頁]。
  - 聲優的聲音等著作鄰接權和 AI 的關係，還要再檢討 [S31 第 42 頁]。
- **判斷**：
  - 評測轉錄引擎，接近第 1 號的「技術の開発又は実用化のための試験」。但維護者聽打時必須細聽作品內容，會不會被認為同時有「享受」的目的，不確定。
  - 這條不處理 DLsite 的契約；維護者不在日本時，也未必適用日本法。未查證：平台契約能不能排除第 30 條之 4，文化庁的文件沒有處理。
- **不要從盜版來源取得**：日本著作權法第 30 條第 1 項第 3 號，把明知是侵權上傳而做的數位錄音排除在私人使用之外 [S30]。文化庁也說，明知網站刊載盜版還從那裡收集資料，「厳にこれを慎むべきものである」[S31 第 28 頁]。
- **台灣著作權法**（最後修正 2022-06-15）：
  - 第 51 條：「供個人或家庭為非營利之目的，在合理範圍內，得利用圖書館及非供公眾使用之機器重製已公開發表之著作」。
  - 第 65 條依利用目的、著作性質、利用的質量與比例、對市場的影響判斷合理使用 [S32]。
  - 全文沒有針對資料探勘或 AI 的專門條款；我在全文搜尋「資料探勘」「人工智慧」都沒有結果 [S32]。
- **判斷**：專案的評測集不完全是「個人或家庭」的用途，第 51 條未必適用，只能靠第 65 條個案判斷，結果不確定。
- **建議的做法**：
  - 向社團（權利人）取得書面許可，寫明作品、用途（只做轉錄評測）、只留本機或可以公開、標準答案能不能公開、署名方式與期限。
  - 公開評測結果時只附數字，不附台詞。要引用台詞，必須符合引用的規定：日本第 32 條、台灣第 52 條 [S30][S32]。

### 自己錄製或委託錄製

- 表演人對自己的表演有錄音權：日本著作權法第 91 條「実演家は、その実演を録音し、又は録画する権利を専有する」[S30]；台灣第 22 條第 2 項「表演人專有以錄音、錄影或攝影重製其表演之權利」[S32]。判斷：腳本是另一個著作，要另外取得權利。
- **要進 repo**：判斷：說話者與腳本作者都同意以 CC BY 4.0 或 CC0 授權，並保存同意紀錄。#15 也提醒，公開之後收不回來。
- **判斷**：這是唯一能同時貼近 ASMR（耳語、雙耳錄音、近距離收音）又能公開的做法；代價是要自己準備錄音環境。

### 不建議使用

| 來源 | 原因 |
|---|---|
| ReazonSpeech | 來源是地上波電視，超過 35,000 小時 [S20]。授權是 CDLA-Sharing-1.0，但「利用目的は著作権法３０条の４に定める情報解析に限る」[S20]。判斷：由人細聽聽打的小型評測集算不算「情報解析」，不確定；電視節目也不能公開。 |
| J-CHAT | YouTube 與 podcast 的對話；CC-BY-NC 4.0，而且「YOU WILL USE THE DATASET SOLELY FOR THE PURPOSE OF JAPANESE COPYRIGHT ACT ARTICLE 30-4」；也寫明「Commercial use is not admitted」[S21]。 |
| Emilia | CC BY-NC 4.0；存取條件要求使用者為使用資料引起的任何索賠「defend and indemnify the authors」，也就是負責賠償作者 [S16]。 |
| CSJ、CEJC、STUDIES | 都要付費或簽研究限定的契約：CSJ 的商業利用 50 萬日圓（未稅）起 [S22]；CEJC 的有償版要簽約 [S23]；STUDIES 標示「For research purpose only」[S24]。三者都不是 ASMR。 |
| Hugging Face 上的 ASMR 存檔 | 例如 DeliberatorArchiver/asmr-archive-data-01：卡片自稱「an archive of ASMR works」，超過 64 TiB，只寫「educational and research purposes only」與「All use is at your own risk」，標 AGPL-3.0，沒有出示權利人授權 [S42]。以它再處理的 OmniAICreator/ASMR-Archive-Processed 同樣沒有出示 [S42]。 |
| Hugging Face 上的動畫語音 | 例如 joujiboi/japanese-anime-speech：音檔來自視覺小說（visual novel）遊戲，卻標 CC0-1.0 [S43]。判斷：上傳者不是權利人，標籤不能當作授權。 |
| JTubeSpeech | 只列 YouTube 的影片 ID 與頻道 ID，README 沒有提到依授權篩選，下載靠 youtube-dl [S41]；這違反 YouTube 條款 [S38]。 |
| 青空朗読 | 原作是公有領域，但錄音有「実演家の権利」與「レコード製作者の権利」；「当法人の許可なく、音声を複製、転載、改変、再配布…することは、営利・非営利を問わず固く禁じております」[S46]。 |
| TED | CC BY-NC-ND 4.0，另外禁止「sharing truncated versions or clips」[S40]；而且多是英文。 |
| Freesound | 逐檔標示授權（CC0、CC BY、CC BY-NC），但 2026-10-15 搜尋「asmr japanese」0 筆、「japanese whisper」11 筆、「japanese speech」70 筆 [S44]。 |

## 放進 Apache-2.0 repo 時要做的事

1. **第三方音檔另放一個目錄。** 第三方音檔和它的標準答案放在一起，附一份清單，寫明每個檔案的來源 URL、作者、授權，以及有沒有修改。CC BY 4.0 與 CC BY-SA 4.0 要求保留作者標示、授權與免責聲明的連結、作品 URI，並註明修改 [S33][S34 §3(a)(1)]；也可以用「提供連結到載有這些資訊的頁面」的方式滿足 [S34 §3(a)(2)]。
2. **轉格式與剪片段。** 只轉取樣率、聲道等格式，屬於技術性修改，「never produces Adapted Material」[S33 §2(a)(4)]。授權本身允許散布「in whole or in part」[S33 §2(a)(1)]；判斷：不改內容、只剪出片段，屬於散布一部分，不會觸發 ShareAlike，但清單裡仍要註明剪輯的範圍。
3. **CC BY-SA 不會改變程式碼的授權。** ShareAlike 只約束改作物 [S34 §3(b)]。判斷：音檔放在 repo 裡，不會讓程式碼變成 CC BY-SA。ASF 也允許在 Apache 產品裡放未修改的 CC BY-SA 媒體檔，條件是遵守署名條款；不過它說的媒體檔是指文件用的影音檔 [S37]。
4. **NC 授權不進 repo。** ASF 的第三方授權政策把「Creative Commons Non-Commercial variants」列在 Category X，也就是不得放進 Apache 產品 [S37]。這份政策只約束 ASF 自己的專案，但它說明了 NC 和 Apache-2.0 使用者的預期不合；本專案的 ADR 0006 也保留了未來自架服務或企業版的可能。
5. **公有領域與 CC0 照樣附出處。** ASF 把它們當作公有領域處理，但仍要求附出處 [S37]；LibriVox 不要求署名，但希望署名 [S4]。

## 與 ADR 的關係

這份研究沒有和任何 ADR 衝突：

- ADR 0002 要求日文有評測集，這份研究提供素材的選項。
- ADR 0006 採用 Apache-2.0，並保留未來商業化的可能；「NC 素材不進 repo」與它一致。

## 沒能查證的事

- 各素材實際聽起來有多接近 ASMR：我只看了官方描述，沒有試聽。
- JVS 允許公開的「約 10 句」，包不包含公開的 GitHub repo。
- YouTube 上標 CC BY 的日文 ASMR 有多少：沒有用 YouTube API 搜尋。
- Common Voice 日文 27.0 的資料卡本文：要登入或執行 JavaScript 才會顯示；我核對的是頁面原始碼裡的下載對話框文字與平台條款。
- DLsite 規約第 12 條的「予定されている利用態様」，包不包含評測用的剪輯與聽打。
- 平台契約能不能排除日本著作權法第 30 條之 4：文化庁的文件沒有處理。
- 台灣有沒有資料探勘或 AI 的修法草案：只查了現行條文。
- 內閣広報室是否提供記者會的原始檔。
- 委託錄製時，個人資料保護法對錄音的要求。

## 來源

全部在 2026-10-15 查詢。

- **S1** JVS corpus（高道研究室）：<https://sites.google.com/site/shinnosuketakamichi/research-topics/jvs_corpus>
- **S2** JVNV corpus：<https://sites.google.com/site/shinnosuketakamichi/research-topics/jvnv_corpus>
- **S3** JSUT corpus：<https://sites.google.com/site/shinnosuketakamichi/publication/jsut>
- **S4** LibriVox「Copyright, Public Domain & LibriVox」：<https://librivox.org/pages/public-domain/>
- **S5** LibriVox 目錄搜尋（錄音語言＝Japanese）：<https://librivox.org/search>；結果取自 `https://librivox.org/advanced_search?title=&author=&reader=&keywords=&genre_id=0&status=all&project_type=either&recorded_language=35&sort_order=alpha&search_page=1&search_form=advanced`（帶 `X-Requested-With: XMLHttpRequest` 標頭時回傳 JSON；`search_page` 1 到 6）
- **S6** LibriVox《こころ》：<https://librivox.org/kokoro-by-soseki-natsume/>
- **S7** 青空文庫「収録ファイルの取り扱い規準」：<https://www.aozora.gr.jp/guide/kijyunn.html>
- **S8** 青空文庫 図書カード No.773《こころ》：<https://www.aozora.gr.jp/cards/000148/card773.html>
- **S9** Kokoro Speech Dataset README：<https://github.com/kaiidams/Kokoro-Speech-Dataset>
- **S10** 國立國語研究所「方言録音資料シリーズ」：<https://mmsrv.ninjal.ac.jp/hogenrokuon_siryo/>
- **S11** Wikimedia Commons：<https://commons.wikimedia.org/wiki/Category:Audio_files_in_Japanese>、<https://commons.wikimedia.org/wiki/Category:Lingua_Libre_pronunciation-jpn>、<https://commons.wikimedia.org/wiki/File:Kyoto_women_conversation_in_1964.ogg>；件數與授權取自 Commons API
- **S12** YODAS 資料卡（espnet/yodas）：<https://huggingface.co/datasets/espnet/yodas>
- **S13** YODAS2 資料卡與 ja000 文字檔：<https://huggingface.co/datasets/espnet/yodas2>、<https://huggingface.co/datasets/espnet/yodas2/blob/main/data/ja000/text/00000000.json>
- **S14** Li et al., "YODAS: YouTube-Oriented Dataset for Audio and Speech"（ASRU 2023）：<https://arxiv.org/abs/2406.00899>
- **S15** 我做的抽查：對 S13 的前 9 個 `audio_id`（Yo123xB6mfU、YoqlTvf-wuy、YoAYPg5gqVk、Y0mvoyahGYA、Y0wyvkJ18U0、Y0BUbvqeR4g、Y1Is-WQ8hhg、Y2TsPxXGjKQ、Y36WgDpQuIk）呼叫 `https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=<id>&format=json`；對照組 dQw4w9WgXcQ 回 200，abcdefghijk 回 404
- **S16** Emilia 資料卡（amphion/Emilia-Dataset）：<https://huggingface.co/datasets/amphion/Emilia-Dataset>
- **S17** MDC「Common Voice Scripted Speech 27.0 - Japanese」：<https://mozilladatacollective.com/datasets/cmu5xbhnf00fmnq07z9p3aa70>（授權與下載對話框的文字取自頁面原始碼）
- **S18** Mozilla Data Collective Data Consumer Terms of Use（Last Updated: May 06, 2026）：<https://mozilladatacollective.com/terms/consumers>
- **S19** Common Voice 統計與公告：<https://github.com/common-voice/cv-dataset>（`datasets/scripted-speech/cv-corpus-27.0-2026-09-11.json`、`datasets/spontaneous-speech/sps-corpus-5.0-2026-09-11.json`）；MDC 公告：<https://huggingface.co/mozilla-foundation>
- **S20** ReazonSpeech 資料卡與專案頁：<https://huggingface.co/datasets/reazon-research/reazonspeech>、<https://research.reazon.jp/projects/ReazonSpeech/>
- **S21** J-CHAT 資料卡：<https://huggingface.co/datasets/sarulab-speech/J-CHAT>
- **S22** 日本語話し言葉コーパス（CSJ）與利用料：<https://clrd.ninjal.ac.jp/csj/>、<https://clrd.ninjal.ac.jp/csj/fee.html>
- **S23** 日本語日常会話コーパス（CEJC）：<https://www2.ninjal.ac.jp/conversation/cejc.html>
- **S24** NII 音声資源コンソーシアム STUDIES：<https://research.nii.ac.jp/src/en/STUDIES.html>
- **S25** デジタル庁「公共データ利用規約（第1.0版）」：<https://www.digital.go.jp/resources/open_data/public_data_license_v1.0>
- **S26** 首相官邸「コピーライトポリシー」與記者會頁面範例：<https://www.kantei.go.jp/jp/terms.html>、<https://www.kantei.go.jp/jp/105/statement/2026/1014kaiken.html>
- **S27** 政府広報オンライン 利用規約：<https://www.gov-online.go.jp/tos/>
- **S28** 音声広報CD「明日への声」vol.111：<https://www.gov-online.go.jp/media/cd/202609/index.html>、<https://www.gov-online.go.jp/media/cd/202609/202609_02.html>
- **S29** DLsite 利用規約（2025年4月21日最終改定）：<https://www.dlsite.com/home/user/regulations>
- **S30** 日本 著作権法（昭和四十五年法律第四十八号，現行條文）：<https://laws.e-gov.go.jp/law/345AC0000000048>（條文取自 e-Gov 法令 API：<https://laws.e-gov.go.jp/api/1/lawdata/345AC0000000048>）
- **S31** 文化審議会著作権分科会法制度小委員会「AIと著作権に関する考え方について」（令和6年3月15日）：<https://www.bunka.go.jp/seisaku/bunkashingikai/chosakuken/pdf/94037901_01.pdf>（頁碼為文件內的頁碼）
- **S32** 台灣 著作權法（修正日期：民國 111 年 06 月 15 日）：<https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=J0070017>
- **S33** CC BY 4.0 Legal Code：<https://creativecommons.org/licenses/by/4.0/legalcode.en>
- **S34** CC BY-SA 4.0 Legal Code：<https://creativecommons.org/licenses/by-sa/4.0/legalcode.en>
- **S35** CC BY 3.0 Unported Legal Code：<https://creativecommons.org/licenses/by/3.0/legalcode.en>
- **S36** CC BY-NC 4.0 Legal Code：<https://creativecommons.org/licenses/by-nc/4.0/legalcode.en>
- **S37** ASF 3rd Party License Policy：<https://www.apache.org/legal/resolved.html>
- **S38** YouTube Terms of Service（Effective as of December 15, 2023）：<https://www.youtube.com/t/terms>
- **S39** YouTube 說明「Creative Commons」：<https://support.google.com/youtube/answer/2797468>
- **S40** TED Talks Usage Policy：<https://www.ted.com/about/our-organization/our-policies-terms/ted-talks-usage-policy>
- **S41** JTubeSpeech README：<https://github.com/sarulab-speech/jtubespeech>
- **S42** Hugging Face 上的 ASMR 存檔：<https://huggingface.co/datasets/DeliberatorArchiver/asmr-archive-data-01>、<https://huggingface.co/datasets/OmniAICreator/ASMR-Archive-Processed>
- **S43** joujiboi/japanese-anime-speech 資料卡：<https://huggingface.co/datasets/joujiboi/japanese-anime-speech>
- **S44** Freesound 搜尋：<https://freesound.org/search/?q=asmr+japanese>、<https://freesound.org/search/?q=japanese+whisper>、<https://freesound.org/search/?q=japanese+speech>
- **S45** あみたろの声素材工房 利用規約（最終更新日 2026/08/11）：<https://amitaro.net/voice/voice_rule/>
- **S46** 青空朗読「著作権について」：<https://aozoraroudoku.jp/contents/copyright.html>
