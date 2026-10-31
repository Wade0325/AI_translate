// AI_Translate 免安裝版的啟動器：以免安裝模式執行整套服務。
//
// 以 Windows 內建 csc 編譯（.NET Framework 4.x，各 Windows 10/11 皆預裝）：
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /optimize
//     /out:AI_Translate.exe tools\launcher.cs
// 注意：內建 csc 僅支援 C# 5 語法（無字串插值、無 ?. 運算子、無 nameof）。
//
// 職責：
//   1. 只允許單一實例：同一個資料夾的 exe 已在執行時，打開那個網址，不再起第二個伺服器（#268）
//   2. 首次啟動時以隨包 uv.exe 佈建 Python 依賴（含 torch，約 3.5 GB 下載）
//   3. 設定免安裝模式的環境變數 → 以隨包 Python 啟動 uvicorn（不載入使用者自己裝的套件，#301）
//   4. 探活 /api/v1/health 後開啟預設瀏覽器
//   5. 以 Job Object 綁定子行程：關閉視窗（或啟動器被殺）時 uvicorn 一併結束
//   6. 出錯時不讓視窗直接消失：說明原因、下一步與日誌位置，按任意鍵才關（#268）
//
// 日誌：啟動器自己的輸出寫進 data\logs\launcher-YYYY-MM-DD.log，留最近 7 天，和後端的
// app-YYYY-MM-DD.log（backend/app/utils/logger.py）放在一起；寫之前去識別：使用者家目錄寫成 ~，
// 路徑裡和帳號名稱相同的那一層寫成 %USERNAME%（ADR 0005）。伺服器與 uv 的輸出直接顯示在
// 視窗裡，不經過啟動器；伺服器自己寫 app-*.log。
//
// 測試用的環境變數（tests/integration/test_launcher.py，使用者不必設）：
//   AIT_LAUNCHER_HEALTH_TIMEOUT  等伺服器就緒的秒數，預設 180
//   AIT_LAUNCHER_NO_BROWSER=1    不開瀏覽器，網址照樣印在視窗裡

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

static class Launcher
{
    const string AppName = "AI_Translate";
    const string ExeName = "AI_Translate.exe";
    const string IssuesUrl = "https://github.com/Wade0325/AI_translate/issues";
    const int DefaultHealthTimeoutSeconds = 180; // 首次啟動 torch import 很慢
    const int SecondInstanceCloseSeconds = 5;

    static Process _server;
    static Mutex _instance;
    static string _urlFile;

    static int Main(string[] args)
    {
        try { Console.OutputEncoding = Encoding.UTF8; } catch (Exception) { }
        try { Console.Title = AppName; } catch (Exception) { }

        string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        try
        {
            return Run(root);
        }
        catch (LaunchFailure e)
        {
            Fail(e.Lines);
            return e.ExitCode;
        }
        catch (Exception e)
        {
            // 沒預料到的例外：原文與堆疊只寫進日誌，視窗裡印一句話與例外的類型
            Log.Detail("未預期的例外：" + e);
            Fail(new string[] {
                "啟動器發生未預期的錯誤（" + e.GetType().Name + "）：" + e.Message,
            });
            return 1;
        }
        finally
        {
            ReleaseInstance();
        }
    }

