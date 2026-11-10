"""Evidence fusion: dedupe, rank, extract claims, find conflicts, check coverage.

The outer brain must do more than concatenate search results. Three things make
the answer trustworthy:

* source tier + freshness + authority decide what survives;
* numeric claims are extracted and compared, so a stale private note can be
  visibly corrected instead of silently averaged;
* every gap in the question plan gets a verdict: covered / partial /
  insufficient. "Not found" is a first-class result, not a failure.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from kb import STOPWORDS, tokenize
from planner import SYMPTOMS

OFFICIAL_DOMAINS = {
    "bambulab.com", "bambulab.cn", "wiki.bambulab.com", "creality.com", "creality.cn",
    "prusa3d.com", "help.prusa3d.com", "elegoo.com", "anycubic.com", "raise3d.com",
    "formlabs.com", "ultimaker.com", "markforged.com", "artillery3d.com", "sovol3d.com",
    "tencent.com", "cloud.tencent.com", "gov.cn", "who.int", "cdc.gov", "epa.gov",
    "osha.gov", "nih.gov", "fda.gov",
}
COMMUNITY_DOMAINS = {
    "reddit.com", "printables.com", "makerworld.com", "thingiverse.com", "github.com",
    "zhihu.com", "bilibili.com", "youtube.com", "all3dp.com", "3dprintbeginner.com",
    "hackaday.com", "cnc-kitchen.com", "forum.bambulab.com", "discourse.org",
}
LOW_DOMAINS = {
    "sohu.com", "163.com", "toutiao.com", "baijiahao.baidu.com", "zhidao.baidu.com",
    "wenku.baidu.com", "douyin.com", "kuaishou.com", "xiaohongshu.com",
}

ATTR_LABEL = {
    "bed_temp": "热床温度",
    "nozzle_temp": "喷嘴温度",
    "drying": "烘干制度",
    "retraction": "回抽长度",
    "retraction_speed": "回抽速度",
    "speed": "打印速度",
}

CONFLICT_THRESHOLD = {
    "bed_temp": 8,
    "nozzle_temp": 15,
    "drying": 8,
    "retraction": 0.4,
    "retraction_speed": 10,
    "speed": 30,
}

# A warping question does not need a retraction number; keeping every number
# the page happened to mention is how answers end up with irrelevant conflicts.
ALLOWED_CLAIMS = {
    "warping": {"bed_temp", "nozzle_temp", "speed"},
    "first_layer": {"bed_temp", "nozzle_temp", "speed"},
    "stringing": {"drying", "retraction", "retraction_speed", "nozzle_temp"},
    "clog": {"nozzle_temp", "retraction", "retraction_speed"},
    "surface": {"nozzle_temp", "speed", "drying"},
    "layer_shift": {"speed"},
    "safety": set(),
}

# A page can mention the printer's *maximum* rating (80°C bed / 300°C hotend)
# without recommending it for this material. Keep claims inside a material
# window so a spec sheet cannot silently become the answer.
MATERIAL_LIMITS = {
    "PLA": {"bed_temp": (40, 70), "nozzle_temp": (150, 260), "drying": (30, 70), "retraction": (0, 6), "retraction_speed": (0, 90), "speed": (5, 300)},
    "PETG": {"bed_temp": (55, 100), "nozzle_temp": (200, 290), "drying": (40, 90), "retraction": (0, 10), "retraction_speed": (0, 90), "speed": (5, 300)},
    "ABS": {"bed_temp": (70, 120), "nozzle_temp": (220, 300), "drying": (40, 100), "retraction": (0, 10), "retraction_speed": (0, 90), "speed": (5, 300)},
    "ASA": {"bed_temp": (70, 120), "nozzle_temp": (220, 300), "drying": (40, 100), "retraction": (0, 10), "retraction_speed": (0, 90), "speed": (5, 300)},
    "TPU": {"bed_temp": (20, 80), "nozzle_temp": (180, 260), "drying": (30, 80), "retraction": (0, 6), "retraction_speed": (0, 60), "speed": (5, 120)},
    "尼龙": {"bed_temp": (40, 120), "nozzle_temp": (220, 310), "drying": (50, 110), "retraction": (0, 10), "retraction_speed": (0, 90), "speed": (5, 300)},
}
GENERIC_LIMITS = {
    "bed_temp": (20, 160),
    "nozzle_temp": (140, 350),
    "drying": (25, 120),
    "retraction": (0, 15),
    "retraction_speed": (0, 150),
    "speed": (5, 800),
}

GAP_KEYWORDS = {
    "official_parameter": [["热床", "喷嘴", "平台", "温度", "Z偏移", "调平", "首层"],
                            ["温度", "℃", "速度", "mm", "偏移", "调平"]],
    "stale_private_note": [["官方", "推荐", "建议", "更新"], ["温度", "参数", "℃"]],
    "verify_conflict": [["官方", "推荐", "建议"], ["温度", "参数", "℃"]],
    "symptom_mechanism": [["原因", "导致", "因为", "由于"], ["解决", "处理", "建议", "先"]],
    "model_experience": [["原因", "问题", "经验"], ["处理", "解决", "建议"]],
    "material_condition": [["烘干", "干燥", "受潮"], ["温度", "℃", "小时"]],
    "freshness": [["固件", "版本", "更新", "批次"], ["问题", "修复", "回滚", "召回"]],
    "official_safety": [["通风", "手套", "护目镜", "防护"], ["皮肤", "吸入", "废液", "安全"]],
    "safety_mechanism": [["气味", "通风", "毒性", "皮肤"], ["风险", "安全", "建议"]],
    "waste": [["废液", "清洗", "树脂", "危险废物"], ["处理", "回收", "合规", "倒入"]],
    "environment": [["空调", "环境", "气流", "湿度"], ["温度", "影响", "导致"]],
    "rule_out": [["排除", "不是", "无效", "先确认"], ["原因", "问题", "方向"]],
    "clarify_model": [],
    "clarify_symptom": [],
}

PATTERNS = [
    ("bed_temp", r"(?:热床|平台|床温|bed)[^。；，,]{0,18}?(\d{2,3})\s*[-–~到至]\s*(\d{2,3})\s*(?:℃|°c|度)", "range"),
    ("bed_temp", r"(?:热床|平台|床温|bed)[^。；，,]{0,18}?(\d{2,3})\s*(?:℃|°c|度)", "single"),
    ("bed_temp", r"(\d{2,3})\s*(?:℃|°c|度)[^。；，,]{0,12}?(?:热床|平台)", "single"),
    ("nozzle_temp", r"(?:喷嘴|喷头|nozzle)[^。；，,]{0,18}?(\d{3})\s*[-–~到至]\s*(\d{3})\s*(?:℃|°c|度)", "range"),
    ("nozzle_temp", r"(?:喷嘴|喷头|nozzle)[^。；，,]{0,18}?(\d{3})\s*(?:℃|°c|度)", "single"),
    ("drying", r"(?:\d{2,3})\s*(?:℃|°c|度)\s*(?:烘干|干燥)[^。；，,]{0,14}?(\d{1,2})\s*(?:小时|h|H)", "drying"),
    ("drying", r"(?:烘干|干燥)[^。；，,]{0,22}?(\d{2,3})\s*(?:℃|°c|度)[^。；，,]{0,14}?(\d{1,2})\s*(?:小时|h|H)", "drying"),
    ("drying", r"(?:推荐|必须)\s*(\d{2,3})\s*(?:℃|°c|度)\s*,?\s*(\d{1,2})\s*(?:小时|h|H)", "drying"),
    ("retraction", r"(?:回抽|retraction)[^。；，,]{0,14}?(\d+(?:\.\d+)?)\s*[-–~到至]\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)", "range"),
    ("retraction", r"(?:回抽|retraction)[^。；，,]{0,14}?(\d+(?:\.\d+)?)\s*(?:mm|毫米)", "single"),
    ("retraction_speed", r"(?:回抽速度|retraction speed)[^。；，,]{0,12}?(\d{1,4})\s*(?:mm/s|毫米/秒)", "single"),
    ("speed", r"(?:打印速度|首层速度|外壁速度|填充速度)[^。；，,]{0,12}?(\d{1,4})\s*(?:mm/s|毫米/秒)", "single"),
    ("speed", r"(\d{1,4})\s*(?:mm/s|毫米/秒)[^。；，,]{0,10}?(?:打印速度|首层速度)", "single"),
]

CLAIM_KEEP = re.compile(r"热床|平台|喷嘴|喷头|烘干|干燥|回抽|速度|℃|度|mm|小时")


def _host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().split(":")[0]
    except ValueError:
        return ""


def _domain_match(host: str, domains: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def source_tier(url: str, site: str = "", authority: int | None = None) -> str:
    host = _host(url) or (site or "").lower()
    if _domain_match(host, OFFICIAL_DOMAINS):
        return "official"
    if _domain_match(host, LOW_DOMAINS):
        return "low"
    if _domain_match(host, COMMUNITY_DOMAINS):
        return "community"
    if authority is not None and authority >= 4:
        return "official"
    if authority is not None and authority >= 2:
        return "community"
    return "general"


TIER_WEIGHT = {"official": 1.0, "community": 0.68, "general": 0.48, "low": 0.22}
TIER_LABEL = {"official": "官方/权威", "community": "社区", "general": "一般网页", "low": "低置信"}


def parse_date(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        match = re.search(r"(\d{4})-(\d{1,2})", text)
        if not match:
            return None
        year, month = int(match.group(1)), int(match.group(2))
        day = 1
    else:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def age_days(value) -> float | None:
    parsed = parse_date(value)
    if not parsed:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400)


def required_age_days(params: dict) -> float | None:
    value = params.get("Freshness")
    if not value:
        return None
    value = str(value)
    match = re.match(r"^([dmy])(\d+)$", value)
    if match:
        unit, number = match.group(1), int(match.group(2))
        return {"d": 1, "m": 30.4, "y": 365.0}[unit] * number
    if "~" in value:
        return None
    return None


def freshness_fit(value, required: float | None) -> float:
    age = age_days(value)
    if age is None:
        return 0.45
    if required is not None:
        if age <= required:
            return 1.0
        return max(0.1, math.exp(-(age - required) / 365.0))
    return max(0.2, math.exp(-age / 540.0))


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；\n])", text or "")
    return [p.strip(" \t\r\n-·") for p in parts if 8 <= len(p.strip()) <= 180]


def _lexical_relevance(query: str, title: str, passage: str) -> float:
    """Lite responses often omit `score`; lexical overlap is the fallback.

    A page that repeats the model + material + symptom is more useful than a
    generic spec sheet, even when the API gives both the same rank.
    """
    q = {t for t in tokenize(query) if len(t) >= 2 and t not in STOPWORDS}
    if not q:
        return 0.0
    body = {t for t in tokenize(f"{title} {passage}") if len(t) >= 2}
    head = {t for t in tokenize(title) if len(t) >= 2}
    if not body:
        return 0.0
    body_cover = len(q & body) / len(q)
    title_cover = len(q & head) / len(q)
    return round(min(1.0, (0.55 * body_cover + 0.45 * title_cover) * 1.8), 3)


def _context_ok(text: str, match: re.Match, attribute: str, material: str = "") -> bool:
    start, end = match.start(), match.end()
    window = text[max(0, start - 24): min(len(text), end + 24)]
    if attribute in {"bed_temp", "nozzle_temp", "drying", "speed", "retraction_speed"}:
        if re.search(r"最高|最大|上限|不超过|可达|支持|至少", window):
            return False
    if attribute == "drying":
        # Bambu's table has a "Support for PLA/PETG 60℃" row before the
        # PETG row. That is a support-material schedule, not PETG's.
        if re.search(r"support|支撑", text[max(0, start - 40):start].lower()):
            return False
    if attribute == "bed_temp" and re.search(r"环境温度|室温", window):
        if not re.search(r"热床|平台|床温", window):
            return False
    if attribute == "speed" and re.search(r"回抽|空驶|移动|加速度|冷却", window):
        return False
    if material and material in MATERIAL_LIMITS:
        # "PLA 50–60; PETG 60–70" must not yield a PETG number for a PLA
        # question. Use the nearest material word *before* the number.
        prefix = text[max(0, start - 90):start].lower()
        nearest, nearest_pos = "", -1
        for word in MATERIAL_LIMITS:
            pos = prefix.rfind(word.lower())
            if pos > nearest_pos:
                nearest, nearest_pos = word, pos
        if nearest and nearest.lower() != material.lower():
            return False
    return True


def _plausible(attribute: str, low: float, high: float, material: str) -> bool:
    limits = MATERIAL_LIMITS.get(material or "", {})
    bound = limits.get(attribute) or GENERIC_LIMITS.get(attribute)
    if not bound:
        return True
    return bound[0] <= low and high <= bound[1]


DOMAIN_WORDS = [
    "3d", "打印", "printer", "热床", "喷嘴", "喷头", "耗材", "首层", "调平",
    "bambu", "拓竹", "创想", "creality", "elegoo", "光固化", "树脂", "filament",
]
SAFETY_REJECT = re.compile(r"环评|生态环境局|建设项目|审批|受理|公示")


def _topic_ok(plan: dict, page: dict) -> bool:
    """Reject pages that merely share a model token.

    "K1 固件" also retrieves a TV firmware guide and a Phicomm router manual.
    A model name alone is not a topic: require a 3D-printing context token.
    """
    slots = plan.get("slots") or {}
    model = str(slots.get("model") or "").lower()
    material = str(slots.get("material") or "").lower()
    symptom = slots.get("symptom") or {}
    meta = SYMPTOMS.get(symptom.get("id", ""), {})
    words = [str(w).lower() for w in (meta.get("keywords") or [])]
    text = f"{page.get('title', '')} {page.get('passage', '')} {page.get('content', '')}".lower()
    if model:
        aliases = {model, model.replace(" ", "")}
        if not any(alias in text for alias in aliases):
            # Generic symptom pages are useful; a page about a *different*
            # printer is not. "3D Printer First Layer Problems" passes,
            # "Ender-3 first layer" does not pass for an A1 mini question.
            other_model = re.search(r"ender|prusa|saturn|mars 5|p1p|x1 carbon|k1 max", text)
            if other_model and model not in {"ender-3", "prusa mk4", "saturn 4", "mars 5", "p1p", "x1 carbon", "k1 max"}:
                return False
            if not (material and material in text) and not any(word in text for word in words):
                return False
        if model in {"k1", "a1", "a1 mini"} and not any(word in text for word in DOMAIN_WORDS):
            return False
    if symptom.get("id") == "safety" and "树脂" in text:
        if SAFETY_REJECT.search(text) and not re.search(r"安全|防护|通风|手套", page.get("title", "")):
            return False
    return True


def _symptom_score(plan: dict, page: dict) -> float:
    symptom = (plan.get("slots") or {}).get("symptom") or {}
    meta = SYMPTOMS.get(symptom.get("id", ""), {})
    words = list(meta.get("keywords") or []) + list(symptom.get("keywords") or [])
    words += list(symptom.get("mechanisms") or [])
    if not words:
        return 0.0
    text = f"{page.get('title', '')} {page.get('passage', '')} {page.get('content', '')}".lower()
    hits = sum(1 for word in set(words) if str(word).lower() in text)
    return round(min(1.0, hits / 3.0), 3)


def extract_claims_from_text(text: str, sid: str = "", date: str = "", tier: str = "general",
                             material: str = "") -> list[dict]:
    claims: list[dict] = []
    for attribute, pattern, kind in PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if not _context_ok(text, match, attribute, material):
                continue
            sentence = next((s for s in _sentences(text) if match.group(0) in s), match.group(0))
            if not CLAIM_KEEP.search(sentence):
                continue
            try:
                if kind == "range":
                    low, high = float(match.group(1)), float(match.group(2))
                    if not _plausible(attribute, low, high, material):
                        continue
                    value = round((low + high) / 2, 1)
                    unit = "℃" if attribute in ("bed_temp", "nozzle_temp", "drying") else (
                        "mm" if attribute == "retraction" else ("mm/s" if attribute in ("speed", "retraction_speed") else ""))
                    claims.append({
                        "sid": sid, "attribute": attribute, "label": ATTR_LABEL.get(attribute, attribute),
                        "value": value, "value_low": low, "value_high": high,
                        "unit": unit,
                        "text": sentence[:140], "date": date, "tier": tier,
                        "official": tier == "official",
                    })
                    continue
                value = float(match.group(1))
                if not _plausible(attribute, value, value, material):
                    continue
                unit = "℃" if attribute in ("bed_temp", "nozzle_temp", "drying") else (
                    "mm" if attribute == "retraction" else ("mm/s" if attribute in ("speed", "retraction_speed") else ""))
                if kind == "drying":
                    claims.append({
                        "sid": sid, "attribute": attribute, "label": ATTR_LABEL.get(attribute, attribute),
                        "value": value, "value_low": value, "value_high": value, "unit": unit,
                        "hours": float(match.group(2)), "text": sentence[:140], "date": date,
                        "tier": tier, "official": tier == "official",
                    })
                else:
                    claims.append({
                        "sid": sid, "attribute": attribute, "label": ATTR_LABEL.get(attribute, attribute),
                        "value": value, "value_low": value, "value_high": value, "unit": unit,
                        "text": sentence[:140], "date": date, "tier": tier,
                        "official": tier == "official",
                    })
            except (ValueError, IndexError):
                continue
    deduped = {}
    for claim in claims:
        key = (claim["attribute"], round(claim["value"], 1), claim["sid"])
        deduped.setdefault(key, claim)
    values = list(deduped.values())
    # A range and its own endpoint ("60–65℃ ... 65℃") are one claim, not two.
    ranges = [c for c in values if c["value_high"] > c["value_low"]]
    filtered = []
    for claim in values:
        if claim["value_high"] == claim["value_low"] and any(
            r["sid"] == claim["sid"] and r["attribute"] == claim["attribute"]
            and r["value_low"] <= claim["value"] <= r["value_high"]
            for r in ranges
        ):
            continue
        filtered.append(claim)
    return filtered


def _conflicts(claims: list[dict], kb_hits: list[dict], material: str = "") -> list[dict]:
    conflicts: list[dict] = []
    by_attr: dict[str, list[dict]] = {}
    for claim in claims:
        by_attr.setdefault(claim["attribute"], []).append(claim)

    for attribute, group in by_attr.items():
        sids = {c["sid"] for c in group}
        if len(sids) < 2:
            continue
        values = [c["value"] for c in group]
        spread = max(values) - min(values)
        if spread <= CONFLICT_THRESHOLD.get(attribute, 10):
            continue
        ordered = sorted(group, key=lambda c: (0 if c["official"] else 1, -(c.get("value") or 0)))
        official = next((c for c in ordered if c["official"]), None)
        groups_text = []
        for claim in ordered[:4]:
            low = claim.get("value_low", claim["value"])
            high = claim.get("value_high", claim["value"])
            span = f"{low:g}" if low == high else f"{low:g}–{high:g}"
            groups_text.append(f"{'官方' if claim['official'] else '其他来源'} {span}{claim['unit']}")
        conflicts.append({
            "id": f"K{len(conflicts) + 1}",
            "type": "public_disagreement",
            "attribute": attribute,
            "label": ATTR_LABEL.get(attribute, attribute),
            "severity": "high" if spread >= CONFLICT_THRESHOLD.get(attribute, 10) * 1.6 else "medium",
            "spread": round(spread, 1),
            "claims": ordered[:6],
            "preferred": official or ordered[0],
            "summary": f"{ATTR_LABEL.get(attribute, attribute)}说法不一致：" + "；".join(groups_text) + "。",
        })

    # Private KB vs public evidence. This is the conflict that matters most:
    # the user's own old note is often the thing that needs correcting.
    for note in kb_hits:
        note_text = f"{note.get('title', '')}。{note.get('body', '')}"
        kb_claims = extract_claims_from_text(note_text, sid=f"KB:{note.get('id', '')}",
                                             date=note.get("created_at", ""), tier="private",
                                             material=material)
        for claim in kb_claims:
            same = [c for c in claims if c["attribute"] == claim["attribute"]]
            if len(same) < 2:
                continue
            preferred = next((c for c in same if c["official"]), same[0])
            # A note inside any official interval is not a conflict, even if
            # the interval's lower endpoint is what `preferred` stores.
            officials = [c for c in same if c["official"]]
            if any(c.get("value_low", c["value"]) <= claim["value"] <= c.get("value_high", c["value"])
                   for c in officials):
                continue
            # Compare against the value we would actually recommend, not the
            # median of a noisy set: otherwise "65 vs 65" can be reported as
            # a 15-degree conflict.
            low = preferred.get("value_low", preferred["value"])
            high = preferred.get("value_high", preferred["value"])
            if low <= claim["value"] <= high:
                continue
            spread = min(abs(claim["value"] - low), abs(claim["value"] - high))
            if spread <= CONFLICT_THRESHOLD.get(claim["attribute"], 10):
                continue
            conflicts.append({
                "id": f"K{len(conflicts) + 1}",
                "type": "kb_vs_public",
                "attribute": claim["attribute"],
                "label": ATTR_LABEL.get(claim["attribute"], claim["attribute"]),
                "severity": "high",
                "spread": round(spread, 1),
                "kb": claim,
                "preferred": preferred,
                "claims": [claim, preferred],
                "summary": (
                    f"你的旧笔记写 {claim['value']:g}{claim['unit']}，"
                    f"公开资料更接近 {preferred['value']:g}{preferred['unit']}，"
                    f"相差 {spread:g}{claim['unit']}。"
                ),
            })
    return conflicts[:4]


def _gap_verdict(gap: dict, texts: list[str], evidence_ids: list[str]) -> dict:
    groups = GAP_KEYWORDS.get(gap.get("type", ""), [])
    if not groups:
        return {"status": "insufficient", "matched": 0, "evidence": evidence_ids[:2],
                "note": "这个问题需要用户补充信息，检索无法替代。"}
    required = 1 if gap.get("type") in {"symptom_mechanism", "environment", "rule_out", "model_experience"} else 2
    matched = []
    for index, text in enumerate(texts):
        hit = sum(1 for group in groups if any(keyword.lower() in text.lower() for keyword in group))
        if hit >= required:
            matched.append(index)
    if len(matched) >= 2:
        status = "covered"
        note = f"{len(matched)} 条独立证据覆盖了这个缺口。"
    elif len(matched) == 1:
        status = "partial"
        note = "只有一条证据，结论需要保守表述。"
    else:
        status = "insufficient"
        note = "公开资料没有给出足够证据；这类缺口应该变成追问，而不是编一个答案。"
    return {
        "status": status,
        "matched": len(matched),
        "evidence": [evidence_ids[i] for i in matched[:3] if i < len(evidence_ids)],
        "note": note,
    }


def fuse(plan: dict, results: list[dict], kb_hits: list[dict]) -> dict:
    material = str((plan.get("slots") or {}).get("material") or "")
    symptom_id = str(((plan.get("slots") or {}).get("symptom") or {}).get("id") or "")
    allowed = ALLOWED_CLAIMS.get(symptom_id)
    max_by_query: dict[str, float] = {}
    for result in results:
        qid = result.get("qid", "")
        scores = []
        for page in result.get("pages", []):
            try:
                scores.append(float(page.get("score") or 0))
            except (TypeError, ValueError):
                continue
        max_by_query[qid] = max(scores) if scores else 0.0

    merged: dict[str, dict] = {}
    for result in results:
        qid = result.get("qid", "")
        query_required = required_age_days(result.get("params", {}))
        for page in result.get("pages", []):
            url = (page.get("url") or "").strip()
            if not url:
                continue
            if not _topic_ok(plan, page):
                continue
            key = url.split("#")[0].rstrip("/")
            try:
                raw_score = float(page.get("score") or 0)
            except (TypeError, ValueError):
                raw_score = 0.0
            max_score = max_by_query.get(qid, 0.0)
            relevance = raw_score / max_score if max_score > 1.2 and max_score > 0 else min(max(raw_score, 0.0), 1.0)
            relevance = max(0.0, min(1.0, relevance))
            lexical = None
            if max_score <= 0:
                # Lite SearchPro responses carry no score at all. Fall back to
                # lexical coverage instead of letting every page tie at zero.
                lexical = _lexical_relevance(result.get("query", ""), page.get("title", ""),
                                             page.get("passage", "") or page.get("content", ""))
                relevance = max(relevance, lexical)
            symptom_score = _symptom_score(plan, page)
            if relevance < 0.12 and symptom_score < 0.34:
                continue
            authority = page.get("authority_level")
            try:
                authority = int(authority) if authority is not None else None
            except (TypeError, ValueError):
                authority = None
            tier = source_tier(url, page.get("site", ""), authority)
            fresh = freshness_fit(page.get("date", ""), query_required)
            authority_bonus = 0.5 + 0.1 * (authority if authority is not None else {"official": 4, "community": 2, "general": 1, "low": 0}[tier])
            rank = (0.36 * relevance + 0.22 * TIER_WEIGHT[tier] + 0.12 * fresh
                    + 0.08 * min(1.0, authority_bonus) + 0.22 * symptom_score)
            rank *= 0.9 + 0.1 * float(result.get("weight", 1.0))
            if key in merged:
                existing = merged[key]
                existing["covers"] = sorted(set(existing["covers"]) | set(result.get("covers", [])))
                existing["qids"] = sorted(set(existing["qids"]) | {qid})
                existing["rank"] = max(existing["rank"], round(rank, 4))
                existing["relevance"] = max(existing["relevance"], round(relevance, 3))
                existing["symptom_score"] = max(existing["symptom_score"], symptom_score)
                continue
            merged[key] = {
                "title": (page.get("title") or "无标题").strip(),
                "url": url,
                "site": (page.get("site") or _host(url)).strip(),
                "date": (page.get("date") or "").strip(),
                "passage": (page.get("passage") or "").strip(),
                "content": (page.get("content") or "").strip()[:1200],
                "score_raw": round(raw_score, 3),
                "relevance": round(relevance, 3),
                "relevance_source": "lexical" if max_score <= 0 else "score",
                "symptom_score": symptom_score,
                "authority_level": authority,
                "tier": tier,
                "tier_label": TIER_LABEL[tier],
                "freshness": round(fresh, 3),
                "rank": round(rank, 4),
                "qids": [qid],
                "covers": list(result.get("covers", [])),
                "replayed": bool(result.get("replayed")),
            }

    evidence = sorted(merged.values(), key=lambda item: item["rank"], reverse=True)[:10]
    for index, item in enumerate(evidence, start=1):
        item["id"] = f"S{index}"

    claims: list[dict] = []
    for item in evidence:
        text = item["passage"] or item["content"]
        for claim in extract_claims_from_text(text, sid=item["id"], date=item["date"], tier=item["tier"],
                                              material=material):
            if allowed is not None and claim["attribute"] not in allowed:
                continue
            claims.append(claim)
    for index, claim in enumerate(claims, start=1):
        claim["id"] = f"C{index}"

    conflicts = _conflicts(claims, kb_hits, material)

    evidence_texts = [f"{e['title']} {e['passage']} {e['content']}" for e in evidence]
    evidence_ids = [e["id"] for e in evidence]
    gaps = []
    for gap in plan.get("gaps", []):
        gap_copy = dict(gap)
        if gap_copy.get("action") == "ask_user":
            gap_copy.update(status="need_user", evidence=[], note="需要用户补充，检索无法替代。")
        else:
            qids = {q["id"] for q in plan.get("queries", []) if gap["id"] in q.get("covers", [])}
            # Coverage is a property of the evidence set, not of which query
            # happened to return the page. A rule-out sentence on the official
            # page still rules out the hypothesis even if Q1 was the one that
            # fetched it.
            texts = evidence_texts
            ids = evidence_ids
            verdict = _gap_verdict(gap, texts, ids)
            verdict["qids"] = sorted(qids)
            if gap_copy.get("type") == "stale_private_note" and any(n.get("stale") for n in kb_hits):
                verdict.update(status="covered", note="已定位到私域旧笔记，并在回答中与公开资料对照。")
            if gap_copy.get("type") == "verify_conflict" and verdict["status"] in ("partial", "insufficient"):
                tiers = {e["tier"] for e in evidence}
                if "official" in tiers and ("community" in tiers or "general" in tiers):
                    verdict.update(status="covered", matched=max(1, verdict.get("matched", 0)),
                                   evidence=evidence_ids[:2],
                                   note="官方与社区说法不一致，已在回答中显式对比。")
            gap_copy.update(verdict)
        gaps.append(gap_copy)

    official_count = sum(1 for e in evidence if e["tier"] == "official")
    fresh_count = sum(1 for e in evidence if e["freshness"] >= 0.8)
    stats = {
        "evidence_count": len(evidence),
        "official": official_count,
        "community": sum(1 for e in evidence if e["tier"] == "community"),
        "general": sum(1 for e in evidence if e["tier"] == "general"),
        "low": sum(1 for e in evidence if e["tier"] == "low"),
        "fresh": fresh_count,
        "claims": len(claims),
        "conflicts": len(conflicts),
        "calls": len(results),
        "failed_calls": sum(1 for r in results if r.get("error")),
        "latency_ms": sum(int(r.get("latency_ms") or 0) for r in results),
        "request_ids": [r.get("request_id") for r in results if r.get("request_id")],
        "replayed": any(r.get("replayed") for r in results),
    }
    return {
        "evidence": evidence,
        "claims": claims,
        "conflicts": conflicts,
        "gaps": gaps,
        "stats": stats,
    }
