# 研究：ffmpeg LGPL build 的義務與可釘版的來源（#80，回答 #17 Q1）

- 查詢日期：2026-10-15。下文引用的每個來源都在這一天查閱，網址列在文末「來源」，內文以〔代號〕標示。
- 範圍：免安裝版 zip 裡的 `bin/ffmpeg.exe` 與 `bin/ffprobe.exe`。後端以子行程呼叫它們，把使用者的音檔轉成 wav。PyAV（`backend/requirements-standalone.txt:35` 的 `av==18.1.0`）是首次佈建時才由使用者端下載，屬於 #17 Q2，不在這份研究裡。
- 這不是法律意見；ffmpeg.org 的法律頁自己也寫明 "this is not legal advice"〔F1〕。標「解讀」的段落，是本研究從條文推出的結論；標「未驗證」的，是沒有實測或找不到第一手來源的部分。

## 短答

1. app 以子行程呼叫 ffmpeg，和 ffmpeg 放在同一個 zip 裡散布，屬於「聚合」（aggregate）：不論 GPL 或 LGPL build，app 的 Apache-2.0 都不受影響〔G1 §5、G3 §2、G4〕。
2. 散布 `ffmpeg.exe` 本身的核心義務，GPL build 和 LGPL build 一樣：附上授權全文；提供和這個二進位檔完全對應的原始碼；只要還在散布，就要讓原始碼可以取得〔G1 §4、§6，G5，G6〕。
3. BtbN 的 LGPL build 是 **LGPLv3**（`--enable-version3`），所以要附 LGPLv3 和 GPLv3 兩份全文〔B2、G2、G7〕。它的 zip 只附了 LGPLv3〔B9〕，原本的打包腳本又把這份也丟掉了〔R1〕。
4. 從網路下載散布時，要照 GPLv3 §6(d)：原始碼放在和二進位檔同一個地方（例如同一個 GitHub Release），或在二進位檔旁邊寫清楚去哪裡拿。§6(b) 的書面要約只適用實體產品〔G1 §6〕。轉散布從網路下載的二進位檔，也要自己附上原始碼〔G6〕。
5. 對 BtbN 的靜態 build 來說，「完全對應的原始碼」包括：FFmpeg 的某個 git commit、BtbN 建置腳本的 commit，以及靜態連入的外部函式庫。連 LGPL 版的 configure 都啟用了 59 個外部函式庫或系統介面〔B9〕。LGPL 版只是少了 x264、x265、xvid 等 GPL 專用的那幾個〔B4〕：義務的種類不變，只是要提供的範圍小一些。（解讀）
6. 兩種 build 都另外要做三件事：在文件裡寫 IJG 的致謝句〔F3、F6〕；FFmpeg 的拼法要寫對〔F1〕；不能附加限制使用者權利的條款，例如禁止逆向工程〔F1、G1 §5〕。絕對不能散布 `--enable-nonfree` 的 build，那是不可再散布的〔F3、F4〕。BtbN 本來就不發布 nonfree build〔B6〕。
7. 可以釘版的 Windows LGPL build：ffmpeg.org 只提供原始碼，Windows 只連到 gyan.dev 與 BtbN〔F2〕。gyan.dev 的 build 全部是 GPLv3〔Y1〕。BtbN 有 win64 LGPL build（static 或 shared，master、9.0 或 8.1 分支），可以用日期 tag 的網址加 SHA-256 釘住〔B5、B6〕。但 BtbN 的保留政策只承諾月底版留兩年、日版留最近 14 個〔B1〕；實際上最舊的只到 2024-11-30〔B5〕，所以 zip 與原始碼都要自己留一份。
8. 功能面：app 只用到解封裝、FFmpeg 內建的音訊解碼器、swresample 和 WAV（pcm_s16le）輸出，在 configure 裡都沒有 GPL 門檻〔F4、F9〕。MP3、AAC/M4A、OGG、Opus、FLAC、WebM、MP4 影片的音軌、WMA，在 LGPL build 都能解碼。這是讀原始碼判斷的，**沒有實測**。GPL build 多出來的東西，app 都用不到：x264、x265 等編碼器，AVS2 解碼，約 30 個視訊濾鏡，rubberband 音訊濾鏡，DVD／AviSynth 輸入，以及 9 個遊戲或舊格式的 ADPCM／CRI AHX 解碼器〔F3、F4、B4〕。

## 1. 現況

- `build_release.ps1:27` 下載的是 `https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip`〔R1〕。
  - `releases/latest/download/<檔名>` 永遠指向「最新的 release」〔H1〕；BtbN 的 `latest` 是每天覆蓋的浮動 build〔B1、B7〕，所以本機和 CI 在不同天打包，會拿到不同的 ffmpeg。
  - `master` 是開發分支；`gpl` 變體的 configure 是 `--enable-gpl --enable-version3`，也就是 GPLv3，`LICENSE.txt` 是 `COPYING.GPLv3`〔B2、B3〕。
- `Get-Cached`（`build_release.ps1:31-40`）的快取檔名固定是 `ffmpeg-win64.zip`，也沒有驗證雜湊；換了來源也不會重新下載〔R1〕。
- `build_release.ps1:97-105` 只把 `ffmpeg.exe`、`ffprobe.exe` 複製進發布包，zip 裡的 `LICENSE.txt` 沒有帶進去〔R1〕。
- `.github/workflows/release.yml:50-60` 只把發布包 zip 上傳到 GitHub Release，沒有原始碼或第三方授權〔R2〕。
- 2026-10-15 查詢時，`Wade0325/AI_translate` 還沒有任何 GitHub Release〔R3〕：GPL build 還沒有對外散布過。

## 2. Q1：要履行哪些義務

### 2.1 FFmpeg 的授權由 configure 參數決定

FFmpeg 大部分檔案是 LGPL v2.1+；啟用 GPL 的部分以後，整體變成 GPL v2+；`--enable-version3` 把（L）GPL 升到第 3 版〔F3〕。configure 依參數決定 build 的授權字串，`ffmpeg -L` 也只會印出其中一種授權文字〔F4 L4836-4850、F5〕：

| configure 參數 | build 的授權（configure 的 `license`） | 例子 |
|---|---|---|
| （都不加） | LGPL version 2.1 or later | FFmpeg 的預設〔F3〕 |
| `--enable-version3` | LGPL version 3 or later | BtbN `lgpl`、`lgpl-shared`〔B2〕；conda-forge 的 `lgpl_*` 套件〔C3〕 |
| `--enable-gpl` | GPL version 2 or later | |
| `--enable-gpl --enable-version3` | GPL version 3 or later | BtbN `gpl`〔B2〕、gyan.dev〔Y1〕、MSYS2〔M1〕 |
| `--enable-nonfree` | "nonfree and unredistributable" | BtbN 的 `nonfree` 變體（沒有發布）〔B2、B6〕 |

- configure 的說明文字：`--enable-nonfree` 產生的函式庫與執行檔「unredistributable」〔F4 L97-102〕；LICENSE.md 也寫明啟用 nonfree 會「cause the resulting binary to be unredistributable」〔F3〕。
- 外部函式庫會影響授權〔F3、F4 L2029-2064〕：
  - 只能以 GPL 啟用（不加 `--enable-gpl` 時 configure 會直接中止）：avisynth、frei0r、libcdio、libdavs2、libdvdnav、libdvdread、librubberband、libvidstab、libx264、libx265、libxavs、libxavs2、libxvid。
  - 要加 `--enable-version3`：gmp、libaribb24、liblensfun、libopencore-amrnb/amrwb、libvo-amrwbenc、mbedtls、rkmpp；libsmbclient 要 GPLv3。
  - nonfree：decklink、libfdk-aac、libmpeghdec。
- BtbN 的 LGPL build 啟用了 gmp、libaribb24、libopencore-amrnb/amrwb〔B9〕，這幾個都在 configure 的 version3 清單上〔F4 L2051-2060〕，所以一定要加 `--enable-version3`，結果就是 LGPLv3。從 9.0 這個檔案的 `ffmpeg.exe` 讀出來的授權字串是 "LGPL version 3 or later"，也沒有 nonfree 的那段文字〔B9〕。

### 2.2 以子行程呼叫：屬於聚合，app 不受影響

- GPLv3 §5 最後一段：與「separate and independent works」一起放在儲存或散布媒體上、沒有結合成「a larger program」的組合稱為 aggregate，「Inclusion of a covered work in an aggregate does not cause this License to apply to the other parts of the aggregate」〔G1〕。LGPLv2.1 §2 的「mere aggregation」有同樣的效果〔G3〕。
- FSF 的 FAQ：pipes、sockets、command-line arguments 是兩個獨立程式之間常用的溝通方式，「the modules normally are separate programs」；但溝通內容若親密到交換複雜的內部資料結構，也可能被視為同一個程式，界線最後由法院決定〔G4〕。
- app 的用法是把檔名當命令列參數傳給 `ffmpeg`／`ffprobe`，再讀結束碼、stderr，以及 ffprobe 印到 stdout 的 JSON（`backend/app/utils/audio.py:26-160`、`backend/app/provider/local/asr.py:154-165`）〔R4〕：落在 FAQ 說的「通常是獨立程式」那一側。（解讀）
- 聚合的條件之一：組合「not used to limit the access or legal rights of the compilation's users beyond what the individual works permit」〔G1 §5〕。所以發布包的 README 或授權說明，不能限制使用者依 ffmpeg 授權本來就有的權利。（解讀：Apache-2.0 本身沒有這類限制）

### 2.3 散布 `ffmpeg.exe` 本身的義務（GPL 與 LGPL 共通）

LGPLv3 是「GPLv3 加上一些額外許可」〔G2 開頭〕。它主要的額外許可（§3 標頭檔、§4 Combined Works、§5 Combined Libraries）是給「連結或使用這個函式庫的程式」用的；app 沒有連結 FFmpeg，所以用不到。原封不動散布 `ffmpeg.exe` 時，適用的是 GPLv3 §4 到 §6〔G2〕。（解讀）也就是說，**這一節的義務在 GPL build 與 LGPL build 都一樣**。

#### a. 附上授權全文

- GPLv3 §4：要「give all recipients a copy of this License along with the Program」，並保留著作權聲明與無擔保聲明〔G1 §4〕。
- LGPL 要附 LGPL 與 GPL 兩份：FSF 說「since the LGPL is a set of additional permissions on top of the GPL, it's crucial to include both licenses」〔G7〕。
- BtbN 的 zip 只有 `LICENSE.txt`，內容和 FFmpeg 原始碼裡的 `COPYING.LGPLv3` 逐位元組相同〔B9〕；沒有 GPLv3 全文，也沒有任何外部函式庫的授權文字〔B9〕。GPLv3 全文在 FFmpeg 原始碼裡就有（`COPYING.GPLv3`）〔F3〕。

#### b. 提供完全對應的原始碼（Corresponding Source）

- GPLv3 §1 的定義：產生、安裝、執行這個目的碼並加以修改所需的**全部**原始碼，包括控制這些步驟的腳本；不包括 System Libraries，以及沒有修改、也不屬於這個作品的通用工具（例如編譯器）〔G1 §1〕。
- 轉散布從網路下載的二進位檔，也要自己附上完整的對應原始碼〔G6〕。ffmpeg.org 的檢查清單也要求「Distribute the source code of FFmpeg, no matter if you modified it or not」，並且「Make sure the source code corresponds exactly to the library binaries you are distributing」〔F1〕。
- 以 BtbN 的 9.0 LGPL build（`ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-9.0.zip`）為例，「完全對應」是指：
  1. **FFmpeg**：檔名裡的 `n9.0.2-17-g2a571b6068`，是 tag `n9.0.2` 之後第 17 個 commit `2a571b6068`〔F11〕。BtbN 建置時直接 clone 分支的最新 commit，沒有改動 FFmpeg 的程式碼〔B3 L40、B4〕。所以這份 build **不等於**官方簽章的 `ffmpeg-9.0.2.tar.xz`，要提供的是那個 commit 的快照。
  2. **建置腳本**：該次建置的 BtbN commit 是 `6c9aec5f`。tag `autobuild-2026-09-30-13-08` 指向它，產生這批檔案的排程 workflow 也是在這個 commit 上跑的〔B8〕。BtbN 的腳本是 MIT 授權〔B10〕。
  3. **外部函式庫**：BtbN 下載原始碼的依賴腳本，都以 `SCRIPT_COMMIT` 或 `SCRIPT_REV` 釘住上游版本（134 個腳本中有 127 個；其餘 7 個是 base、finalize 這類不下載原始碼的腳本）〔B4〕。aom 與 aribb24 套了 BtbN 自己的 patch（`patches/`）〔B4〕。這份 build 的 configure 啟用了 59 個外部函式庫或系統介面（不算 `--enable-version3`、`--enable-pthreads`；清單見 §5）〔B9〕，其中 schannel、cuda-llvm 等是系統介面或編譯選項；間接依賴（例如 librsvg、libass 再用到的函式庫）不在 configure 這一行裡（未逐一清點）。
