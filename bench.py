"""Verification harness: run the four demo cases and print a reproducible table.

This is deliberately *not* an online benchmark. In replay mode it measures the
whole chain against the recorded SearchPro corpus; in live mode it measures the
same chain against the real API (and costs quota). The article should label the
numbers accordingly.

Usage:
    python bench.py                 # follows WSA_MODE (auto: live if credentials exist)
    python bench.py --live          # force live; requires credentials
    python bench.py --json out.json # also write machine-readable rows
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pipeline import Pipeline

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "data" / "cases.json"


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def summarize(case: dict, result: dict) -> dict:
    answer = result.get("answer", {})
    gaps = result.get("plan", {}).get("gaps", [])
    coverage = answer.get("coverage", {})
    steps = answer.get("steps", [])
    evidence = result.get("evidence", [])
    calls = result.get("search", {}).get("calls", [])
    return {
        "id": case.get("id"),
        "tag": case.get("tag"),
        "run_id": result.get("run_id"),
        "mode": result.get("mode"),
        "replayed": result.get("replayed"),
        "elapsed_ms": result.get("elapsed_ms"),
        "calls": len(calls),
        "evidence": len(evidence),
        "official": sum(1 for item in evidence if item.get("tier") == "official"),
        "community": sum(1 for item in evidence if item.get("tier") == "community"),
        "claims": len(result.get("claims", [])),
        "conflicts": len(result.get("conflicts", [])),
        "gaps_covered": coverage.get("covered", sum(1 for g in gaps if g.get("status") == "covered")),
        "gaps_total": len(gaps),
        "citations": sum(1 for step in steps if step.get("sids")),
        "steps": len(steps),
        "confidence": answer.get("confidence"),
        "headline": answer.get("headline"),
    }


def markdown(rows: list[dict]) -> str:
    head = (
        "| 案例 | 查询 | 证据 | 官方 | 数值断言 | 冲突 | 缺口覆盖 | 有引用步骤 | 置信 |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---|\n"
    )
    lines = []
    for row in rows:
        lines.append(
            f"| {row['tag']} | {row['calls']} | {row['evidence']} | {row['official']} | "
            f"{row['claims']} | {row['conflicts']} | {row['gaps_covered']}/{row['gaps_total']} | "
            f"{row['citations']}/{row['steps']} | {row['confidence']} |"
        )
    return head + "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="force live mode")
    parser.add_argument("--json", type=Path, default=None, help="write rows as JSON")
    args = parser.parse_args()

    if args.live:
        import os
        os.environ["WSA_MODE"] = "live"

    cases = load_cases()
    pipeline = Pipeline()
    rows = []
    started = time.time()
    failed = False
    for case in cases:
        result = pipeline.ask(case["question"])
        if any(call.get("error") for call in result.get("search", {}).get("calls", [])):
            failed = True
        row = summarize(case, result)
        rows.append(row)
        print(f"  [{row['tag']}] {row['headline']}  ({row['calls']} calls / {row['elapsed_ms']}ms)")

    print()
    print(markdown(rows))
    print()
    print(f"mode={rows[0]['mode']}  replayed={rows[0]['replayed']}  "
          f"cases={len(rows)}  wall={time.time() - started:.2f}s  failed={failed}")
    if rows[0].get("replayed"):
        print("note: replay numbers verify the chain, not online accuracy.")
    else:
        print("note: one live run; not an online accuracy benchmark.")

    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
