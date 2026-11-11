"""A tiny local knowledge base: SQLite + FTS5, zero external services.

It plays the role of the "私域知识" half of the hybrid question. The seeded
notes are deliberately ordinary user notes: incomplete, sometimes outdated,
sometimes wrong. That is the point -- the outer brain has to notice what the
private KB does *not* know before it goes to the public web.
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Iterable

from config import DATA_DIR, ensure_dirs

CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
LATIN = re.compile(r"[a-z0-9][a-z0-9\-_.+]*")

STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "那", "怎么", "如何", "为什么", "什么", "现在", "然后", "还是",
    "但是", "而且", "因为", "所以", "如果", "可以", "需要", "问题", "打印", "机器",
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "are",
}


def tokenize(text: str) -> list[str]:
    """Character bigrams for Chinese + lowercase latin words.

    No jieba dependency: a 3D-printing vocabulary is small and bigrams are
    surprisingly competitive for this corpus. The same function is used for
    indexing and querying, so recall stays predictable.
    """
    text = (text or "").lower()
    out: list[str] = []
    for run in CJK_RUN.findall(text):
        out.extend(run)
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
    for word in LATIN.findall(text):
        if len(word) >= 2:
            out.append(word)
    return out


def index_text(*parts: str) -> str:
    seen: dict[str, None] = {}
    for part in parts:
        for tok in tokenize(part):
            seen.setdefault(tok, None)
    return " ".join(seen)


def query_terms(query: str) -> list[str]:
    seen: dict[str, None] = {}
    for tok in tokenize(query):
        if tok in STOPWORDS or len(tok) < 2 and not CJK_RUN.fullmatch(tok):
            continue
        if tok in STOPWORDS:
            continue
        seen.setdefault(tok, None)
    return list(seen)


def fts_match(query: str) -> str:
    terms = query_terms(query)
    if not terms:
        return ""
    # Quoting each term keeps FTS5 operators out of user input.
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)


def _overlap(query: str, text: str) -> float:
    q = {t for t in tokenize(query) if len(t) >= 2 and t not in STOPWORDS}
    if not q:
        return 0.0
    d = {t for t in tokenize(text) if len(t) >= 2}
    return len(q & d) / len(q)


class KnowledgeBase:
    def __init__(self, path: pathlib.Path | str | None = None) -> None:
        ensure_dirs()
        self.path = pathlib.Path(path) if path else (DATA_DIR / "kb.sqlite3")
        # ThreadingHTTPServer serves each request on its own thread. A single
        # sqlite3 connection is not shareable across threads, so keep one
        # connection per thread (SQLite itself is happy with WAL + readers).
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def init(self, seed_path: pathlib.Path | str | None = None) -> "KnowledgeBase":
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                source TEXT NOT NULL DEFAULT 'user_note'
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                id UNINDEXED,
                text,
                tokenize = 'unicode61'
            );
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_title TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                material TEXT NOT NULL DEFAULT '',
                symptom TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                client_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(client_id, run_id, step_title)
            );
            CREATE INDEX IF NOT EXISTS idx_receipts_match
                ON receipts(model, material, symptom, created_at);
            """
        )
        self.conn.commit()
        count = self.conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"]
        if count == 0:
            self.seed(seed_path)
        return self

    def seed(self, seed_path: pathlib.Path | str | None = None) -> int:
        path = pathlib.Path(seed_path) if seed_path else (DATA_DIR / "kb_seed.json")
        if not path.exists():
            return 0
        notes = json.loads(path.read_text(encoding="utf-8"))
        for note in notes:
            self.add(note, commit=False)
        self.conn.commit()
        return len(notes)

    def add(self, note: dict, commit: bool = True) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO notes (id,title,body,tags,created_at,status,source)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                note["id"], note["title"], note["body"], note.get("tags", ""),
                note.get("created_at", ""), note.get("status", "active"),
                note.get("source", "user_note"),
            ),
        )
        self.conn.execute("DELETE FROM notes_fts WHERE id = ?", (note["id"],))
        self.conn.execute(
            "INSERT INTO notes_fts (id, text) VALUES (?, ?)",
            (note["id"], index_text(note["title"], note["body"], note.get("tags", ""))),
        )
        if commit:
            self.conn.commit()

    def all(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM notes ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def search(self, query: str, k: int = 4) -> list[dict]:
        match = fts_match(query)
        if not match:
            return []
        rows = self.conn.execute(
            """
            SELECT n.*, bm25(notes_fts) AS rank
            FROM notes_fts f JOIN notes n ON n.id = f.id
            WHERE notes_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, max(k * 3, 8)),
        ).fetchall()
        results = []
        for row in rows:
            note = dict(row)
            note.pop("rank", None)
            text = f"{note['title']} {note['body']} {note['tags']}"
            note["relevance"] = round(min(1.0, _overlap(query, text)), 3)
            note["stale"] = note.get("status") != "active"
            results.append(note)
        results.sort(key=lambda n: (n["relevance"], n["title"]), reverse=True)
        return results[:k]

    def add_receipt(self, receipt: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT OR REPLACE INTO receipts"
            " (run_id,step_title,model,material,symptom,outcome,note,client_id,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                receipt["run_id"], receipt["step_title"], receipt.get("model", ""),
                receipt.get("material", ""), receipt.get("symptom", ""),
                receipt["outcome"], receipt.get("note", "")[:300],
                receipt["client_id"], now,
            ),
        )
        self.conn.commit()
        return {"saved": True, "created_at": now}

    def receipt_summary(self, model: str = "", material: str = "", symptom: str = "") -> list[dict]:
        """Only receipts that match the same model/material/symptom, 180 days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat(timespec="seconds")
        rows = self.conn.execute(
            "SELECT step_title,outcome,created_at FROM receipts"
            " WHERE model=? AND material=? AND symptom=? AND created_at>=?",
            (model, material, symptom, cutoff),
        ).fetchall()
        now = datetime.now(timezone.utc)
        buckets: dict[str, dict] = {}
        for row in rows:
            bucket = buckets.setdefault(row["step_title"], {
                "step_title": row["step_title"], "fixed": 0, "not_fixed": 0,
                "weekly_fixed": 0.0, "last_at": "",
            })
            if row["outcome"] == "fixed":
                bucket["fixed"] += 1
                try:
                    age = (now - datetime.fromisoformat(row["created_at"])).days
                except ValueError:
                    age = 0
                bucket["weekly_fixed"] += 0.5 ** (max(0, age) / 90)
            elif row["outcome"] == "not_fixed":
                bucket["not_fixed"] += 1
            if row["created_at"] > bucket["last_at"]:
                bucket["last_at"] = row["created_at"]
        out = []
        for bucket in buckets.values():
            total = bucket["fixed"] + bucket["not_fixed"]
            bucket["total"] = total
            bucket["weight"] = round(min(0.15, bucket["weekly_fixed"] * 0.02), 4)
            bucket["visible"] = total >= 3
            bucket["last_at"] = bucket["last_at"][:10]
            out.append(bucket)
        out.sort(key=lambda b: (b["fixed"], b["total"]), reverse=True)
        return out

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def seed_if_empty(path: pathlib.Path | str | None = None) -> KnowledgeBase:
    return KnowledgeBase(path).init()
