"""Local web server. Standard library only: no build step, no node_modules.

    python server.py --port 8765
    python server.py --mode replay
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import WEB_DIR, get_settings
from pipeline import Pipeline, get_pipeline
from planner import compile_question

RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
MAX_QUESTION = 1200


class Handler(BaseHTTPRequestHandler):
    server_version = "DeshiFuOuterBrain/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _text(self, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _file(self, path: Path, download: bool = False) -> None:
        if not path.exists() or not path.is_file():
            self._json(404, {"error": "not_found"})
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 20000:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._file(WEB_DIR / "index.html")
            return
        if path.startswith("/assets/"):
            candidate = (WEB_DIR / "assets" / path[len("/assets/"):]).resolve()
            if WEB_DIR.resolve() in candidate.parents:
                self._file(candidate)
            else:
                self._json(403, {"error": "forbidden"})
            return
        if path == "/api/health":
            probe = parse_qs(parsed.query).get("probe") == ["1"]
            pipeline = self.server.pipeline  # type: ignore[attr-defined]
            info = pipeline.client.health(probe=probe)
            info["kb_notes"] = len(pipeline.kb.all())
            info["run_dir"] = "runs/"
            self._json(200, info)
            return
        if path == "/api/cases":
            cases_path = WEB_DIR.parent / "data" / "cases.json"
            try:
                self._json(200, {"cases": json.loads(cases_path.read_text(encoding="utf-8"))})
            except (OSError, json.JSONDecodeError):
                self._json(200, {"cases": []})
            return
        if path == "/api/runs":
            pipeline = self.server.pipeline  # type: ignore[attr-defined]
            self._json(200, {"runs": pipeline.list_runs(30)})
            return
        if path == "/api/receipts":
            qs = parse_qs(parsed.query)
            pipeline = self.server.pipeline  # type: ignore[attr-defined]
            items = pipeline.kb.receipt_summary(
                qs.get("model", [""])[0], qs.get("material", [""])[0], qs.get("symptom", [""])[0]
            )
            self._json(200, {"receipts": items})
            return
        if path.startswith("/api/runs/"):
            run_id = path[len("/api/runs/"):].strip("/")
            if not RUN_ID_RE.match(run_id):
                self._json(400, {"error": "bad_run_id"})
                return
            run_path = WEB_DIR.parent / "runs" / f"{run_id}.json"
            self._file(run_path, download=parse_qs(parsed.query).get("download") == ["1"])
            return
        if path == "/favicon.ico":
            self._text(204, "")
            return
        self._json(404, {"error": "not_found", "path": path})

    # ----------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802 - http.server API
        path = urlparse(self.path).path
        if path not in ("/api/ask", "/api/compile", "/api/receipts"):
            self._json(404, {"error": "not_found"})
            return
        data = self._read_json()
        if path == "/api/receipts":
            outcome = str(data.get("outcome", ""))
            client_id = str(data.get("client_id", ""))[:64]
            run_id = str(data.get("run_id", ""))
            step_title = str(data.get("step_title", "")).strip()[:120]
            if outcome not in ("fixed", "not_fixed", "not_tried"):
                self._json(400, {"error": "bad_outcome"})
                return
            if len(client_id) < 8 or not RUN_ID_RE.match(run_id) or not step_title:
                self._json(400, {"error": "bad_receipt"})
                return
            try:
                result = self.server.pipeline.kb.add_receipt({  # type: ignore[attr-defined]
                    "run_id": run_id, "step_title": step_title,
                    "model": str(data.get("model", ""))[:80],
                    "material": str(data.get("material", ""))[:40],
                    "symptom": str(data.get("symptom", ""))[:40],
                    "outcome": outcome, "note": str(data.get("note", "")),
                    "client_id": client_id,
                })
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._json(500, {"error": "receipt_failed", "detail": str(exc)})
                return
            self._json(200, result)
            return
        question = str(data.get("question", "")).strip()
        if not question:
            self._json(400, {"error": "empty_question", "detail": "请描述你遇到的打印问题。"})
            return
        if len(question) > MAX_QUESTION:
            self._json(400, {"error": "question_too_long", "detail": f"最多 {MAX_QUESTION} 字。"})
            return
        try:
            pipeline = self.server.pipeline  # type: ignore[attr-defined]
            if path == "/api/compile":
                hits = pipeline.kb.search(question, 4)
                plan = compile_question(question, hits)
                self._json(200, {
                    "plan": plan,
                    "kb": [
                        {"id": h["id"], "title": h["title"], "stale": h.get("stale", False)}
                        for h in hits
                    ],
                })
                return
            payload = pipeline.ask(question)
        except Exception as exc:  # noqa: BLE001 - surface a clean error to the UI
            traceback.print_exc()
            self._json(500, {"error": "internal", "detail": f"{type(exc).__name__}: {exc}"})
            return
        self._json(200, payload)

    # ------------------------------------------------------------------ log
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - http.server API
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="得师傅·外脑 local demo server")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--mode", choices=["auto", "live", "replay"], default=None)
    parser.add_argument("--open", action="store_true", help="open the browser after start")
    args = parser.parse_args()

    settings = get_settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if args.mode:
        settings.mode = args.mode

    pipeline = get_pipeline()
    # get_pipeline may have been built before the CLI override; keep one object.
    pipeline.settings = settings
    pipeline.client.settings = settings

    try:
        server = ThreadingHTTPServer((settings.host, settings.port), Handler)
    except OSError as exc:
        print(f"端口 {settings.port} 启动失败：{exc}")
        print("换一个端口：python server.py --port 8766")
        return
    server.daemon_threads = True
    server.pipeline = pipeline  # type: ignore[attr-defined]

    url = f"http://{settings.host}:{settings.port}/"
    print("=" * 62)
    print("得师傅·外脑  |  元宝搜索增强的 3D 打印诊断")
    print(f"模式      : {settings.mode}  (credential={settings.credential_kind})")
    print(f"回放样本  : {pipeline.client._fixture_count()} 条")  # noqa: SLF001 - banner only
    print(f"私域笔记  : {len(pipeline.kb.all())} 条")
    print(f"地址      : {url}")
    print("=" * 62)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