- 解讀：照 §1 的定義，保守的做法是把靜態連入 `ffmpeg.exe` 的每個外部函式庫的原始碼都提供出來，至少要涵蓋其中（L）GPL 授權的（ffmpeg.org 清單第 17 項以 LAME 為例〔F1〕）。permissive 授權（BSD、MIT 等）的函式庫，至少要附上它們的著作權與授權聲明。哪些要附原始碼、哪些只要附聲明，留給第三方授權盤點（草稿 v01-48）逐一確認。（未驗證：本研究沒有逐一核對 59 項各自的授權）
- ffmpeg.org 另外建議：用 `git diff > changes.diff` 提供修改內容（BtbN 沒有改動 FFmpeg，所以是空的）；把 configure 那一行寫進原始碼根目錄的文字檔；原始碼用 tarball 或 zip 提供〔F1〕。

#### c. 原始碼放在哪裡、放多久

- 從網路下載時適用 GPLv3 §6(d)：「offer equivalent access to the Corresponding Source in the same way through the same place at no further charge」；原始碼可以放在另一台伺服器（自己的或第三方的），但要「maintain clear directions next to the object code saying where to find the Corresponding Source」，而且不論放在哪，「you remain obligated to ensure that it is available for as long as needed」〔G1 §6〕。
- FSF FAQ：可以把原始碼放在另一個網站，但要給清楚的取得方式，並確保「the source remains available for as long as you distribute the object code」〔G5〕。
- §6(b) 的書面要約（三年有效）只適用「a physical product (including a physical distribution medium)」；§6(c) 只限偶爾、非商業、而且自己也是收到書面要約的情況〔G1 §6〕。GitHub 下載不屬於這兩種，所以 #17 說的「提供原始碼的取得方式」要照 §6(d) 做，不能只附一份書面要約。（解讀）
- 若改用沒有加 `--enable-version3` 的 LGPL v2.1+ build（例如自己建置、又不啟用 version3 清單上的函式庫），LGPLv2.1 §4 要求原始碼隨附，或從「the same place」提供同等的取得管道〔G3 §4〕；它沒有替函式庫本身提供書面要約這個選項。
- ffmpeg.org 清單第 8 項：「Host the FFmpeg source code on the same webserver as the binary you are distributing」〔F1〕。對這個專案來說，最直接的做法是把原始碼附在同一個 GitHub Release 的 assets（解讀）。上游的 GitHub、SourceForge 等網站不在我們的控制之下；BtbN 的 release 也會依保留政策被刪除（§3.2），所以只放連結的話，要承擔「as long as needed」的風險。

#### d. 其他聲明

- **IJG**：`libavcodec/jfdctfst.c`、`jfdctint_template.c`、`jrevdct.c` 來自 libjpeg。只散布執行檔時，「you must credit the IJG in the documentation accompanying your program」〔F3〕；檔頭的原文是要在隨附文件寫明「this software is based in part on the work of the Independent JPEG Group」〔F6〕。只要啟用了 idctdsp 或 fdctdsp，這些檔案就會編進去〔F7〕；預設會啟用的 mjpeg 解碼器就用到 idctdsp〔F4 L3248〕。GPL 與 LGPL build 都適用。
- **名稱**：FFmpeg 是 Fabrice Bellard 的商標；清單要求別拼錯（兩個大寫 F、小寫 mpeg）〔F1〕。
- **不得附加限制**：清單要求「Remove any prohibition of reverse engineering from your EULA」〔F1〕；GPLv3 的聚合條件也一樣（§2.2）。

### 2.4 ffmpeg.org 的「License Compliance Checklist」逐條對照

這份清單是寫給「linking against the FFmpeg libraries」的情況，ffmpeg.org 說它「not the only way to comply」，其中有幾項只是「good ideas anyway」〔F1〕。「本專案」一欄是本研究的解讀。

| # | 清單內容（摘要）〔F1〕 | 本專案 |
|---|---|---|
| 1 | 不用 `--enable-gpl`、`--enable-nonfree` 編譯 | 選 LGPL build 時適用；BtbN `lgpl` 符合〔B9〕 |
| 2 | 以動態連結（Windows 上就是 dll）連結 FFmpeg | 不適用：app 不連結 FFmpeg |
| 3 | 不論有沒有修改，都要散布 FFmpeg 原始碼 | 適用（§2.3 b） |
| 4 | 原始碼要和散布的二進位檔完全對應 | 適用：要對應到 commit，不是對應到版本號（§2.3 b） |
| 5 | 用 `git diff > changes.diff` 提供修改 | 適用；沒有修改時就是空檔 |
| 6 | 用文字檔說明怎麼編譯（configure 那一行） | 適用；BtbN 的 configure 行可以從二進位檔讀出〔B9〕 |
| 7 | 原始碼用 tarball 或 zip | 適用 |
| 8 | 原始碼放在和二進位檔同一台伺服器 | 適用：同一個 GitHub Release（§2.3 c） |
| 9 | 每個下載頁都要寫「This software uses code of FFmpeg licensed under the LGPLv2.1 and its source can be downloaded here」 | 適用於 README 與 Release 頁；BtbN build 是 LGPLv3，要把版本改成 v3（解讀） |
| 10 | 在程式的「關於」寫「This software uses libraries from the FFmpeg project under the LGPLv2.1」 | 建議做（屬「good idea」）；版本同上 |
| 11 | EULA 寫明程式使用 LGPL 的 FFmpeg | 專案沒有 EULA；在授權說明裡寫明 |
| 12 | EULA 若主張程式碼所有權，要寫明 FFmpeg 不屬於你 | 在第三方授權說明裡寫明 |
| 13 | 移除禁止逆向工程的條款 | Apache-2.0 沒有這種條款；README 也不要加 |
| 14 | EULA 的各語言版本都要一致 | README 有多語版時適用 |
| 15 | 不要拼錯 FFmpeg | 適用 |
| 16 | 不要把 FFmpeg 的 dll 改成難以辨認的名稱 | 只有改用 shared 變體時適用 |
| 17 | 對編進 FFmpeg 的每個 LGPL 外部函式庫（例如 LAME）重做一遍 | 適用：BtbN `lgpl` 有 `--enable-libmp3lame` 等〔B9〕 |
| 18 | 確定程式沒有用到任何 GPL 函式庫（特別是 libx264） | 選 LGPL build 時適用；BtbN `lgpl` 有 `--disable-libx264`〔B9〕 |

