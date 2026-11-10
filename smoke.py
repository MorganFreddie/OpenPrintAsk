import json
import sys

from kb import KnowledgeBase
from planner import compile_question

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CASES = [
    "A1 mini 打 PLA，首层老翘边，热床 60℃ 还加了胶水也没用，是不是机器坏了？",
    "P1S 打 PETG 拉丝特别严重，回抽从 0.8 调到 1.2 了还是不行，是不是要换喷嘴？",
    "K1 升级最新固件以后首层压得很薄，是不是固件有问题？要不要回滚？",
    "光敏树脂打印机放在卧室里，味道很大，对人有毒吗？需要怎么防护？",
]

kb = KnowledgeBase().init()
for question in CASES:
    hits = kb.search(question, 4)
    plan = compile_question(question, hits)
    print("=" * 72)
    print("Q:", question)
    print("slots:", plan["slots"]["model"], plan["slots"]["material"],
          (plan["slots"]["symptom"] or {}).get("id"),
          "tried=", [t["label"] for t in plan["slots"]["tried"]],
          "env=", [e["label"] for e in plan["slots"]["environment"]])
    print("gaps:", [(g["id"], g["type"], g["priority"], g["status"]) for g in plan["gaps"]])
    print("kb:", [(h["id"], h["relevance"], h["stale"]) for h in hits])
    print("queries:")
    for query in plan["queries"]:
        print("  ", query["id"], json.dumps(query["params"], ensure_ascii=False),
              query["text"], "->", query["covers"])
    print("rewrite:", plan["rewritten_question"])
