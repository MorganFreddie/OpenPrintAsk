"""End-to-end pipeline: private KB -> question compiler -> SearchPro -> answer.

The order matters. If you search first and ask questions later, you get a pile
of pages. Here the gap analysis happens *before* any network call, so every
request has a job, and the answer can say which job failed.
"""
from __future__ import annotations

import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from compose import compose
from config import RUNS_DIR, Settings, ensure_dirs, get_settings
from fuse import fuse
from kb import KnowledgeBase
from planner import compile_question
from wsa import WsaClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Pipeline:
    def __init__(self, settings: Settings | None = None,
                 kb: KnowledgeBase | None = None, client: WsaClient | None = None) -> None:
        ensure_dirs()
        self.settings = settings or get_settings()
        self.kb = kb or KnowledgeBase().init()
        self.client = client or WsaClient(self.settings)

    # ------------------------------------------------------------------ KB
    def _kb_hits(self, question: str, plan: dict) -> list[dict]:
        slots = plan.get("slots", {})
        queries = [question]
        composed = " ".join(filter(None, [
            slots.get("model"), slots.get("material"),
            (slots.get("symptom") or {}).get("label", ""),
        ]))
        if composed.strip():
            queries.append(composed)
        merged: dict[str, dict] = {}
        for query in queries:
            for hit in self.kb.search(query, k=4):
                current = merged.get(hit["id"])
                if not current or hit["relevance"] > current["relevance"]:
                    merged[hit["id"]] = hit
        hits = sorted(merged.values(), key=lambda h: h["relevance"], reverse=True)
        return hits[:5]

    # -------------------------------------------------------------- search
    def _tags(self, plan: dict) -> list[str]:
        slots = plan.get("slots", {})
        model = slots.get("model") or ""
        tags = [
            (slots.get("symptom") or {}).get("id", ""),
            model.lower(), model.replace(" ", "").lower(),
            (slots.get("material") or "").lower(),
        ]
        return [t for t in tags if t]

    def _run_one(self, query: dict, tags: list[str]) -> dict:
        started = time.perf_counter()
        result = self.client.search(query["text"], query["params"], tags=tags)
        if query["params"].get("Site") and (result.get("error") or not result.get("pages")):
            retry_params = {k: v for k, v in query["params"].items() if k != "Site"}
            retry = self.client.search(query["text"], retry_params, tags=tags)
            if retry.get("ok") and retry.get("pages"):
                retry["fallback"] = "site_filter_removed"
                result = retry
            else:
                result["site_fallback_failed"] = True
        result.update({
            "qid": query["id"],
            "covers": query["covers"],
            "weight": query["weight"],
            "purpose": query["purpose"],
            "planned_params": query["params"],
            "wall_ms": int((time.perf_counter() - started) * 1000),
        })
        return result

    def _execute(self, queries: list[dict], tags: list[str]) -> list[dict]:
        if not queries:
            return []
        results: list[dict] = []
        workers = max(1, min(self.settings.max_workers, len(queries)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._run_one, query, tags): query for query in queries}
            for future in as_completed(futures):
                query = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001 - one query must never kill the run
                    results.append({
                        "qid": query["id"], "query": query["text"], "params": query["params"],
                        "covers": query["covers"], "weight": query["weight"],
                        "purpose": query["purpose"], "pages": [], "ok": False,
                        "error": "pipeline_error", "detail": f"{type(exc).__name__}: {exc}"[:300],
                        "latency_ms": 0, "request_id": "", "replayed": False,
                    })
        order = {query["id"]: index for index, query in enumerate(queries)}
        results.sort(key=lambda r: order.get(r.get("qid", ""), 99))
        return results

    # ------------------------------------------------------------------ ask
    def ask(self, question: str) -> dict:
        started = time.perf_counter()
        question = (question or "").strip()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        stages: list[dict] = []

        t = time.perf_counter()
        compile_ms = 0
        plan = compile_question(question, [])
        compile_ms += int((time.perf_counter() - t) * 1000)
        stages.append({"name": "问题编译", "ms": compile_ms,
                       "detail": f"{len(plan['gaps'])} 个缺口 / {len(plan['queries'])} 条查询"})

        t = time.perf_counter()
        kb_hits = self._kb_hits(question, plan)
        stages.append({"name": "私域检索", "ms": int((time.perf_counter() - t) * 1000),
                       "detail": f"{len(kb_hits)} 条笔记"})

        # Recompile with the KB in hand: gaps such as "stale note" only exist
        # after we know what the private library already says.
        t = time.perf_counter()
        plan = compile_question(question, kb_hits)
        compile_ms += int((time.perf_counter() - t) * 1000)
        stages[0]["ms"] = compile_ms
        stages[0]["detail"] = f"{len(plan['gaps'])} 个缺口 / {len(plan['queries'])} 条查询"
        plan["kb_hits"] = [
            {"id": h["id"], "title": h["title"], "created_at": h["created_at"],
             "stale": h.get("stale", False), "relevance": h.get("relevance", 0)}
            for h in kb_hits
        ]

        t = time.perf_counter()
        results = self._execute(plan["queries"], self._tags(plan))
        stages.append({"name": "元宝搜索", "ms": int((time.perf_counter() - t) * 1000),
                       "detail": f"{len(results)} 次调用 / {sum(len(r.get('pages', [])) for r in results)} 条原始结果"})

        t = time.perf_counter()
        fused = fuse(plan, results, kb_hits)
        stages.append({"name": "证据融合", "ms": int((time.perf_counter() - t) * 1000),
                       "detail": f"{len(fused['evidence'])} 条证据 / {len(fused['claims'])} 条数值 / {len(fused['conflicts'])} 处冲突"})

        t = time.perf_counter()
        answer = compose(question, plan, fused, kb_hits)
        stages.append({"name": "回答生成", "ms": int((time.perf_counter() - t) * 1000),
                       "detail": answer.get("headline", "")})

        elapsed = int((time.perf_counter() - started) * 1000)
        trace = {
            "run_id": run_id,
            "created_at": _now_iso(),
            "question": question,
            "mode": self.settings.mode,
            "credential_kind": self.settings.credential_kind,
            "stages": stages,
            "calls": [
                {
                    "qid": r.get("qid"), "query": r.get("query"), "params": r.get("params"),
                    "purpose": r.get("purpose"), "covers": r.get("covers"),
                    "latency_ms": r.get("latency_ms"), "pages": len(r.get("pages", [])),
                    "request_id": r.get("request_id"), "version": r.get("version"),
                    "error": r.get("error"), "detail": r.get("detail"),
                    "replayed": r.get("replayed"), "fallback": r.get("fallback"),
                }
                for r in results
            ],
            "stats": fused["stats"],
            "kb": plan.get("kb_hits", []),
            "plan": {
                "rewritten_question": plan["rewritten_question"],
                "strategy": plan["strategy"],
                "queries": plan["queries"],
                "gaps": fused["gaps"],
            },
            "answer": answer,
            "evidence": fused["evidence"],
            "claims": fused["claims"],
            "conflicts": fused["conflicts"],
            "elapsed_ms": elapsed,
        }

        payload = {
            "run_id": run_id,
            "created_at": _now_iso(),
            "question": question,
            "mode": self.settings.mode,
            "credential_kind": self.settings.credential_kind,
            "replayed": any(r.get("replayed") for r in results),
            "elapsed_ms": elapsed,
            "stages": stages,
            "plan": {
                "slots": plan["slots"],
                "chips": plan["chips"],
                "gaps": fused["gaps"],
                "queries": plan["queries"],
                "strategy": plan["strategy"],
                "rewritten_question": plan["rewritten_question"],
                "naive_query": plan["naive_query"],
            },
            "kb": {"hits": plan.get("kb_hits", [])},
            "search": {
                "calls": [
                    {
                        "qid": r.get("qid"), "query": r.get("query"), "params": r.get("params"),
                        "purpose": r.get("purpose"), "covers": r.get("covers"),
                        "latency_ms": r.get("latency_ms"), "pages": len(r.get("pages", [])),
                        "request_id": r.get("request_id"), "version": r.get("version"),
                        "error": r.get("error"), "detail": r.get("detail"),
                        "replayed": r.get("replayed"), "fallback": r.get("fallback"),
                    }
                    for r in results
                ],
                "stats": fused["stats"],
            },
            "evidence": fused["evidence"],
            "claims": fused["claims"],
            "conflicts": fused["conflicts"],
            "answer": answer,
            "trace": trace,
        }
        self._save(run_id, payload)
        return payload

    def _save(self, run_id: str, payload: dict) -> None:
        try:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            (RUNS_DIR / f"{run_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def list_runs(self, limit: int = 20) -> list[dict]:
        items = []
        for path in sorted(RUNS_DIR.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append({
                    "run_id": data.get("run_id"), "question": data.get("question"),
                    "created_at": data.get("created_at"), "mode": data.get("mode"),
                    "elapsed_ms": data.get("elapsed_ms"),
                })
            except (OSError, json.JSONDecodeError):
                continue
        return items


_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline
