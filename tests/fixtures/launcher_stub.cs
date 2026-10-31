// 啟動器測試用的替身（tests/integration/test_launcher.py）：放在假的程式資料夾裡，
// 改名成 runtime\python.exe 時假裝是伺服器，改名成 bin\uv.exe 時假裝是首次佈建的 uv。
// 和啟動器一樣用內建 csc 編譯，只能用 C# 5 語法。
//
// 每次被執行都在程式資料夾（替身的上一層）的 stub-calls.txt 記一行：名稱、行程編號、參數。
//
// 伺服器的行為照環境變數 LAUNCHER_STUB_SERVER：
//   exit:N             馬上以代碼 N 結束（還沒就緒就結束）
//   hang               一直不回應就緒檢查（等啟動器逾時後停掉它）
//   serve              回應 /api/v1/health，一直跑到被停掉
//   serve-then-exit:N  回應第一次就緒檢查之後，以代碼 N 結束（就緒後崩潰）
// uv 以 LAUNCHER_STUB_UV_EXIT 的代碼結束，沒設時是 0。
// 輸出只用 ASCII，不受主控台碼頁影響。替身最多跑 60 秒，測試出錯時也不會一直留著。

using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading;

static class LauncherStub
{
    const int MaxSeconds = 60;

    static int Main(string[] args)
    {
        string exe = Assembly.GetExecutingAssembly().Location;
        string name = Path.GetFileNameWithoutExtension(exe).ToLowerInvariant();
        string root = Path.GetDirectoryName(Path.GetDirectoryName(exe));
        File.AppendAllText(Path.Combine(root, "stub-calls.txt"),
            name + " " + System.Diagnostics.Process.GetCurrentProcess().Id + " "
                + string.Join(" ", args) + Environment.NewLine);

        if (name == "uv")
        {
            int code = ParseInt(Environment.GetEnvironmentVariable("LAUNCHER_STUB_UV_EXIT"), 0);
            Console.Error.WriteLine("stub uv: exit " + code);
            return code;
        }

        string mode = Environment.GetEnvironmentVariable("LAUNCHER_STUB_SERVER") ?? "serve";
        if (mode.StartsWith("exit:"))
        {
            Console.Error.WriteLine("stub server: failed to start");
            return ParseInt(mode.Substring(5), 1);
        }
        if (mode == "hang")
        {
            Thread.Sleep(MaxSeconds * 1000);
            return 99;
        }
        int exitAfterServing = -1;
        if (mode.StartsWith("serve-then-exit:"))
            exitAfterServing = ParseInt(mode.Substring("serve-then-exit:".Length), 1);
        return Serve(Port(args), exitAfterServing);
    }

    static int Serve(int port, int exitAfterServing)
    {
        var listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        Console.WriteLine("stub server: listening on " + port);
        DateTime deadline = DateTime.UtcNow.AddSeconds(MaxSeconds);
        while (DateTime.UtcNow < deadline)
        {
            if (!listener.Pending())
            {
                Thread.Sleep(20);
                continue;
            }
            using (TcpClient client = listener.AcceptTcpClient())
            {
                NetworkStream stream = client.GetStream();
                ReadRequest(stream);
                byte[] body = Encoding.ASCII.GetBytes("{\"status\":\"ok\"}");
                byte[] head = Encoding.ASCII.GetBytes(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + body.Length + "\r\nConnection: close\r\n\r\n");
                stream.Write(head, 0, head.Length);
                stream.Write(body, 0, body.Length);
                stream.Flush();
            }
            if (exitAfterServing >= 0)
            {
                // 讓啟動器先讀完回應、印出就緒，再結束
                Thread.Sleep(500);
                Console.Error.WriteLine("stub server: crashed");
                return exitAfterServing;
            }
        }
        return 98;
    }

    static void ReadRequest(NetworkStream stream)
    {
        var text = new StringBuilder();
        var buffer = new byte[1024];
        while (text.ToString().IndexOf("\r\n\r\n", StringComparison.Ordinal) < 0)
        {
            int read = stream.Read(buffer, 0, buffer.Length);
            if (read <= 0)
                return;
            text.Append(Encoding.ASCII.GetString(buffer, 0, read));
        }
    }

    static int Port(string[] args)
    {
        for (int i = 0; i + 1 < args.Length; i++)
            if (args[i] == "--port")
                return int.Parse(args[i + 1]);
        throw new ArgumentException("no --port");
    }

    static int ParseInt(string text, int fallback)
    {
        int value;
        return int.TryParse(text, out value) ? value : fallback;
    }
}