    static int Run(string root)
    {
        string python = Path.Combine(root, "runtime", "python.exe");
        string backend = Path.Combine(root, "backend");
        string dataDir = Path.Combine(root, "data");

        Log.Detail(string.Format(CultureInfo.InvariantCulture,
            "啟動器開始：版本 {0}，Windows {1}，.NET {2}，行程 {3}",
            ReadVersion(backend), WindowsVersion(), Environment.Version,
            Process.GetCurrentProcess().Id));
        Log.Detail("程式資料夾：" + root);

        if (!File.Exists(python) || !Directory.Exists(backend))
            throw new LaunchFailure(
                "找不到 runtime\\python.exe 或 backend\\：檔案不完整。",
                "請確認已把整個 zip 解壓縮（在 zip 上按右鍵 →「全部解壓縮」），再執行解壓後資料夾裡的 "
                    + ExeName + "；不要直接在 zip 裡雙擊。");

        CreateFolder(dataDir);
        // 伺服器的資料庫、上傳暫存與日誌都寫在 data：寫不進去時伺服器一定起不來，先在這裡說清楚
        CheckWritable(dataDir);
        Log.Start(Path.Combine(dataDir, "logs"));

        _urlFile = Path.Combine(dataDir, "launcher-url.txt");
        if (!AcquireInstance(root))
            return ShowRunningInstance();

        Provision(root, python);

        int port = PickPort(8000);
        string baseUrl = string.Format(CultureInfo.InvariantCulture, "http://127.0.0.1:{0}", port);
        WriteUrlFile(baseUrl);

        Log.Info("正在啟動 " + AppName + " 伺服器 (port " + port + ") ...");
        Log.Info("首次啟動需載入模型函式庫，可能需要一兩分鐘，請稍候。");

        IntPtr job = CreateKillOnCloseJob();

        var psi = new ProcessStartInfo();
        psi.FileName = python;
        // -s：不載入使用者自己裝的套件（%APPDATA%\Python\Python311\site-packages 與那裡的 .pth，
        // #301）。python311._pth 只開了隔離模式，沒有關掉使用者的 site-packages。不用 -I：它會
        // 連 PYTHON* 環境變數一起忽略，下面設的 PYTHONIOENCODING 就失效了。旗標要放在 -m 前面
        psi.Arguments = string.Format(CultureInfo.InvariantCulture,
            "-s -m uvicorn main:app --host 127.0.0.1 --port {0}", port);
        psi.WorkingDirectory = backend;
        psi.UseShellExecute = false; // 子行程直接沿用本 console 輸出日誌
        psi.EnvironmentVariables["APP_MODE"] = "standalone";
        psi.EnvironmentVariables["AIT_DATA_DIR"] = dataDir;
        psi.EnvironmentVariables["AIT_FFMPEG_DIR"] = Path.Combine(root, "bin");
        psi.EnvironmentVariables["AIT_STATIC_DIR"] = Path.Combine(root, "frontend", "dist");
        psi.EnvironmentVariables["HF_HOME"] = Path.Combine(dataDir, "models", "hf_cache");
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

        _server = StartProcess(psi, "runtime\\python.exe");
        if (job != IntPtr.Zero)
            AssignProcessToJobObject(job, _server.Handle);

        int timeout = HealthTimeoutSeconds();
        DateTime started = DateTime.UtcNow;
        Health health = WaitForHealth(baseUrl + "/api/v1/health", timeout);
        if (health == Health.Exited)
            throw new LaunchFailure(
                "伺服器還沒就緒就結束了（結束代碼 " + ExitCodeText(_server.ExitCode) + "）。",
                "上方視窗裡伺服器印出的最後幾行通常就是原因。");
        if (health == Health.TimedOut)
            throw new LaunchFailure(
                "伺服器在 " + timeout + " 秒內沒有就緒，已經停止它。",
                "電腦較慢，或防毒軟體正在掃描剛下載的套件時，第一次啟動可能超過這個時間：請再執行一次 "
                    + ExeName + "。",
                "一直如此的話，請看上方視窗裡伺服器印出的訊息。");

        Log.Detail(string.Format(CultureInfo.InvariantCulture,
            "伺服器在 {0:0} 秒後就緒", (DateTime.UtcNow - started).TotalSeconds));
        Console.WriteLine();
        Log.Info("伺服器已就緒：" + baseUrl);
        Log.Info("關閉此視窗即停止 " + AppName + "。");
        OpenBrowser(baseUrl);

        _server.WaitForExit();
        // 就緒之後伺服器不會自己結束：關閉視窗或 Ctrl+C 時啟動器會跟著被結束，走不到這裡
        int code = _server.ExitCode;
        var failure = new LaunchFailure(
            "伺服器意外停止了（結束代碼 " + ExitCodeText(code) + "）。",
            "如果有進行中的轉錄，它已經中斷；重新執行 " + ExeName + " 之後會記成失敗，可以再重新轉錄。",
            "上方視窗裡伺服器印出的最後幾行通常就是原因。");
        failure.ExitCode = code != 0 ? code : 1;
        throw failure;
    }

    // ─── 出錯時：說明原因與日誌位置，按任意鍵才關 ─────────────────────────

