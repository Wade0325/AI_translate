// AI_Translate 免安裝啟動器（standalone 模式）。
//
// 以 Windows 內建 csc 編譯（.NET Framework 4.x，各 Windows 10/11 皆預裝）：
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /optimize
//     /out:AI_Translate.exe tools\launcher.cs
// 注意：內建 csc 僅支援 C# 5 語法（無字串插值、無 ?. 運算子）。
//
// 職責：
//   1. 首次啟動時以隨包 uv.exe 佈建 Python 依賴（含 torch，約 3.5 GB 下載）
//   2. 設定 standalone 環境變數 → 以隨包 Python 啟動 uvicorn
//   3. 探活 /api/v1/health 後開啟預設瀏覽器
//   4. 以 Job Object 綁定子行程：關閉視窗（或啟動器被殺）時 uvicorn 一併結束

using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

static class Launcher
{
    const int HealthTimeoutSeconds = 180; // 首次啟動 torch import 很慢

    static Process _server;

    static int Main(string[] args)
    {
        try { Console.OutputEncoding = Encoding.UTF8; } catch (Exception) { }
        Console.Title = "AI_Translate";

        string root = Path.GetDirectoryName(
            System.Reflection.Assembly.GetExecutingAssembly().Location);
        string python = Path.Combine(root, "runtime", "python.exe");
        string backend = Path.Combine(root, "backend");
        string dataDir = Path.Combine(root, "data");

        if (!File.Exists(python) || !Directory.Exists(backend))
        {
            Console.Error.WriteLine("找不到 runtime\\python.exe 或 backend\\ — 請確認 zip 已完整解壓。");
            Pause();
            return 1;
        }

        Directory.CreateDirectory(dataDir);

        if (!Provision(root, python))
        {
            Console.Error.WriteLine();
            Console.Error.WriteLine("執行環境佈建失敗（多半是網路中斷）。已下載的部分會保留，");
            Console.Error.WriteLine("重新執行 AI_Translate.exe 即可續傳。");
            Pause();
            return 1;
        }

        int port = PickPort(8000);
        string baseUrl = string.Format("http://127.0.0.1:{0}", port);

        Console.WriteLine("正在啟動 AI_Translate 伺服器 (port " + port + ") ...");
        Console.WriteLine("首次啟動需載入模型函式庫，可能需要一兩分鐘，請稍候。");

        IntPtr job = CreateKillOnCloseJob();

        var psi = new ProcessStartInfo();
        psi.FileName = python;
        psi.Arguments = string.Format(
            "-m uvicorn main:app --host 127.0.0.1 --port {0}", port);
        psi.WorkingDirectory = backend;
        psi.UseShellExecute = false; // 子行程直接沿用本 console 輸出日誌
        psi.EnvironmentVariables["APP_MODE"] = "standalone";
        psi.EnvironmentVariables["AIT_DATA_DIR"] = dataDir;
        psi.EnvironmentVariables["AIT_FFMPEG_DIR"] = Path.Combine(root, "bin");
        psi.EnvironmentVariables["AIT_STATIC_DIR"] = Path.Combine(root, "frontend", "dist");
        psi.EnvironmentVariables["HF_HOME"] = Path.Combine(dataDir, "models", "hf_cache");
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

        _server = Process.Start(psi);
        if (job != IntPtr.Zero)
            AssignProcessToJobObject(job, _server.Handle);

        if (!WaitForHealth(baseUrl + "/api/v1/health", HealthTimeoutSeconds))
        {
            Console.Error.WriteLine("伺服器在 " + HealthTimeoutSeconds + " 秒內未就緒，請檢視上方日誌。");
            try { if (!_server.HasExited) _server.Kill(); } catch (Exception) { }
            Pause();
            return 1;
        }

        Console.WriteLine();
        Console.WriteLine("伺服器已就緒：" + baseUrl);
        Console.WriteLine("關閉此視窗即停止 AI_Translate。");
        try { Process.Start(baseUrl); } catch (Exception) { }

        _server.WaitForExit();
        return _server.ExitCode;
    }

    // ─── 首次佈建 ─────────────────────────────────────────────────────────

    static bool Provision(string root, string python)
    {
        string sentinel = Path.Combine(root, "runtime", ".provisioned");
        if (File.Exists(sentinel))
            return true;

        string uv = Path.Combine(root, "bin", "uv.exe");
        string requirements = Path.Combine(root, "backend", "requirements-standalone.txt");
        if (!File.Exists(uv) || !File.Exists(requirements))
        {
            Console.Error.WriteLine("找不到 bin\\uv.exe 或 backend\\requirements-standalone.txt。");
            return false;
        }

        Console.WriteLine("═══════════════════════════════════════════════════════");
        Console.WriteLine(" 首次啟動：正在下載執行環境（約 3.5 GB，含 PyTorch）");
        Console.WriteLine(" 過程視網速需要數分鐘到數十分鐘；中斷後重開會續傳。");
        Console.WriteLine("═══════════════════════════════════════════════════════");

        var psi = new ProcessStartInfo();
        psi.FileName = uv;
        psi.Arguments = string.Format(
            "pip install --python \"{0}\" --target \"{1}\" -r \"{2}\"",
            python,
            Path.Combine(root, "runtime", "Lib", "site-packages"),
            requirements);
        psi.WorkingDirectory = root;
        psi.UseShellExecute = false; // 進度直接顯示在本 console

        Process p = Process.Start(psi);
        p.WaitForExit();
        if (p.ExitCode != 0)
            return false;

        File.WriteAllText(sentinel, DateTime.Now.ToString("o"));
        Console.WriteLine("執行環境佈建完成。");
        return true;
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

    static bool WaitForHealth(string url, int timeoutSeconds)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            if (_server != null && _server.HasExited)
                return false;
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(url);
                req.Timeout = 2000;
                using (var resp = (HttpWebResponse)req.GetResponse())
                {
                    if ((int)resp.StatusCode == 200)
                        return true;
                }
            }
            catch (WebException) { }
            Thread.Sleep(1500);
        }
        return false;
    }

    static void Pause()
    {
        Console.WriteLine("按任意鍵關閉...");
        try { Console.ReadKey(true); } catch (Exception) { }
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