### 2.5 GPL build 與 LGPL build 在這個專案的差別

| 項目 | LGPL build（BtbN `lgpl`） | GPL build（BtbN `gpl`，現況） |
|---|---|---|
| app 的授權 | 聚合，不受影響 | 聚合，不受影響（§2.2） |
| 要附的授權全文 | LGPLv3 + GPLv3〔G7〕 | GPLv3〔G1 §4〕 |
| 對應原始碼 | 要，完全對應（§2.3 b） | 要，完全對應（同左） |
| 原始碼的範圍 | FFmpeg + 59 個外部函式庫／系統介面與其依賴〔B9〕 | 再加上 x264、x265、xvid、xavs2、davs2、vidstab、frei0r、rubberband、avisynth、libdvdcss/dvdread/dvdnav〔B4〕 |
| 聚合界線若被質疑 | 就算被認定成「使用函式庫的程式」，LGPL 仍允許，只要再履行 LGPLv3 §4 的條件〔G2 §4〕（解讀） | 若被認定為同一個程式，整體要以 GPL 授權〔G1 §5(c)〕（解讀；依 §2.2 不太可能） |
| ffmpeg.org 的 LGPL 檢查清單 | 可以照做〔F1〕 | 不適用（第 1、18 項就排除了） |

結論（解讀）：#17 的表格說 LGPL「義務比較輕：附上授權文字，並提供原始碼的取得方式」，這只對一半。在這個專案的用法下，兩種 build 都要附授權全文，也都要提供和二進位檔**完全對應**的原始碼；#17 表格寫在 GPL 那一列的條件，LGPL build 也一樣要做。LGPL 比較輕的地方，是要提供的元件比較少，以及聚合界線多一層保障。

## 3. Q2：可以釘版的 Windows LGPL build

### 3.1 FFmpeg 官方沒有發布二進位檔

- 下載頁：「FFmpeg only provides source code. Below are some links that provide it already compiled」；Windows 一欄只列「Windows builds from gyan.dev」與「Windows builds by BtbN」〔F2〕。
- 目前的穩定版是 9.0.2 "Lei"（2026-09-18 發布，9.0 分支 2026-06-26 從 master 切出）。8.1.3 是 2026-09-21 發布〔F2〕。
- 官方原始碼 tarball 以 PGP 金鑰 `FCF986EA15E6E293A5644F10B4322F04D67658D8` 簽章，下載頁附有驗證方法〔F2〕。

### 3.2 BtbN FFmpeg-Builds（有 LGPL）

- **變體**：`gpl`、`lgpl`（「Lacking libraries that are GPL-only. Most prominently libx264 and libx265」）、`nonfree`，以及它們的 `-shared` 版；可以再加上 `4.4`…`9.0` 從 release 分支建置〔B1 L57-66〕。自動建置只跑 win(arm)64 與 linux(arm)64〔B1〕。
- **實際發布的檔案**：以 2026-09-30 月底那一批為例，Windows x64 有 master、9.0、8.1 三條線，各有 GPL／LGPL × static／shared 四種，**沒有 nonfree**〔B6〕。
- **檔名**：`ffmpeg-<git describe>-win64-<變體>[-<分支>].zip`，例如 `ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-9.0.zip`〔B3 L66、B6〕。浮動的 `latest` release 裡改用 `ffmpeg-master-latest-win64-lgpl.zip`、`ffmpeg-n9.0-latest-win64-lgpl-9.0.zip` 這種名稱，每天覆蓋〔B7〕。同一批裡，master 的各變體可能建在不同的 commit 上（例如 2026-09-30 那批 win64 的 LGPL static 是 `N-127032`，另外三個是 `N-127021`）〔B6〕。
- **保留政策**：「The last build of each month is kept for two years」、「The last 14 daily builds are kept」、「The special "latest" build floats」〔B1 L16-20〕。2026-10-15 實際查到 37 個 release：`latest`、最近的日版，以及 2024-11-30 到 2026-09-30 的月底版；最舊的是 `autobuild-2024-11-30-13-12`，大約 22.5 個月前〔B5〕，比 README 寫的兩年短一些。
- **雜湊**：每批都附 `checksums.sha256`〔B6〕；GitHub 也替每個 release asset 算好 SHA-256 digest（2025-06 起）〔H2〕。本研究下載上面那個 9.0 LGPL 檔，三方的值一致：自己用 `Get-FileHash` 算出的值、`checksums.sha256`、GitHub 的 asset digest，都是 `6b264b9e6019103f601d98c292bd332fd87acf1c5e941ddff4fb71760fe63432`〔B6、B9〕。
- **zip 內容**（9.0 LGPL static）：`bin/ffmpeg.exe`（134,497,280 bytes）、`bin/ffprobe.exe`（134,296,064）、`bin/ffplay.exe`、`LICENSE.txt`（LGPLv3）、`doc/` 裡的 FFmpeg HTML 文件、`presets/`；**沒有**原始碼、GPLv3 全文或第三方授權〔B9〕。
- **支援的 Windows**：README 寫「Windows builds are targetting Windows 7 and newer, provided UCRT is installed」，最低支援 Windows 10 22H2〔B1 L5-6〕。

2026-09-30 月底那一批的 win64 LGPL 檔案（依政策會保留到 2028 年左右）〔B6〕：

| 分支 | 檔名 | 大小 | SHA-256 |
|---|---|--:|---|
| 9.0 | `ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-9.0.zip` | 163.6 MiB | `6b264b9e6019103f601d98c292bd332fd87acf1c5e941ddff4fb71760fe63432` |
| 9.0（shared） | `ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-shared-9.0.zip` | 73.5 MiB | `7157177b8a6cb2174c1650ba8c71b363f2c78cba5330f88c4c02cf5b2b880646` |
| 8.1 | `ffmpeg-n8.1.3-9-g29e619e767-win64-lgpl-8.1.zip` | 162.8 MiB | `4a7642b2264c03e8a0ce8a3825b933ee5580656f45695a086fe7e294045ffc0a` |
| master | `ffmpeg-N-127032-g6ae491a26c-win64-lgpl.zip` | 168.0 MiB | `c73ad424c5f9d94dd48815b4d3531e57130cb9f5c3dc8f21f4aa4e1fdb0658e3` |