    static void Fail(string[] lines)
    {
        // 先讓出單一實例：使用者在這個視窗還停著時再雙擊，可以直接重新啟動
        StopServer();
        ReleaseInstance();

        Console.Error.WriteLine();
        foreach (string line in lines)
            Log.Error(line);
        Console.Error.WriteLine();
        if (Log.Folder != null)
        {
            Log.Error("日誌在：" + Log.Folder);
            Log.Error("（launcher-日期.log 是啟動器的，app-日期.log 是伺服器的）");
            Log.Error("需要協助時，請到 " + IssuesUrl + " 回報，並附上這個資料夾裡今天的日誌檔。");
        }
        else
        {
            Log.Error("日誌沒有寫成：" + (Log.Problem ?? "還沒開始寫日誌就出錯了").TrimEnd('。', '.') + "。");
            Log.Error("需要協助時，請到 " + IssuesUrl + " 回報，並附上這個視窗的內容。");
        }
        Pause();
    }

    static void StopServer()
    {
        try
        {
            if (_server != null && !_server.HasExited)
                _server.Kill();
        }
        catch (Exception) { }
    }

    static void Pause()
    {
        Console.WriteLine("按任意鍵關閉...");
        try
        {
            // 先丟掉出錯之前就按下的鍵（例如等佈建時按過 Enter），免得訊息一出現視窗就關掉
            while (Console.KeyAvailable)
                Console.ReadKey(true);
            Console.ReadKey(true);
        }
        catch (Exception) { }
    }

    static string ExitCodeText(int code)
    {
        uint value = unchecked((uint)code);
        if (value < 0xC0000000)
            return code.ToString(CultureInfo.InvariantCulture);
        // Windows 的例外狀態碼：十進位看不出是什麼，補上十六進位與常見幾種的意思
        string text = string.Format(CultureInfo.InvariantCulture, "0x{0:X8}", value);
        string meaning = null;
        switch (value)
        {
            case 0xC0000005: meaning = "記憶體存取違規"; break;
            case 0xC0000017: meaning = "記憶體不足"; break;
            case 0xC00000FD: meaning = "堆疊溢位"; break;
            case 0xC0000135: meaning = "找不到需要的 DLL"; break;
            case 0xC000013A: meaning = "被 Ctrl+C 中斷"; break;
            case 0xC0000409: meaning = "程式自行緊急中止"; break;
        }
        return meaning == null ? text : text + "，" + meaning;
    }

    // ─── 單一實例 ─────────────────────────────────────────────────────────
    // 以程式資料夾的路徑命名 mutex：同一份解壓的資料夾只能跑一個，另一個資料夾（例如舊版）不受影響。
    // 第一個實例把網址寫進 data\launcher-url.txt，第二個實例讀它、確認伺服器在回應後打開那個網址

    static bool AcquireInstance(string root)
    {
        string name = "Local\\" + AppName + "-launcher-" + PathHash(root);
        bool createdNew;
        Mutex mutex;
        try
        {
            mutex = new Mutex(true, name, out createdNew);
        }
        catch (UnauthorizedAccessException)
        {
            return false; // 另一個實例建立的 mutex 打不開：當成已在執行
        }
        if (!createdNew)
        {
            bool owned;
            try { owned = mutex.WaitOne(0); }
            catch (AbandonedMutexException) { owned = true; } // 上一個實例沒收尾就結束了
            if (!owned)
            {
                mutex.Close();
                return false;
            }
        }
        _instance = mutex;
        return true;
    }

    static void ReleaseInstance()
    {
        if (_instance == null)
            return;
        try { if (_urlFile != null) File.Delete(_urlFile); } catch (Exception) { }
        try { _instance.ReleaseMutex(); } catch (Exception) { }
        _instance.Close();
        _instance = null;
    }

