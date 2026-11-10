"""Probe a few live SearchPro query shapes and print compact top hits."""
from __future__ import annotations

import sys

from config import Settings
from wsa import WsaClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

settings = Settings()
client = WsaClient(settings)

CASES = [
    ("A1 broad", "A1 mini PLA 热床温度 首层 翘边 官方", {"Mode": 2, "Cnt": 10, "Site": "wiki.bambulab.com"}),
    ("A1 exact", "A1 mini PLA 热床温度 60 65 首层 附着", {"Mode": 2, "Cnt": 10}),
    ("A1 faq", "A1 mini 热床温度 PLA 首层 翘边", {"Mode": 2, "Cnt": 10, "Site": "wiki.bambulab.com"}),
    ("P1S dry", "P1S PETG 拉丝 烘干 65℃ 4小时 回抽", {"Mode": 2, "Cnt": 10}),
    ("K1 fw", "K1 固件 3.2 首层 变薄 Z偏移 调平", {"Mode": 2, "Cnt": 10}),
    ("Resin", "光敏树脂 打印机 卧室 通风 手套 废液 安全", {"Mode": 2, "Cnt": 10}),
]

for label, query, params in CASES:
    result = client.search(query, params)
    print("=" * 80)
    print(label, "|", query, "|", params)
    print("ok", result["ok"], "err", result["error"], "rid", result["request_id"],
          "version", result["version"], "ms", result["latency_ms"], "pages", len(result["pages"]))
    for i, page in enumerate(result["pages"][:5], 1):
        print(f"  {i}. [{page.get('site')}] {page.get('title', '')[:80]}")
        print("     ", (page.get("passage") or "")[:150].replace("\n", " "))