下載網址的格式是 `https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/<檔名>`〔B6〕。

### 3.3 gyan.dev（只有 GPLv3）

- 「All builds are 64-bit, static and licensed as GPLv3」；只有附帶的 tools 套件是 LGPLv3，而那個套件不含 ffmpeg 與 ffprobe〔Y1〕。
- essentials 版就包含 libx264、libx265、libxvid、librubberband、libvidstab、avisynth+〔Y1〕。
- 可以釘版：release 版有帶版本號的網址（例如 `https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip`），每個檔案都附 `.sha256`〔Y1〕。GitHub 鏡像 `GyanD/codexffmpeg` 每個版本一個 tag（例如 `9.0.2`），asset 也有 digest〔Y2〕。
- gyan.dev 可以付費訂製 Windows build，條件是不能需要 `--enable-nonfree`〔Y1〕；本研究沒有詢問 LGPL 訂製的條件與價格（未驗證）。
- 結論：可以釘版，但沒有 LGPL，不符合 Q1 的 LGPL 選項。

### 3.4 其他套件來源

- **conda-forge**：預設 `license_family` 是 `lgpl`，用官方 tarball `ffmpeg-<版本>.tar.gz` 加上 feedstock 的 patch 建置〔C1〕。套件的中繼資料寫 `LGPL-2.1-or-later`〔C1、C2〕，但 `build.sh` 的 configure 一律加 `--enable-version3`〔C3〕，依 FFmpeg 的規則實際是 LGPLv3〔F4 L4836-4850〕；兩邊的標示不一致。有 win-64 的 9.0.2 LGPL 套件，例如 `win-64/ffmpeg-9.0.2-lgpl_h4e4debe_600.conda`（sha256 `418a18d25280ed3e7913ef4325c808c4f3260ee8b7206593cfc185da623629f4`）〔C2〕。它是 DLL 版，依賴約 30 個其他 conda 套件（aom、lame、libopus、openssl、sdl2 等）〔C2〕。要放進發布包，得自己組出整組 DLL；本研究沒有試（未驗證）。
- **MSYS2**：`mingw-w64-ffmpeg` 9.0.2 是 `GPL-3.0-or-later`（`--enable-gpl --enable-version3 --enable-libx264`）〔M1〕，不符合 LGPL 選項。

### 3.5 自己建置

- 用 BtbN 的腳本：`./makeimage.sh win64 lgpl 9.0` 加上 `./build.sh win64 lgpl 9.0`，需要 bash 與 docker〔B1〕。結果和他們發布的檔案同一套設定，但 FFmpeg 是 clone 分支當下最新的 commit〔B3 L40〕，要另外記下 commit 才能對應原始碼。
- 只含 FFmpeg 原生元件的最小 LGPL build：從簽章過的官方 tarball 建置，不啟用任何外部函式庫。§4 列出的格式都由原生解碼器處理，所以功能上夠用〔F4〕。要提供的原始碼只剩 FFmpeg tarball、configure 那一行和建置腳本，第三方盤點也最短。代價是要自己維護 Windows 的交叉編譯流程。（解讀；**未實測**：沒有實際建過，也不知道檔案大小與建置時間）

### 3.6 釘版與驗證的做法（給 v01-47 的草案，未在 `build_release.ps1` 實測）

1. 選一個**月底版**（保留最久）的 tag 和檔名，把網址和 SHA-256 寫死在 `build_release.ps1`。快取檔名要帶版本，換版時才會重新下載：

   ```powershell
   $FfmpegTag    = "autobuild-2026-09-30-13-08"
   $FfmpegFile   = "ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-9.0.zip"
   $FfmpegSha256 = "6b264b9e6019103f601d98c292bd332fd87acf1c5e941ddff4fb71760fe63432"
   $FfmpegUrl    = "https://github.com/BtbN/FFmpeg-Builds/releases/download/$FfmpegTag/$FfmpegFile"

   $ffZip = Get-Cached $FfmpegUrl $FfmpegFile
   $actual = (Get-FileHash -Algorithm SHA256 $ffZip).Hash   # -ne 比較字串時不分大小寫
   if ($actual -ne $FfmpegSha256) { throw "ffmpeg 壓縮包的 SHA-256 不符：$actual" }
   ```

2. 驗證它真的是 LGPL build，三種方法任選：
   - `LICENSE.txt` 要和 FFmpeg 的 `COPYING.LGPLv3` 相同〔B3 L71、B9〕。
   - `ffmpeg -hide_banner -L` 要印出「GNU Lesser General Public License … version 3」；nonfree build 會印出「has nonfree parts compiled in」〔F5〕。
   - `ffmpeg -hide_banner -buildconf` 裡不能有 `--enable-gpl` 或 `--enable-nonfree`。conda-forge 的 recipe 也用 `-buildconf` 檢查授權參數〔C1〕。
3. 用 CI 上的小樣本，實測 §4 每種格式都能轉成 16 kHz 單聲道 wav（目前**沒有**這個測試）。
4. 因為 BtbN 會刪掉舊的 release（§3.2），也因為 §2.3 c 要求原始碼一直可以取得：zip 本身、FFmpeg commit 的快照、BtbN 腳本快照與依賴的原始碼，都要自己保存，並附在發布的 GitHub Release 上。

## 4. Q3：LGPL 與 GPL build 的功能差異

### 4.1 app 實際用到的 ffmpeg 功能

