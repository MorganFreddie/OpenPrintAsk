"""Yuanbao Search (腾讯元宝搜索 / WSA SearchPro) client.

Two credential paths are supported, because the documentation exposes two and
mixing them up is the most common first-hour failure:

1. Service API key  -> POST https://api.wsa.cloud.tencent.com/SearchPro
                       Authorization: Bearer sk-...
2. Tencent Cloud AK -> POST https://wsa.tencentcloudapi.com/
                       TC3-HMAC-SHA256 signed request, X-TC-Action: SearchPro

A third mode, replay, reads a local fixture set. It exists so the prototype can
be developed and demonstrated without burning quota; every replayed response is
flagged so the UI can never pretend it is live data.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pathlib
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from config import FIXTURE_DIR, RUNS_DIR, Settings, ensure_dirs
from kb import tokenize

SERVICE_ENDPOINT = "https://api.wsa.cloud.tencent.com/SearchPro"
TC3_ENDPOINT = "https://wsa.tencentcloudapi.com/"
TC3_HOST = "wsa.tencentcloudapi.com"
ACTION = "SearchPro"
VERSION = "2025-05-08"

VALID_CNT = {10, 20, 30, 40, 50}
VALID_INDUSTRY = {"gov", "news", "acad", "finance"}
FRESHNESS_RE = re.compile(r"^(d([1-9]|[12]\d|30)|m([1-9]|1[0-2])|y[1-5]|\d{4}-\d{2}-\d{2}(~\d{4}-\d{2}-\d{2})?)$")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


class WsaClient:
    def __init__(self, settings: Settings, fixture_path: pathlib.Path | str | None = None) -> None:
        ensure_dirs()
        self.settings = settings
        self.fixture_path = pathlib.Path(fixture_path) if fixture_path else (FIXTURE_DIR / "demo.json")
        self._fixtures: dict | None = None

    # ---------------------------------------------------------------- public
    def search(self, query: str, params: dict | None = None,
               tags: list[str] | None = None) -> dict:
        params = self._sanitize(params)
        query = re.sub(r"\s+", " ", (query or "").strip())
        started = time.perf_counter()
        if not query:
            return self._result(query, params, error="empty_query", started=started)

        if self.settings.mode == "replay":
            result = self._replay(query, params, tags or [])
        elif self.settings.credential_kind == "api_key":
            result = self._live_with_retry(self._bearer_once, query, params)
        elif self.settings.credential_kind == "tc3":
            result = self._live_with_retry(self._tc3_once, query, params)
        else:
            result = self._result(query, params, error="missing_credentials", started=started,
                                  detail="未配置 WSA_API_KEY 或 WSA_SECRET_ID/WSA_SECRET_KEY")

        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        if self.settings.record and self.settings.mode == "live" and result.get("ok"):
            self._record(query, params, result)
        return result

    def health(self, probe: bool = False) -> dict:
        info = {
            "mode": self.settings.mode,
            "credential_kind": self.settings.credential_kind,
            "fixtures": self._fixture_count(),
        }
        if self.settings.mode == "replay":
            info.update(ok=info["fixtures"] > 0, detail="回放模式：不调用真实 API")
            return info
        if not self.settings.has_credentials:
            info.update(ok=False, detail="live 模式但未配置凭证")
            return info
        if not probe:
            info.update(ok=True, detail="凭证已配置；点击“测试连接”会真实调用一次")
            return info
        result = self.search("3D打印 首层 翘边", {"Mode": 2, "Cnt": 10})
        info.update(ok=result.get("ok", False), detail=result.get("error") or "连接正常",
                    latency_ms=result.get("latency_ms"), request_id=result.get("request_id"))
        return info

    # ------------------------------------------------------------- sanitize
    @staticmethod
    def _sanitize(params: dict | None) -> dict:
        params = dict(params or {})
        params.pop("Query", None)
        mode = params.get("Mode", 2)
        try:
            mode = int(mode)
        except (TypeError, ValueError):
            mode = 2
        params["Mode"] = mode if mode in (0, 1, 2) else 2
        try:
            cnt = int(params.get("Cnt", 10))
        except (TypeError, ValueError):
            cnt = 10
        params["Cnt"] = cnt if cnt in VALID_CNT else 10
        site = params.get("Site")
        if site:
            site = str(site).strip()
            if site.startswith("exclude:"):
                domains = [d.strip() for d in site[8:].split("|") if d.strip()][:5]
                params["Site"] = "exclude:" + "|".join(domains) if domains else None
            else:
                params["Site"] = site
            if not params.get("Site"):
                params.pop("Site", None)
        for key in ("Freshness",):
            value = params.get(key)
            if value and not FRESHNESS_RE.match(str(value)):
                params.pop(key, None)
        industry = params.get("Industry")
        if industry and industry not in VALID_INDUSTRY:
            params.pop("Industry", None)
        deeplinks = params.get("Deeplinks")
        if deeplinks is not None:
            params["Deeplinks"] = bool(deeplinks)
        return params

    # ---------------------------------------------------------------- result
    def _result(self, query: str, params: dict, pages: list | None = None,
                request_id: str = "", version: str = "", error: str = "",
                detail: str = "", started: float | None = None,
                replayed: bool = False, http_status: int = 0) -> dict:
        latency = int((time.perf_counter() - started) * 1000) if started else 0
        return {
            "ok": not error,
            "query": query,
            "params": params,
            "pages": pages or [],
            "request_id": request_id,
            "version": version,
            "error": error,
            "detail": detail,
            "latency_ms": latency,
            "replayed": replayed,
            "http_status": http_status,
        }

    # ------------------------------------------------------------------ live
    def _live_with_retry(self, fn, query: str, params: dict) -> dict:
        started = time.perf_counter()
        last = None
        for attempt in range(2):
            try:
                result = fn(query, params, started)
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:  # noqa: BLE001 - best-effort diagnostics
                    pass
                last = self._result(query, params, error=f"http_{exc.code}",
                                    detail=body[:600], started=started, http_status=exc.code)
                if exc.code in (429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(0.7)
                    continue
                return last
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = self._result(query, params, error="network_error",
                                    detail=str(exc)[:300], started=started)
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                return last
            except Exception as exc:  # noqa: BLE001 - never crash the pipeline for one query
                return self._result(query, params, error="client_error",
                                    detail=f"{type(exc).__name__}: {exc}"[:300], started=started)
            if result.get("error") in ("http_429",) and attempt == 0:
                time.sleep(0.7)
                continue
            return result
        return last or self._result(query, params, error="unknown", started=started)

    def _bearer_once(self, query: str, params: dict, started: float) -> dict:
        payload = {"Query": query, **params}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            SERVICE_ENDPOINT, data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json; charset=UTF-8",
                "Accept": "application/json",
                "User-Agent": "deshifu-outer-brain/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=self.settings.request_timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
        return self._parse(raw, query, params, started, status)

    def _tc3_once(self, query: str, params: dict, started: float) -> dict:
        payload = {"Query": query, **params}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        timestamp = int(time.time())
        headers = self._tc3_headers(body, timestamp)
        request = urllib.request.Request(TC3_ENDPOINT, data=body, method="POST", headers=headers)
        with urllib.request.urlopen(request, timeout=self.settings.request_timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
        return self._parse(raw, query, params, started, status)

    def _tc3_headers(self, body: bytes, timestamp: int) -> dict:
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
        content_type = "application/json; charset=utf-8"
        canonical_headers = f"content-type:{content_type}\nhost:{TC3_HOST}\n"
        signed_headers = "content-type;host"
        hashed_payload = hashlib.sha256(body).hexdigest()
        canonical_request = (
            f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"
        )
        credential_scope = f"{date}/wsa/tc3_request"
        string_to_sign = (
            "TC3-HMAC-SHA256\n"
            f"{timestamp}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )
        secret_date = _hmac(("TC3" + self.settings.secret_key).encode("utf-8"), date)
        secret_service = _hmac(secret_date, "wsa")
        secret_signing = _hmac(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            f"TC3-HMAC-SHA256 Credential={self.settings.secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {
            "Authorization": authorization,
            "Content-Type": content_type,
            "X-TC-Action": ACTION,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": VERSION,
            "User-Agent": "deshifu-outer-brain/1.0",
        }

    def _parse(self, raw: str, query: str, params: dict, started: float, status: int) -> dict:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._result(query, params, error="bad_json", detail=raw[:300],
                                started=started, http_status=status)
        response = data.get("Response", data)
        error = response.get("Error") or data.get("Error")
        if error:
            code = error.get("Code") or error.get("code") or "api_error"
            message = error.get("Message") or error.get("message") or ""
            return self._result(query, params, error=str(code), detail=message,
                                request_id=response.get("RequestId", ""),
                                started=started, http_status=status)
        raw_pages = response.get("Pages") or []
        pages = []
        for item in raw_pages:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except json.JSONDecodeError:
                    continue
            if isinstance(item, dict) and item.get("url"):
                pages.append(item)
        return self._result(query, params, pages=pages,
                            request_id=response.get("RequestId", ""),
                            version=response.get("Version", ""),
                            started=started, http_status=status)

    # ---------------------------------------------------------------- replay
    def _load_fixtures(self) -> dict:
        if self._fixtures is not None:
            return self._fixtures
        if not self.fixture_path.exists():
            self._fixtures = {"entries": [], "pages": []}
            return self._fixtures
        try:
            self._fixtures = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._fixtures = {"entries": [], "pages": []}
        return self._fixtures

    def _fixture_count(self) -> int:
        data = self._load_fixtures()
        return len(data.get("entries", [])) + len(data.get("pages", []))

    def _replay(self, query: str, params: dict, tags: list[str]) -> dict:
        started = time.perf_counter()
        data = self._load_fixtures()
        entries = data.get("entries", [])
        exact = next((e for e in entries if _norm(e.get("query", "")) == _norm(query)), None)
        if exact:
            pages = exact.get("pages", [])[: params.get("Cnt", 10)]
            return self._result(query, params, pages=[dict(p) for p in pages],
                                request_id=f"replay-{hashlib.md5(query.encode('utf-8')).hexdigest()[:8]}",
                                version="standard", started=started, replayed=True)

        pool = data.get("pages", [])
        tagset = {t.lower() for t in tags if t}
        scored = []
        q_tokens = set(tokenize(query))
        for page in pool:
            page_tags = {t.lower() for t in page.get("tags", [])}
            tag_hit = len(tagset & page_tags) if tagset else 0
            if tagset and tag_hit == 0:
                continue
            text_tokens = set(tokenize(f"{page.get('title','')} {page.get('passage','')} {page.get('content','')}"))
            overlap = len(q_tokens & text_tokens)
            score = tag_hit * 4 + overlap
            if score > 0:
                scored.append((score, page))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        pages = [dict(page) for _score, page in scored[: params.get("Cnt", 10)]]
        if not pages:
            return self._result(query, params, error="replay_miss",
                                detail="回放样本里没有匹配到这条查询；请补充 fixtures 或切换 live。",
                                started=started, replayed=True)
        return self._result(query, params, pages=pages,
                            request_id=f"replay-{hashlib.md5(query.encode('utf-8')).hexdigest()[:8]}",
                            version="standard", started=started, replayed=True)

    # ---------------------------------------------------------------- record
    def _record(self, query: str, params: dict, result: dict) -> None:
        try:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            line = json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "params": params,
                "request_id": result.get("request_id"),
                "version": result.get("version"),
                "pages": result.get("pages"),
            }, ensure_ascii=False)
            with (RUNS_DIR / "records.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass
