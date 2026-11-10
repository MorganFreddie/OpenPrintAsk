"""One-call live smoke test for Yuanbao SearchPro.

Run this before recording the final screenshots:

    python live_check.py

It reads credentials from .env (never from source), sends exactly one
SearchPro request, prints the RequestId and the first three results, and
writes the full response to runs/live_check.json.
"""
from __future__ import annotations

import argparse
import json
import sys

from config import RUNS_DIR, Settings, ensure_dirs
from wsa import WsaClient


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="SearchPro live smoke test")
    parser.add_argument("--query", default="A1 mini PLA 热床温度 官方")
    parser.add_argument("--mode", type=int, default=0, choices=[0, 1, 2])
    args = parser.parse_args()

    settings = Settings()
    if not settings.has_credentials:
        print("未检测到 SearchPro 凭证。")
        print("请把 WSA_API_KEY（或 WSA_SECRET_ID / WSA_SECRET_KEY）写进 .env，")
        print("不要发到聊天、文章或截图里。参考 .env.example。")
        return 2

    # A very common mix-up: a Tencent Cloud SecretId (AKID...) is not a
    # SearchPro service API KEY (sk-...). Fail with a precise hint instead of
    # sending it to the Bearer endpoint and getting UnauthorizedOperation.
    if settings.api_key.startswith(("AKID", "AKI")):
        print("检测到 WSA_API_KEY 里填的是腾讯云 SecretId（AKI...），不是服务 API KEY。")
        print("二选一：")
        print("  1) 换用服务 API KEY：WSA_API_KEY=sk-...（推荐，简单）")
        print("  2) 走 TC3：WSA_API_KEY= 留空，填 WSA_SECRET_ID / WSA_SECRET_KEY")
        print("改完再运行 python live_check.py。")
        return 2

    # Force live even if WSA_MODE=replay/auto is set in the shell.
    settings.mode = "live"
    ensure_dirs()
    client = WsaClient(settings)
    result = client.search(args.query, {"Mode": args.mode, "Cnt": 10}, tags=["live-check"])

    payload = {
        "ok": result.get("ok"),
        "error": result.get("error"),
        "detail": result.get("detail"),
        "http_status": result.get("http_status"),
        "request_id": result.get("request_id"),
        "version": result.get("version"),
        "latency_ms": result.get("latency_ms"),
        "params": result.get("params"),
        "pages": result.get("pages", []),
    }
    (RUNS_DIR / "live_check.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not result.get("ok"):
        print(f"FAILED: {result.get('error')} / {result.get('detail')}")
        print(f"HTTP {result.get('http_status')} · see runs/live_check.json")
        return 1

    print(f"OK  RequestId={result.get('request_id')}  version={result.get('version')}")
    print(f"latency={result.get('latency_ms')}ms  pages={len(result.get('pages', []))}")
    for i, page in enumerate(result.get("pages", [])[:3], 1):
        print(f"  S{i} [{page.get('site')}] {page.get('title')}")
        print(f"     {page.get('date')} · {page.get('url')}")
    print(f"wrote {RUNS_DIR / 'live_check.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