- `ffprobe -v quiet -print_format json -show_format <檔案>`：只讀時長（`audio.py:26-65`）〔R4〕。
- `ffmpeg -y -i <檔案> -ar 16000 -ac 1 <輸出>.wav`（`audio.py:121-160`）；`-ss`／`-t` 切段並輸出 wav（`audio.py:81-118`）；`-ac 1 -ar <取樣率>` 轉單聲道（`asr.py:154-165`）〔R4〕。
- 沒有用到任何 `-af`／`-vf` 濾鏡，也沒有指定編碼器；WAV 的預設音訊編碼是 `pcm_s16le`〔F9〕，取樣率轉換用 libswresample（LGPL；LICENSE.md 只把它的測試程式列為 GPL）〔F3〕。
- 輸出是 WAV，而 WAV 只能放音訊。沒有 `-map` 時，ffmpeg 依輸出格式自動選串流：每種可放的類型各選一條，音訊選聲道最多的那條〔F10〕。所以 MP4 影片只會解它的音軌，**不需要**解 H.264。

### 4.2 常見格式在 LGPL build 的支援

下表的元件在 configure 裡都沒有 `gpl` 依賴：有的只選用 FFmpeg 內部元件（`_select`），有的連依賴宣告都沒有（例如 flac、vorbis、alac 解碼器）〔F4 L3120-3376、L3914-4011〕。

| 使用者的檔案 | 解封裝（demuxer） | 音訊解碼器（FFmpeg 內建） | LGPL build |
|---|---|---|---|
| MP3 | mp3 | mp3float／mp3 | 可以 |
| AAC／M4A | mov（m4a）、aac（ADTS） | aac、aac_fixed；ALAC 用 alac | 可以 |
| OGG | ogg | vorbis、opus、flac | 可以 |
| Opus | ogg | opus（需要 swresample，LGPL）；BtbN 也啟用了 libopus〔B9〕 | 可以 |
| FLAC | flac | flac | 可以 |
| WebM／MKV | matroska | opus、vorbis、aac 等 | 可以 |
| MP4／MOV 影片的音軌 | mov | aac、ac3、eac3 等；h264 也是內建的 LGPL 解碼器，但用不到（§4.1） | 可以 |
| WMA | asf | wmav1、wmav2、wmapro、wmalossless、wmavoice | 可以 |
| WAV | wav | pcm_* | 可以 |

**未驗證**：上表是讀 configure 判斷的。本研究沒有執行下載回來的二進位檔，也沒有實際轉檔測試（見 §3.6 第 3 點）。

### 4.3 GPL build 多出來、但 app 用不到的東西

- **GPL 外部函式庫**（BtbN 在 `lgpl` 變體停用）〔B4、B9〕：libx264、libx265、libxvid、libxavs2（編碼器）；libdavs2（AVS2 視訊解碼）；libvidstab、frei0r（視訊濾鏡）；librubberband（rubberband 音訊濾鏡，做變速與變調）；avisynth（讀取 AviSynth 腳本）；libdvdnav、libdvdread、libdvdcss（dvdvideo 解封裝）〔各項用途見 F13〕。
- **FFmpeg 內建的 GPL 部分**〔F3、F4〕：
  - 約 30 個視訊濾鏡，例如 cropdetect、hqdn3d、eq、delogo、boxblur（`_filter_deps="gpl"`，F4 L4152-4293）；沒有音訊濾鏡。
  - x86 最佳化 `flac_dsp_gpl.asm`：只用在 FLAC **編碼器**（`flac_enc_lpc_16`，只在 `CONFIG_GPL` 且啟用 FLAC 編碼器時編入）〔F8〕；另有 `idct_mmx.c`、`vf_removegrain.asm`〔F3〕。
  - `lgpl_gpl`：檔案本身是 LGPL，但「some developers prefer only building them with --enable-gpl」〔F4 L4837〕。8 個 ADPCM 解碼器（Circus、IMA Acorn Escape、IMA HVQM2、IMA HVQM4、IMA Magix、IMA PlayDate、Silicon Graphics N64、Playstation C），以及 CRI AHX 的解碼器、parser、bsf〔F4 L3129-3140、L3735、L3750；名稱見 F12〕；都是遊戲或舊平台的格式。8.1.3、9.0、master 的 configure 都有這個門檻。
- 兩種 build 都**沒有** libfdk-aac（屬於 nonfree）〔B4〕；AAC 一律由內建的 aac 解碼器處理。

### 4.4 不在授權範圍：專利

GPL 和 LGPL 都不處理專利授權的問題；ffmpeg.org 另有一段「Patent Mini-FAQ」說明這件事〔F1〕。AAC、H.264 等內建解碼器在兩種 build 裡都有，所以專利不是選 GPL 或 LGPL 的因素（解讀）。這份研究沒有評估專利風險。

## 5. 對 #17 與後續 ticket 的意義

- **#17 Q1**：功能上，LGPL build 足夠（§4，待實測）。義務上，LGPL 仍然要附 LGPLv3 + GPLv3 全文，也要提供完全對應的原始碼；比 GPL 輕的只是元件少一些（§2.5）。所以要考慮的選項可能不只「BtbN LGPL vs BtbN GPL」，還有「自建只含原生元件的 LGPL build」：義務最少，但要自己維護建置（§3.5）。
- **草稿 v01-47（ffmpeg 釘版並履行授權義務）**，可以直接用的清單：
  - 用 §3.6 的做法釘版並驗證。
  - 把授權全文與聲明放進發布包，例如 `licenses/ffmpeg/`：LGPLv3、GPLv3、IJG 致謝句、FFmpeg 使用聲明（§2.3 a、d）。
  - 把原始碼附在同一個 GitHub Release：`release.yml` 目前只上傳 zip，要一併上傳原始碼，或在 Release 說明裡寫清楚取得方式（§2.3 c）。
- **草稿 v01-48（第三方授權聲明）**：BtbN 9.0 LGPL build 的 configure 啟用了下列 59 項〔B9〕：
  iconv zlib libxml2 libvmaf fontconfig libharfbuzz libfreetype libfribidi vulkan libdav1d libvorbis librav1e librsvg gmp lzma liblcevc-dec opencl amf libaom chromaprint ffnvcodec cuda-llvm libgme libkvazaar libaribb24 libaribcaption libass libbluray libjxl libmp3lame libopus libplacebo librist libssh libtheora libvpx libwebp libzmq lv2 libvpl openal liboapv libopencore-amrnb libopencore-amrwb libopenh264 libopenjpeg libopenmpt schannel sdl2 libsnappy libsoxr libsrt libsvtav1 libtwolame libuavs3d vaapi libvvenc libzimg libzvbi
  停用的有：avisynth libdavs2 libdvdread libdvdnav libfdk-aac frei0r librubberband libvidstab whisper libx264 libx265 libxavs2 libxvid，以及 libxcb、xlib、libpulse、libdrm 這些 BtbN 只在 Linux 建置的〔B4〕。其中 whisper 是 BtbN 目前在所有變體都停用（腳本的 `ffbuild_enabled` 一律回傳 -1），和授權無關〔B4〕。
