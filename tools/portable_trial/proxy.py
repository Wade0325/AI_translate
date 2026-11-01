"""試發布（#35）用的 HTTP CONNECT 代理：計首次佈建的下載量，也能模擬斷網。

uv 與 huggingface_hub 都照 HTTPS_PROXY 走代理，所以經過這裡的位元組就是首次佈建（或權重下載）
從網路拿到的量（含 TLS 的額外負擔，比檔案本身多一點點）。

- 每秒把累計的量寫進 --stats（JSON）：總量、每個主機的量、進行中的連線數。
- 每條連線結束時，在 --tunnels（JSON Lines）記一行：主機、量、秒數、怎麼結束的。
- --control 這個檔案存在時是「斷網」：已經開著的連線不再轉送任何資料（不關閉，像 Wi-Fi 斷掉時
  連線卡住），新的連線收下但不回應。檔案刪掉之後，新的連線恢復正常；卡住的連線不會恢復，
  和真的斷網一樣只能靠用戶端逾時。要完全恢復就重新啟動這支代理。

只用標準函式庫。只在 CI 的試發布 workflow 用，不進發布包。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

CHUNK = 256 * 1024
HANG_SECONDS = 24 * 3600


@dataclass
class Tunnel:
    host: str
    port: str
    opened: float
    down: int = 0
    up: int = 0
    ended: str = ""
    seconds: float = 0.0

    def end(self, why: str) -> None:
        if not self.ended:
            self.ended = why


class Stats:
    def __init__(self, stats_path: Path, control_path: Path, tunnels_path: Path) -> None:
        self.stats_path = stats_path
        self.control_path = control_path
        self.tunnels_path = tunnels_path
        self.started = time.time()
        self.down = 0
        self.up = 0
        self.hosts: dict[str, dict[str, int]] = {}
        self.active = 0
        self.connections = 0
        self.blackhole = False

    def host(self, name: str) -> dict[str, int]:
        return self.hosts.setdefault(name, {"down": 0, "up": 0, "connections": 0})

    def snapshot(self) -> dict[str, object]:
        return {
            "time": time.time(),
            "elapsed": round(time.time() - self.started, 1),
            "down": self.down,
            "up": self.up,
            "active": self.active,
            "connections": self.connections,
            "blackhole": self.blackhole,
            "hosts": self.hosts,
        }

    def log_tunnel(self, record: dict[str, object]) -> None:
        with self.tunnels_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def hang() -> None:
    await asyncio.sleep(HANG_SECONDS)


async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, stats: Stats,
                host: str, direction: str, tunnel: Tunnel) -> None:
    try:
        while True:
            if stats.blackhole:
                tunnel.end("blackhole")
                await hang()
            data = await reader.read(CHUNK)
            if not data:
                tunnel.end(f"eof-{direction}")
                break
            if stats.blackhole:
                tunnel.end("blackhole")
                await hang()
            n = len(data)
            counters = stats.host(host)
            counters[direction] += n
            if direction == "down":
                stats.down += n
                tunnel.down += n
            else:
                stats.up += n
                tunnel.up += n
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError) as e:
        tunnel.end(f"{type(e).__name__}-{direction}")
    finally:
        try:
            writer.close()
        except (ConnectionError, OSError):
            pass


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, stats: Stats) -> None:
    if stats.blackhole:
        await hang()
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 60)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
            ConnectionError, OSError):
        writer.close()
        return
    request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
    parts = request_line.split(" ")
    if len(parts) < 2 or parts[0] != "CONNECT":
        writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
        stats.log_tunnel({"host": request_line, "ended": "not-connect"})
        writer.close()
        return
    host, _, port = parts[1].rpartition(":")
    if stats.blackhole:
        await hang()
    tunnel = Tunnel(host=host, port=port, opened=round(time.time() - stats.started, 1))
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port)), 60)
    except (asyncio.TimeoutError, ConnectionError, OSError, ValueError) as e:
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        tunnel.end(f"connect-failed: {type(e).__name__}")
        stats.log_tunnel(asdict(tunnel))
        writer.close()
        return
    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await writer.drain()
    stats.active += 1
    stats.connections += 1
    stats.host(host)["connections"] += 1
    started = time.time()
    try:
        await asyncio.gather(
            relay(reader, upstream_writer, stats, host, "up", tunnel),
            relay(upstream_reader, writer, stats, host, "down", tunnel),
        )
    finally:
        stats.active -= 1
        tunnel.seconds = round(time.time() - started, 1)
        stats.log_tunnel(asdict(tunnel))


async def report(stats: Stats) -> None:
    while True:
        stats.blackhole = stats.control_path.exists()
        tmp = stats.stats_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(stats.snapshot(), ensure_ascii=False), encoding="utf-8")
        for _ in range(20):
            try:
                os.replace(tmp, stats.stats_path)
                break
            except PermissionError:  # Windows：讀的那一方剛好開著檔案
                await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--tunnels", type=Path, required=True)
    args = parser.parse_args()
    stats = Stats(args.stats, args.control, args.tunnels)

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await handle(reader, writer, stats)

    server = await asyncio.start_server(on_client, "127.0.0.1", args.port, limit=1 << 20)
    reporter = asyncio.ensure_future(report(stats))
    async with server:
        try:
            await server.serve_forever()
        finally:
            reporter.cancel()


if __name__ == "__main__":
    asyncio.run(main())
