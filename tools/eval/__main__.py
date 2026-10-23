import io
import sys

from .cli import main

# Windows 主控台預設 cp950，印不出 ⚠、→、Δ 這些字元
for stream in (sys.stdout, sys.stderr):
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(encoding="utf-8")

raise SystemExit(main())
