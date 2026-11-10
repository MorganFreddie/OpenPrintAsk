"""Run all four demo cases through the full pipeline and print a compact report."""
from __future__ import annotations

import json
import sys

from pipeline import Pipeline

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CASES = [
    "A1 mini 打 PLA，首层老翘边，热床 60℃ 还加了胶水也没用，是不是机器坏了？",
    "P1S 打 PETG 拉丝特别严重，回抽从 0.8 调到 1.2 了还是不行，是不是要换喷嘴？",
    "K1 升级最新固件以后首层压得很薄，是不是固件有问题？要不要回滚？",
    "光敏树脂打印机放在卧室里，味道很大，对人有毒吗？需要怎么防护？",
]

pipeline = Pipeline()
payloads = []
failed = False
for question in CASES:
    result = pipeline.ask(question)
    payloads.append(result)
    print("=" * 78)
    print("Q:", question)
    print("mode:", result["mode"], "replayed:", result["replayed"], "elapsed_ms:", result["elapsed_ms"])
    print("plan:", result["plan"]["rewritten_question"])
    for call in result["search"]["calls"]:
        print(f"  {call['qid']} {json.dumps(call['params'], ensure_ascii=False)} "
              f"pages={call['pages']} err={call['error'] or '-'} "
              f"rid={call['request_id'] or '-'} fallback={call['fallback'] or '-'}")
        if call.get("error"):
            failed = True
    print("evidence:", len(result["evidence"]),
          [item["title"][:28] for item in result["evidence"][:4]])
    print("claims:", [(c["attribute"], c.get("value_low"), c.get("value_high"), c["sid"])
                      for c in result["claims"]][:6])
    print("conflicts:", [c["summary"] for c in result["conflicts"]])
    print("gaps:", [(g["id"], g["type"], g["status"]) for g in result["plan"]["gaps"]])
    answer = result["answer"]
    print("answer:", answer["headline"], "| confidence:", answer["confidence"],
          "| coverage:", answer["coverage"])
    print("summary:", answer["summary"])
    for step in answer["steps"]:
        print(f"  {step['n']}. {step['title']} [{','.join(step['sids'])}] {step['text'][:70]}")
    print("followup:", answer["followup"])
    print("uncertainties:", answer["uncertainties"])

    if any(c.get("error") for c in result["search"]["calls"]):
        failed = True

with open("runs/demo_check.json", "w", encoding="utf-8") as handle:
    json.dump(payloads, handle, ensure_ascii=False, indent=2)
print("=" * 78)
print("wrote runs/demo_check.json; failed =", failed)
raise SystemExit(1 if failed else 0)