    static string PathHash(string path)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(
            Path.GetFullPath(path).TrimEnd('\\', '/').ToUpperInvariant());
        using (var sha = SHA256.Create())
        {
            byte[] hash = sha.ComputeHash(bytes);
            var text = new StringBuilder();
            for (int i = 0; i < 8; i++)
                text.Append(hash[i].ToString("x2", CultureInfo.InvariantCulture));
            return text.ToString();
        }
    }

    static void WriteUrlFile(string url)
    {
        try
        {
            File.WriteAllText(_urlFile, url);
        }
        catch (Exception e)
        {
            // 寫不進去只影響第二次雙擊時打開的網址，照樣啟動
            Log.Detail("無法寫入 " + _urlFile + "：" + e.Message);
        }
    }

    static int ShowRunningInstance()
    {
        string url = ReadUrlFile();
        Log.Detail("已有實例在執行；記下的網址：" + (url ?? "（沒有）"));
        if (url != null && Probe(url + "/api/v1/health"))
        {
            Log.Info(AppName + " 已經在執行，不會再啟動第二個。");
            Log.Info("已在瀏覽器開啟：" + url);
            OpenBrowser(url);
            Console.WriteLine("這個視窗 " + SecondInstanceCloseSeconds + " 秒後自動關閉。");
            Thread.Sleep(SecondInstanceCloseSeconds * 1000);
            return 0;
        }
        Log.Info(AppName + " 已經在另一個視窗啟動中，不會再啟動第二個。");
        Log.Info("首次佈建可能要數分鐘到數十分鐘；就緒後那個視窗會自動開啟瀏覽器，請切換到那個視窗查看進度。");
        Pause();
        return 0;
    }

    static string ReadUrlFile()
    {
        try
        {
            string url = File.ReadAllText(_urlFile).Trim();
            // 只接受啟動器自己寫的格式，不打開檔案裡的任意網址
            const string prefix = "http://127.0.0.1:";
            int port;
            if (url.StartsWith(prefix, StringComparison.Ordinal)
                && int.TryParse(url.Substring(prefix.Length), NumberStyles.None,
                                CultureInfo.InvariantCulture, out port)
                && port > 0 && port < 65536)
                return url;
        }
        catch (Exception) { }
        return null;
    }

    static void OpenBrowser(string url)
    {
        if (Environment.GetEnvironmentVariable("AIT_LAUNCHER_NO_BROWSER") == "1")
            return;
        try
        {
            Process.Start(url);
        }
        catch (Exception e)
        {
            Log.Detail("無法開啟瀏覽器：" + e.Message);
            Log.Info("無法自動開啟瀏覽器，請自己在瀏覽器開啟 " + url);
        }
    }

    // ─── 首次佈建 ─────────────────────────────────────────────────────────

    static void Provision(string root, string python)
    {
        string sentinel = Path.Combine(root, "runtime", ".provisioned");
        if (File.Exists(sentinel))
            return;

        string uv = Path.Combine(root, "bin", "uv.exe");
        string requirements = Path.Combine(root, "backend", "requirements-standalone.txt");
        if (!File.Exists(uv) || !File.Exists(requirements))
            throw new LaunchFailure(
                "找不到 bin\\uv.exe 或 backend\\requirements-standalone.txt：檔案不完整。",
                "請重新解壓縮整個 zip；防毒軟體隔離了 uv.exe 時，請到隔離區還原，"
                    + "並把這個資料夾加入防毒軟體的排除清單。");

        Log.Info("═══════════════════════════════════════════════════════");
        Log.Info(" 首次啟動：正在下載執行環境（約 3.5 GB，含 PyTorch）");
        Log.Info(" 過程視網速需要數分鐘到數十分鐘；中斷後重開會續傳。");
        Log.Info(" 沒有 NVIDIA 顯卡的電腦也會下載這些，只用 Gemini 時大部分用不到。");
        Log.Info("═══════════════════════════════════════════════════════");
        Log.Detail("首次佈建開始；可用空間：" + FreeSpaceText(root));

        var psi = new ProcessStartInfo();
        psi.FileName = uv;
        psi.Arguments = string.Format(
            "pip install --python \"{0}\" --target \"{1}\" -r \"{2}\"",
            python,
            Path.Combine(root, "runtime", "Lib", "site-packages"),
            requirements);
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false; // 進度直接顯示在本 console

        DateTime started = DateTime.UtcNow;
        Process p = StartProcess(psi, "bin\\uv.exe");
        p.WaitForExit();
        Log.Detail(string.Format(CultureInfo.InvariantCulture,
            "uv 結束，代碼 {0}，花了 {1:0} 秒；可用空間：{2}",
            p.ExitCode, (DateTime.UtcNow - started).TotalSeconds, FreeSpaceText(root)));
        if (p.ExitCode != 0)
            throw new LaunchFailure(
                "執行環境佈建失敗（uv 結束代碼 " + ExitCodeText(p.ExitCode) + "）。"
                    + "上方視窗裡 uv 印出的最後幾行通常就是原因。常見的原因：",
                "  1. 網路中斷或不穩：已下載的部分會保留，重新執行 " + ExeName + " 即可續傳。",
                "  2. 磁碟空間不足：目前 " + FreeSpaceText(root) + "；清出空間後再試。",
                "  3. 防毒軟體攔下了下載或解壓的檔案：把這個資料夾加入防毒軟體的排除清單後再試。",
                "  4. 公司或學校的網路擋了下載（防火牆、代理伺服器）：換一個網路再試。",
                "  5. 資料夾的路徑太長：把整個資料夾移到較短的路徑（例如 D:\\AI_Translate）後再試。");

        WriteFile(sentinel, DateTime.Now.ToString("o", CultureInfo.InvariantCulture));
        Log.Info("執行環境佈建完成。");
    }

    // 程式資料夾所在的磁碟，以及 uv 放下載快取的磁碟（%LOCALAPPDATA%\uv\cache）
    static string FreeSpaceText(string root)
    {
        var drives = new List<string>();
        var parts = new List<string>();
        foreach (string path in new string[] {
            root, Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) })
        {
            string drive;
            try { drive = Path.GetPathRoot(Path.GetFullPath(path)); }
            catch (Exception) { continue; }
            if (string.IsNullOrEmpty(drive) || drives.Contains(drive.ToUpperInvariant()))
                continue;
            drives.Add(drive.ToUpperInvariant());
            try
            {
                long free = new DriveInfo(drive).AvailableFreeSpace;
                parts.Add(string.Format(CultureInfo.InvariantCulture,
                    "{0} 剩 {1:0.0} GB 可用", drive.TrimEnd('\\'), free / 1073741824.0));
            }
            catch (Exception) { }
        }
        return parts.Count > 0 ? string.Join("、", parts.ToArray()) : "（查不到）";
    }

    // ─── 檔案與行程：失敗時用中文說明是哪個路徑、為什麼 ───────────────────

    static void CreateFolder(string path)
    {
        try
        {
            Directory.CreateDirectory(path);
        }
        catch (Exception e)
        {
            if (!IsIoProblem(e))
                throw;
            throw IoFailure("無法建立資料夾：" + path, e);
        }
    }

    static void CheckWritable(string folder)
    {
        string probe = Path.Combine(folder, ".launcher-write-test");
        try
        {
            File.WriteAllText(probe, "");
            File.Delete(probe);
        }
        catch (Exception e)
        {
            if (!IsIoProblem(e))
                throw;
            throw IoFailure("無法寫入資料夾：" + folder, e);
        }
    }

    static void WriteFile(string path, string content)
    {
        try
        {
            File.WriteAllText(path, content);
        }
        catch (Exception e)
        {
            if (!IsIoProblem(e))
                throw;
            throw IoFailure("無法寫入檔案：" + path, e);
        }
    }

    static bool IsIoProblem(Exception e)
    {
        return e is IOException || e is UnauthorizedAccessException || e is NotSupportedException
            || e is System.Security.SecurityException;
    }

    static LaunchFailure IoFailure(string what, Exception e)
    {
        Log.Detail(what + "：" + e.GetType().Name + "：" + e.Message);
        string[] reason = IoReason(e);
        return new LaunchFailure(what, "原因：" + reason[0], reason[1]);
    }

    // 回傳 {原因, 下一步}
    static string[] IoReason(Exception e)
    {
        const string move = "請把整個資料夾移到可以寫入的位置（例如 D:\\AI_Translate），不要放在 C:\\Program Files 底下，再重新執行。";
        if (e is UnauthorizedAccessException || e is System.Security.SecurityException)
            return new string[] { "沒有寫入權限（存取被拒）。", move };
        if (e is PathTooLongException)
            return new string[] { "路徑太長。", "請把整個資料夾移到較短的路徑（例如 D:\\AI_Translate）後再試。" };
        if (e is DriveNotFoundException || e is DirectoryNotFoundException)
            return new string[] { "上層資料夾或磁碟不存在（隨身碟或網路磁碟被移除了嗎？）。", move };
        switch (Marshal.GetHRForException(e) & 0xFFFF)
        {
            case 39:  // ERROR_HANDLE_DISK_FULL
            case 112: // ERROR_DISK_FULL
                return new string[] { "磁碟空間不足。", "請清出磁碟空間後再試。" };
            case 32:  // ERROR_SHARING_VIOLATION
            case 33:  // ERROR_LOCK_VIOLATION
                return new string[] { "檔案被其他程式占用（例如防毒軟體正在掃描）。", "請稍等一下再試，或重新開機後再試。" };
            case 80:  // ERROR_FILE_EXISTS
            case 183: // ERROR_ALREADY_EXISTS
                return new string[] { "那個位置已經有一個同名的檔案。", "請把那個檔案改名或移走後再試。" };
            case 19:  // ERROR_WRITE_PROTECT
                return new string[] { "磁碟有寫入保護。", move };
        }
        return new string[] { e.Message, move };
    }

    static Process StartProcess(ProcessStartInfo psi, string shownName)
    {
        try
        {
            return Process.Start(psi);
        }
        catch (Win32Exception e)
        {
            Log.Detail("無法執行 " + psi.FileName + "：錯誤 " + e.NativeErrorCode + "：" + e.Message);
            string reason;
            switch (e.NativeErrorCode)
            {
                case 2:    reason = "檔案不見了"; break; // ERROR_FILE_NOT_FOUND
                case 5:    reason = "存取被拒"; break; // ERROR_ACCESS_DENIED
                case 225:  reason = "防毒軟體判定它有病毒而攔下"; break; // ERROR_VIRUS_INFECTED
                case 1260: reason = "被系統原則封鎖"; break; // ERROR_ACCESS_DISABLED_BY_POLICY
                case 4551: reason = "被應用程式控制原則（例如「智慧型應用程式控制」）封鎖"; break;
                default:   reason = e.Message; break;
            }
            throw new LaunchFailure(
                "無法執行 " + shownName + "：" + reason + "（錯誤 " + e.NativeErrorCode + "）。",
                "防毒軟體可能隔離或攔下了它：請到防毒軟體的隔離區還原，並把這個資料夾加入排除清單；"
                    + "或重新解壓縮整個 zip。");
        }
    }

    // Environment.OSVersion 在沒有宣告支援 Windows 10 的 exe 裡會被降成 6.2.9200（Windows 8），
    // 日誌要的是真正的版本：RtlGetVersion 不受相容性設定影響
    static string WindowsVersion()
    {
        try
        {
            var info = new OSVERSIONINFOEX();
            info.dwOSVersionInfoSize = Marshal.SizeOf(typeof(OSVERSIONINFOEX));
            if (RtlGetVersion(ref info) == 0)
                return string.Format(CultureInfo.InvariantCulture, "{0}.{1}.{2}",
                    info.dwMajorVersion, info.dwMinorVersion, info.dwBuildNumber);
        }
        catch (Exception) { }
        return Environment.OSVersion.Version.ToString();
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct OSVERSIONINFOEX
    {
        public int dwOSVersionInfoSize, dwMajorVersion, dwMinorVersion, dwBuildNumber, dwPlatformId;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
        public string szCSDVersion;
        public ushort wServicePackMajor, wServicePackMinor, wSuiteMask;
        public byte wProductType, wReserved;
    }

    [DllImport("ntdll.dll")]
    static extern int RtlGetVersion(ref OSVERSIONINFOEX info);

    static string ReadVersion(string backend)
    {
        try { return File.ReadAllText(Path.Combine(backend, "VERSION")).Trim(); }
        catch (Exception) { return "dev"; }
    }

    // ─── 埠選擇與探活 ─────────────────────────────────────────────────────

    static int PickPort(int preferred)
    {
        try
        {
            var probe = new TcpListener(IPAddress.Loopback, preferred);
            probe.Start();
            probe.Stop();
            return preferred;
        }
        catch (SocketException)
        {
            // 慣用埠被占：拿一個系統分配的空埠（前端 API/WS 都是相對路徑，任意埠皆可）
            var any = new TcpListener(IPAddress.Loopback, 0);
            any.Start();
            int port = ((IPEndPoint)any.LocalEndpoint).Port;
            any.Stop();
            return port;
        }
    }

    static int HealthTimeoutSeconds()
    {
        int seconds;
        string text = Environment.GetEnvironmentVariable("AIT_LAUNCHER_HEALTH_TIMEOUT");
        if (int.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out seconds)
            && seconds > 0)
            return seconds;
        return DefaultHealthTimeoutSeconds;
    }

    enum Health { Ready, Exited, TimedOut }

    static Health WaitForHealth(string url, int timeoutSeconds)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            if (_server.HasExited)
                return Health.Exited;
            if (Probe(url))
                return Health.Ready;
            Thread.Sleep(1500);
        }
        // 最後一次探活與逾時之間結束的，也算提早結束：結束代碼比「逾時」更有用
        return _server.HasExited ? Health.Exited : Health.TimedOut;
    }

    static bool Probe(string url)
    {
        try
        {
            var req = (HttpWebRequest)WebRequest.Create(url);
            req.Timeout = 2000;
            req.Proxy = null; // 本機位址不經過系統的代理伺服器
            using (var resp = (HttpWebResponse)req.GetResponse())
                return (int)resp.StatusCode == 200;
        }
        catch (WebException) { return false; }
    }

    // ─── Job Object：確保關閉啟動器（含被強殺）時子行程一併結束 ─────────

    [StructLayout(LayoutKind.Sequential)]
    struct IO_COUNTERS
    {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    const int JobObjectExtendedLimitInformation = 9;
    const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr CreateJobObject(IntPtr attrs, string name);

    [DllImport("kernel32.dll")]
    static extern bool SetInformationJobObject(
        IntPtr job, int infoClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint size);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    static IntPtr CreateKillOnCloseJob()
    {
        try
        {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero)
                return IntPtr.Zero;
            var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            SetInformationJobObject(
                job, JobObjectExtendedLimitInformation, ref info,
                (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)));
            return job;
        }
        catch (Exception)
        {
            return IntPtr.Zero;
        }
    }
}

