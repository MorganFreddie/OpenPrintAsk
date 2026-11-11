"""Load the editable 3D-printing vocabulary.

The vocabulary is data, not code: models, materials, symptom words, environment
words and "already tried" phrases can be corrected without touching planner.py.
This is the layer a user can safely contribute to.
"""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache

from config import DATA_DIR


class LexiconError(ValueError):
    pass


@lru_cache(maxsize=1)
def get_lexicon(path: str | None = None) -> dict:
    file = pathlib.Path(path) if path else (DATA_DIR / "lexicon.json")
    if not file.exists():
        return {}
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LexiconError(f"lexicon.json 读取失败：{exc}") from exc
    if not isinstance(data, dict):
        raise LexiconError("lexicon.json 顶层必须是对象")
    for key in ("models", "materials", "symptoms", "environments"):
        if key not in data:
            raise LexiconError(f"lexicon.json 缺少 {key}")
    return data


def reload_lexicon() -> dict:
    get_lexicon.cache_clear()
    return get_lexicon()