- **和 ADR 的關係**：與 ADR 0006（Apache-2.0；隨包的第三方元件要在發布前盤點，並附上必要的授權文字）一致，這份研究替它補上 ffmpeg 部分的細節。與 ADR 0004（只發布免安裝版）也沒有衝突。

## 6. 未驗證與待確認

- **沒有實測解碼**：§4 的格式支援只是讀原始碼判斷，沒有執行下載回來的二進位檔。
- **原始碼的範圍**：靜態連入的 permissive 函式庫，是要附原始碼，還是只附聲明就夠？§2.3 b 採保守解讀。59 項各自的授權也還沒有逐一核對（交給 v01-48）。
- **原始碼包的大小**：FFmpeg 加上所有依賴的原始碼總共多大、放不放得進 GitHub Release 的單檔上限，都沒有量。BtbN 的 `download.sh` 會把每個依賴打包成 `.cache/downloads/<stage>_<hash>.tar.xz`〔B4〕，可能可以拿來產生原始碼包，但沒有試過（需要 docker）。
- **上游會不會消失**：LAME 的原始碼在 SourceForge SVN（`SCRIPT_REV="6835"`）〔B4〕，其他依賴多在 GitHub、GitLab。幾年後還拿不拿得到，無法保證；這是 §3.6 第 4 點要自己保存的理由。
- **shared 與 static 的大小**：只知道 zip 的大小（shared 73.5 MiB、static 163.6 MiB）〔B6〕，沒有比較只取 ffmpeg、ffprobe 加上必要 DLL 之後的大小。
- **自建最小 build**：沒有實際建過（§3.5）。
- **gyan.dev 訂製 LGPL build 的條件**：沒有詢問（§3.3）。
- **PyAV 自帶的 FFmpeg**：#17 說它是 GPL，本研究沒有查證（屬 #17 Q2）。

## 7. 來源（查閱日期一律為 2026-10-15）