// 啟動失敗：每一行都是給使用者看的中文，Main 印出來、寫進日誌，再停下來等按鍵
class LaunchFailure : Exception
{
    public readonly string[] Lines;
    public int ExitCode = 1;

    public LaunchFailure(params string[] lines) : base(string.Join(" ", lines))
    {
        Lines = lines;
    }
}

// 啟動器的日誌：data\logs\launcher-YYYY-MM-DD.log（UTF-8），留最近 7 天。
// Start 之前的內容先留在記憶體，開始寫時一起補上。每一行都開檔、寫入、關檔：
// 第二個實例會寫同一個檔，啟動器的輸出也少，不必一直開著。
static class Log
{
    const string Prefix = "launcher-";
    const string Suffix = ".log";
    const int KeepDays = 7;

    static readonly List<string> _pending = new List<string>();
    static readonly string _source = "[launcher " + Process.GetCurrentProcess().Id + "]";
    static Regex _home = HomePattern(HomeFolder());
    static Regex _user = UserPattern(UserName());

    /// 日誌資料夾；還沒開始寫或寫不進去時是 null
    public static string Folder;
    /// 寫不進日誌的原因
    public static string Problem;

    public static void Start(string folder)
    {
        try
        {
            Directory.CreateDirectory(folder);
            Folder = folder;
            RemoveExpired(folder, DateTime.Now.Date);
        }
        catch (Exception e)
        {
            Folder = null;
            Problem = "無法建立 " + folder + "：" + e.Message;
            _pending.Clear();
            Console.Error.WriteLine("注意：日誌檔寫不進去，只顯示在這個視窗。" + Problem);
            return;
        }
        foreach (string line in _pending)
            Append(line);
        _pending.Clear();
        Detail("日誌檔寫在 " + folder);
    }

