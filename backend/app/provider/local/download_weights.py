"""在轉錄的那台機器上下載本機模型的模型權重。

Docker 模式的本機轉錄在主機的 GPU worker（``local_worker.bat``）執行，設定頁沒有權重卡，
缺權重時任務失敗的訊息指向這個指令（#123）。在主機的 ``backend`` 資料夾用同一個 venv 執行::

    .venv\\Scripts\\python.exe -m app.provider.local.download_weights                  # 預設模型所需
    .venv\\Scripts\\python.exe -m app.provider.local.download_weights all              # 所有本機模型
    .venv\\Scripts\\python.exe -m app.provider.local.download_weights moss-qwen3-asr   # 指定模型

權重下載到 HF_HOME；沒設時用設定的 ``hf_home``，和 ``local_worker.bat`` 設的相同。
已下載的跳過，中斷後再執行一次會接著下載。
"""

from __future__ import annotations

import argparse
import os
import sys

from app.provider.local import weights


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.provider.local.download_weights", description="下載本機模型的模型權重")
    parser.add_argument(
        "model", nargs="?", choices=[*weights.MODEL_REPOS, "all"],
        help="省略＝預設模型所需；all＝所有本機模型；或指定模型名稱")
    args = parser.parse_args(argv)

    missing = [r for r in weights.download_targets(args.model) if not weights.repo_is_ready(r)]
    print(f"模型權重的位置：{os.environ['HF_HOME']}")
    if not missing:
        print("需要的模型權重都已下載")
        return 0

    print(f"要下載 {len(missing)} 個，約 {weights.size_gb(missing)} GB")
    for i, repo in enumerate(missing, start=1):
        print(f"({i}/{len(missing)}) {repo}")
        try:
            weights.download_snapshot(repo)
        except Exception as e:
            print(f"下載失敗：{type(e).__name__}: {e}", file=sys.stderr)
            print("請確認網路連線與磁碟空間；再執行一次會接著下載", file=sys.stderr)
            return 1
    print("下載完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