| 代號 | 來源 | 用到的部分 |
|---|---|---|
| F1 | ffmpeg.org〈FFmpeg License and Legal Considerations〉 https://ffmpeg.org/legal.html | 授權概述、License Compliance Checklist 18 項、商標、Patent Mini-FAQ |
| F2 | ffmpeg.org〈Download FFmpeg〉 https://ffmpeg.org/download.html | 「FFmpeg only provides source code」、Windows 連結、版本與發布日、PGP 金鑰 |
| F3 | FFmpeg `LICENSE.md`（commit 2a571b6068） https://github.com/FFmpeg/FFmpeg/blob/2a571b606854520cf89804d8030c8b328e621689/LICENSE.md | GPL 部分、version3、外部函式庫、nonfree、IJG |
| F4 | FFmpeg `configure`（同上 commit） https://github.com/FFmpeg/FFmpeg/blob/2a571b606854520cf89804d8030c8b328e621689/configure | L97-102 授權選項；L2029-2064 外部函式庫授權清單；L4822-4850 授權判定；L3129-3140、L3735、L3750、L4837 `lgpl_gpl`；L4152-4293 GPL 濾鏡；L3120-3376 解碼器；L3914-4011 封裝格式；L3248 mjpeg |
| F5 | FFmpeg `fftools/opt_common.c` `show_license()` https://github.com/FFmpeg/FFmpeg/blob/2a571b606854520cf89804d8030c8b328e621689/fftools/opt_common.c#L79-L150 | `ffmpeg -L` 依 build 印出的授權文字 |
| F6 | FFmpeg `libavcodec/jrevdct.c` 檔頭 https://github.com/FFmpeg/FFmpeg/blob/2a571b606854520cf89804d8030c8b328e621689/libavcodec/jrevdct.c#L1-L37 | IJG 條款原文 |
| F7 | FFmpeg `libavcodec/Makefile` https://github.com/FFmpeg/FFmpeg/blob/2a571b606854520cf89804d8030c8b328e621689/libavcodec/Makefile#L108 | L108 fdctdsp → jfdctfst/jfdctint；L125 idctdsp → jrevdct |
| F8 | FFmpeg `libavcodec/x86/Makefile` L163-164 與 `flac_dsp_gpl.asm` L29 https://github.com/FFmpeg/FFmpeg/blob/2a571b606854520cf89804d8030c8b328e621689/libavcodec/x86/Makefile#L163-L164 | GPL 的 asm 只用在 FLAC 編碼器 |
| F9 | FFmpeg `libavformat/wavenc.c` L529 https://github.com/FFmpeg/FFmpeg/blob/2a571b606854520cf89804d8030c8b328e621689/libavformat/wavenc.c#L529 | WAV 預設音訊編碼 pcm_s16le |
| F10 | ffmpeg 文件〈Automatic stream selection〉 https://ffmpeg.org/ffmpeg.html#Automatic-stream-selection | 依輸出格式自動選串流 |
| F11 | GitHub compare `n9.0.2...2a571b6068` https://github.com/FFmpeg/FFmpeg/compare/n9.0.2...2a571b606854520cf89804d8030c8b328e621689 | 9.0 build 比 tag 多 17 個 commit |
| F12 | FFmpeg `libavcodec/codec_desc.c`（同上 commit） https://github.com/FFmpeg/FFmpeg/blob/2a571b606854520cf89804d8030c8b328e621689/libavcodec/codec_desc.c | `lgpl_gpl` 那幾個解碼器的完整名稱 |
| F13 | FFmpeg 文件：〈FFmpeg Filters〉、〈FFmpeg Formats〉、〈General Documentation〉。讀的是 B9 zip 隨附的 `doc/ffmpeg-filters.html`、`doc/ffmpeg-formats.html`、`doc/general.html`；線上版在 https://ffmpeg.org/ffmpeg-filters.html 、 https://ffmpeg.org/ffmpeg-formats.html 、 https://ffmpeg.org/general.html | rubberband（time-stretching and pitch-shifting）、vidstab、frei0r、dvdvideo、AviSynth、davs2／xavs2 的用途 |
| G1 | GNU GPL v3 https://www.gnu.org/licenses/gpl-3.0.txt | §1 Corresponding Source、§4、§5（含 aggregate）、§6 |
| G2 | GNU LGPL v3 https://www.gnu.org/licenses/lgpl-3.0.txt | 開頭（GPLv3 加上額外許可）、§0 定義、§4 Combined Works |
| G3 | GNU LGPL v2.1 https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt | §2 mere aggregation、§4 目的碼散布 |
| G4 | GNU GPL FAQ #MereAggregation https://www.gnu.org/licenses/gpl-faq.html#MereAggregation | 子行程、命令列參數通常是獨立程式 |
| G5 | GNU GPL FAQ #SourceAndBinaryOnDifferentSites https://www.gnu.org/licenses/gpl-faq.html#SourceAndBinaryOnDifferentSites | 原始碼放別的網站的條件 |
| G6 | GNU GPL FAQ #UnchangedJustBinary https://www.gnu.org/licenses/gpl-faq.html#UnchangedJustBinary | 轉散布下載來的二進位檔也要附原始碼 |
| G7 | GNU〈How to Use GNU Licenses for Your Own Software〉 https://www.gnu.org/licenses/gpl-howto.html | LGPL 要同時附 GPL 與 LGPL |
| B1 | BtbN `README.md`（commit 6c9aec5f） https://github.com/BtbN/FFmpeg-Builds/blob/6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b/README.md | 變體、addins、保留政策（L16-20）、支援的 Windows |
| B2 | BtbN `variants/`（同上 commit） https://github.com/BtbN/FFmpeg-Builds/tree/6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b/variants | `defaults-lgpl.sh`（`--enable-version3`、`COPYING.LGPLv3`）、`defaults-gpl.sh`、`win64-nonfree.sh` |
| B3 | BtbN `build.sh`（同上 commit） https://github.com/BtbN/FFmpeg-Builds/blob/6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b/build.sh | L40 clone 分支、L47 extra-version、L66 檔名、L71 LICENSE.txt |
| B4 | BtbN `scripts.d/`、`patches/`、`download.sh`（同上 commit） https://github.com/BtbN/FFmpeg-Builds/tree/6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b/scripts.d | GPL 專用依賴（`[[ $VARIANT == lgpl* ]] && return -1`）、fdk-aac 只在 nonfree、`SCRIPT_COMMIT`／`SCRIPT_REV` |
| B5 | BtbN Releases 列表 https://github.com/BtbN/FFmpeg-Builds/releases | 37 個 release，最舊的是 2024-11-30 |
| B6 | BtbN `autobuild-2026-09-30-13-08` https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-09-30-13-08 （含 `checksums.sha256`） | 檔名、大小、SHA-256、GitHub digest，沒有 nonfree |
| B7 | BtbN `latest` https://github.com/BtbN/FFmpeg-Builds/releases/tag/latest | 浮動檔名與每天更新 |
| B8 | BtbN workflow run 36713993443 https://github.com/BtbN/FFmpeg-Builds/actions/runs/36713993443 ；tag ref https://api.github.com/repos/BtbN/FFmpeg-Builds/git/ref/tags/autobuild-2026-09-30-13-08 | 2026-09-30 排程建置的 headSha 與 tag 都是 6c9aec5f |
| B9 | 本研究下載檢查 `ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-9.0.zip`（來自 B6） | SHA-256 比對；zip 內容；`LICENSE.txt` 與 F3 commit 的 `COPYING.LGPLv3` 逐位元組相同；以文字搜尋讀出 `ffmpeg.exe` 內嵌的 configure 行與授權字串（沒有執行二進位檔） |
| B10 | BtbN `LICENSE` https://github.com/BtbN/FFmpeg-Builds/blob/6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b/LICENSE | 建置腳本是 MIT 授權 |
| Y1 | gyan.dev〈FFmpeg Builds〉 https://www.gyan.dev/ffmpeg/builds/ （頁面版本 v59，2026-07-16） | 「licensed as GPLv3」、essentials 的函式庫、版本化網址與 `.sha256`、付費訂製 |
| Y2 | `GyanD/codexffmpeg` release 9.0.2 https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2 | 以版本號為 tag、asset digest |
| C1 | conda-forge `ffmpeg-feedstock` `recipe/meta.yaml`（commit e2c25db1） https://github.com/conda-forge/ffmpeg-feedstock/blob/e2c25db1f2572b9d6372cd5b3ce0013b31c36f66/recipe/meta.yaml | 預設 lgpl、官方 tarball、`-buildconf` 檢查 |
| C2 | anaconda.org API https://api.anaconda.org/package/conda-forge/ffmpeg/files | win-64 9.0.2 LGPL 套件的檔名、sha256、授權標示、依賴 |
| C3 | conda-forge `ffmpeg-feedstock` `recipe/build.sh`（同 C1 commit） https://github.com/conda-forge/ffmpeg-feedstock/blob/e2c25db1f2572b9d6372cd5b3ce0013b31c36f66/recipe/build.sh | L151-167 依 `license_family` 加 `--enable-gpl` 或 `--disable-gpl`；L193 一律 `--enable-version3`；有 win-64 專用分支 |
| M1 | MSYS2 `mingw-w64-ffmpeg/PKGBUILD`（commit a2c974c9） https://github.com/msys2/MINGW-packages/blob/a2c974c912d45495534b525bc0a84c91ef0718b8/mingw-w64-ffmpeg/PKGBUILD | 9.0.2，GPL-3.0-or-later，`--enable-gpl --enable-version3 --enable-libx264` |
| H1 | GitHub Docs〈Linking to releases〉 https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases | `releases/latest/download/` 指向最新的 release |
| H2 | GitHub Changelog 2025-06-03〈Releases now expose digests for release assets〉 https://github.blog/changelog/2025-06-03-releases-now-expose-digests-for-release-assets/ | release asset 的 SHA-256 digest |
| R1 | 本 repo `build_release.ps1`（main d3e617f） | L27 下載網址、L31-40 快取、L97-105 只複製兩個 exe |
| R2 | 本 repo `.github/workflows/release.yml`（main d3e617f） | L50-60 只上傳發布包 zip |
| R3 | `gh release list --repo Wade0325/AI_translate` | 沒有任何 Release |
| R4 | 本 repo `backend/app/utils/audio.py`、`backend/app/provider/local/asr.py`（main d3e617f） | app 實際呼叫的 ffmpeg／ffprobe 參數 |