    /// 印在視窗並寫進日誌
    public static void Info(string message)
    {
        Console.WriteLine(message);
        Write("INFO", message);
    }

    /// 印在視窗的錯誤輸出並寫進日誌
    public static void Error(string message)
    {
        Console.Error.WriteLine(message);
        Write("ERROR", message);
    }

    /// 只寫進日誌
    public static void Detail(string message)
    {
        Write("INFO", message);
    }

    static void Write(string level, string message)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)
            + " - " + level + " - " + _source + " - " + Deidentify(message);
        if (Folder == null)
        {
            if (Problem == null)
                _pending.Add(line);
            return;
        }
        Append(line);
    }

    static void Append(string line)
    {
        string path = Path.Combine(Folder,
            Prefix + DateTime.Now.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) + Suffix);
        try
        {
            using (var stream = new FileStream(path, FileMode.Append, FileAccess.Write,
                                               FileShare.ReadWrite | FileShare.Delete))
            using (var writer = new StreamWriter(stream, new UTF8Encoding(false)))
                writer.WriteLine(line);
        }
        catch (Exception) { } // 寫不進日誌不影響啟動
    }

    // 刪掉超過保留天數的日誌檔：今天和前 KeepDays - 1 天的留著；名稱不是日誌檔的不動
    static void RemoveExpired(string folder, DateTime today)
    {
        DateTime oldestKept = today.AddDays(-(KeepDays - 1));
        foreach (string path in Directory.GetFiles(folder, Prefix + "*" + Suffix))
        {
            string name = Path.GetFileName(path);
            string day = name.Substring(Prefix.Length, name.Length - Prefix.Length - Suffix.Length);
            DateTime date;
            if (!DateTime.TryParseExact(day, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                                        DateTimeStyles.None, out date))
                continue;
            if (date < oldestKept)
            {
                try { File.Delete(path); }
                catch (Exception) { } // 刪不掉（例如被別的程式開著）下次再刪
            }
        }
    }

    // ─── 去識別 ───────────────────────────────────────────────────────────

    public static string Deidentify(string text)
    {
        if (_home != null)
            text = _home.Replace(text, "~");
        if (_user != null)
            text = _user.Replace(text, "%USERNAME%");
        return text;
    }

    // 和後端一樣以 USERPROFILE 為家目錄（Python 的 Path.home() 也讀它）
    static string HomeFolder()
    {
        string home = Environment.GetEnvironmentVariable("USERPROFILE");
        if (string.IsNullOrEmpty(home))
            home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return home;
    }

    static string UserName()
    {
        string name = Environment.GetEnvironmentVariable("USERNAME");
        if (string.IsNullOrEmpty(name))
            name = Environment.UserName;
        return name;
    }

    // 比對路徑裡的家目錄：\ 與 / 都算分隔符號，連續的 \\ 也算（例外訊息裡的跳脫），不分大小寫；
    // 家目錄是根目錄時不比對。和後端的 _home_pattern（backend/app/utils/logger.py）相同，另外要求
    // 前後是路徑的邊界：/tmp/x/root 裡的 /root、C:\Users\wade 裡的 C:\Users\wa 都不算
    static Regex HomePattern(string home)
    {
        if (string.IsNullOrEmpty(home))
            return null;
        var parts = new List<string>();
        foreach (string part in Regex.Split(home, @"[\\/]"))
            if (part.Length > 0)
                parts.Add(Regex.Escape(part));
        bool rooted = home[0] == '/' || home[0] == '\\';
        if (parts.Count == 0 || (parts.Count == 1 && !rooted))
            return null;
        const string separator = @"[\\/]+";
        return new Regex(@"(?<![\w.\-])" + (rooted ? separator : "")
                             + string.Join(separator, parts.ToArray()) + NameEnd,
                         RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    }

    // 資料夾名稱到這裡結束：後面不是名稱裡的字（句尾的句號不算名稱）
    const string NameEnd = @"(?![\w\-]|\.[\w\-])";

    // 路徑裡和帳號名稱相同的一整層（例如 D:\王小明\AI_Translate 的「王小明」）
    static Regex UserPattern(string user)
    {
        if (string.IsNullOrEmpty(user))
            return null;
        return new Regex(@"(?<=[\\/])" + Regex.Escape(user) + NameEnd,
                         RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    }
}
