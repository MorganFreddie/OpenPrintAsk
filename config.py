"""Runtime configuration for 得师傅·外脑 (DeshiFu Outer Brain).

Everything is read from environment variables / a local .env file so that no
secret ever has to live in source code or in the article.
"""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
WEB_DIR = ROOT / "web"
FIXTURE_DIR = DATA_DIR / "fixtures"


def load_env(path: pathlib.Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE, # comments, no interpolation)."""
    path = path or (ROOT / ".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


class Settings:
    def __init__(self) -> None:
        load_env()
        self.api_key = os.getenv("WSA_API_KEY", "").strip()
        self.secret_id = os.getenv("WSA_SECRET_ID", "").strip()
        self.secret_key = os.getenv("WSA_SECRET_KEY", "").strip()

        mode = os.getenv("WSA_MODE", "auto").strip().lower()
        if mode not in {"auto", "live", "replay"}:
            mode = "auto"
        if mode == "auto":
            mode = "live" if self.has_credentials else "replay"
        self.mode = mode

        self.host = os.getenv("WSA_HOST", "127.0.0.1")
        self.port = int(os.getenv("WSA_PORT", "8765"))
        self.record = os.getenv("WSA_RECORD", "0").strip() == "1"
        self.request_timeout = float(os.getenv("WSA_TIMEOUT", "12"))
        self.max_workers = int(os.getenv("WSA_MAX_WORKERS", "4"))

        # Optional LLM polishing. The demo works without it; when present, the
        # composer can be upgraded to a model-written answer.
        self.llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()
        self.llm_model = os.getenv("LLM_MODEL", "deepseek-chat").strip()

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key or (self.secret_id and self.secret_key))

    @property
    def credential_kind(self) -> str:
        if self.api_key:
            return "api_key"
        if self.secret_id and self.secret_key:
            return "tc3"
        return "none"

    def public_dict(self) -> dict:
        return {
            "mode": self.mode,
            "credential_kind": self.credential_kind,
            "has_credentials": self.has_credentials,
            "record": self.record,
            "llm": bool(self.llm_api_key),
            "port": self.port,
        }


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def ensure_dirs() -> None:
    for directory in (DATA_DIR, RUNS_DIR, FIXTURE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
