"""The question compiler.

A novice says: "A1 mini 打 PLA 老翘边，60 度热床加胶水也没用，是不是机器坏了？"

A search engine can answer that string, but it answers the *wrong* question:
it will return generic warping listicles. This module turns the complaint into
a small set of typed questions -- what the private KB already knows, what it is
missing, which official baseline is needed, whether the fact has a shelf life,
and which variables have already been ruled out. Those questions become the
SearchPro query plan.
"""
from __future__ import annotations

import re

from lexicon import get_lexicon

MODE_LABEL = {0: "公网", 1: "权威垂类", 2: "混合"}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

MODEL_META = {
    "A1 mini": {"brand": "Bambu Lab", "site": "wiki.bambulab.com"},
    "A1": {"brand": "Bambu Lab", "site": "wiki.bambulab.com"},
    "P1S": {"brand": "Bambu Lab", "site": "wiki.bambulab.com"},
    "P1P": {"brand": "Bambu Lab", "site": "wiki.bambulab.com"},
    "X1 Carbon": {"brand": "Bambu Lab", "site": "wiki.bambulab.com"},
    "K1": {"brand": "Creality", "site": "creality.com"},
    "K1C": {"brand": "Creality", "site": "creality.com"},
    "K1 Max": {"brand": "Creality", "site": "creality.com"},
    "Ender-3 V3": {"brand": "Creality", "site": "creality.com"},
    "Ender-3": {"brand": "Creality", "site": "creality.com"},
    "Saturn 4": {"brand": "Elegoo", "site": "elegoo.com"},
    "Saturn 4 Ultra": {"brand": "Elegoo", "site": "elegoo.com"},
    "Mars 5": {"brand": "Elegoo", "site": "elegoo.com"},
    "Prusa MK4": {"brand": "Prusa", "site": "help.prusa3d.com"},
}

MODEL_ALIASES = sorted(
    [
        ("a1 mini", "A1 mini"), ("a1mini", "A1 mini"), ("a1 mini combo", "A1 mini"),
        ("p1s", "P1S"), ("p1p", "P1P"), ("x1 carbon", "X1 Carbon"), ("x1c", "X1 Carbon"),
        ("k1 max", "K1 Max"), ("k1c", "K1C"), ("k1", "K1"),
        ("ender-3 v3", "Ender-3 V3"), ("ender3 v3", "Ender-3 V3"), ("ender-3", "Ender-3"),
        ("saturn 4 ultra", "Saturn 4 Ultra"), ("saturn 4", "Saturn 4"), ("mars 5", "Mars 5"),
        ("prusa mk4", "Prusa MK4"), ("mk4", "Prusa MK4"),
    ],
    key=lambda item: len(item[0]),
    reverse=True,
)

MATERIALS = [
    ("PLA", ["pla", "聚乳酸"], False),
    ("PETG", ["petg"], True),
    ("ABS", ["abs"], True),
    ("ASA", ["asa"], True),
    ("TPU", ["tpu", "柔性材料"], True),
    ("尼龙", ["尼龙", "nylon", "pa6", "pa12"], True),
    ("光敏树脂", ["光敏树脂", "树脂", "resin"], False),
]

SYMPTOMS = {
    "warping": {
        "label": "翘边 / 首层脱落",
        "keywords": ["翘边", "翘起", "卷边", "边角翘", "脱落", "掉了", "掉件", "不粘", "粘不住", "粘不牢", "warping", "warp", "detach", "curling", "bed adhesion", "first layer adhesion"],
        "mechanisms": ["首层附着", "热床温度", "平台清洁", "环境气流", "首层压缩量"],
        "query_symptom": "首层 翘边 附着 原因",
        "parameter_sensitive": True,
    },
    "first_layer": {
        "label": "首层异常（厚度 / 附着）",
        "keywords": ["首层", "第一层", "z偏移", "z-offset", "z offset", "压得薄", "压得太薄", "首层变差", "首层不平", "first layer", "squished", "too thin"],
        "mechanisms": ["Z 偏移", "调平", "首层流量", "平台状态"],
        "query_symptom": "首层 厚度 附着 异常 原因",
        "parameter_sensitive": True,
    },
    "stringing": {
        "label": "拉丝 / 渗料",
        "keywords": ["拉丝", "丝状", "渗料", "stringing", "oozing", "毛刺", "蜘蛛网", "wisps"],
        "mechanisms": ["回抽", "耗材含水率", "喷嘴温度", "空驶"],
        "query_symptom": "拉丝 渗料 原因",
        "parameter_sensitive": True,
    },
    "clog": {
        "label": "堵头 / 挤出不足",
        "keywords": ["堵头", "堵塞", "挤出不足", "下料不顺", "空打", "clog", "under-extrusion", "缺料", "jammed"],
        "mechanisms": ["热蠕变", "喷嘴磨损", "挤出机张力", "散热"],
        "query_symptom": "堵头 挤出不足 原因",
        "parameter_sensitive": True,
    },
    "layer_shift": {
        "label": "错层 / 位移",
        "keywords": ["错层", "位移", "layer shift", "层移", "打一半歪了"],
        "mechanisms": ["皮带张力", "加速度", "Z 轴", "模型固定"],
        "query_symptom": "错层 位移 原因",
        "parameter_sensitive": False,
    },
    "surface": {
        "label": "表面粗糙 / 气泡",
        "keywords": ["表面粗糙", "气泡", "麻点", "拉毛", "surface", "blob", "zits"],
        "mechanisms": ["耗材含水率", "流量", "温度", "冷却"],
        "query_symptom": "表面粗糙 气泡 原因",
        "parameter_sensitive": True,
    },
    "safety": {
        "label": "气味 / 安全边界",
        "keywords": ["安全", "有毒", "气味", "孕妇", "小孩", "卧室", "通风", "皮肤", "过敏", "废液", "毒性", "safety", "toxic", "ventilation", "fumes", "VOC"],
        "mechanisms": ["通风", "皮肤接触", "废液处理", "房间选择"],
        "query_symptom": "气味 安全 通风",
        "parameter_sensitive": False,
    },
}

ENV_WORDS = [
    ("aircon", "空调直吹", ["空调", "直吹"]),
    ("window", "窗边/开门", ["窗边", "开窗", "门开", "阳台"]),
    ("humidity", "潮湿天气", ["潮湿", "湿度", "回南天", "下雨"]),
    ("cold", "低温环境", ["冬天", "低温", "冷"]),
    ("bedroom", "卧室/居住空间", ["卧室", "睡房", "宿舍"]),
]

TRIED_WORDS = [
    ("adhesive", "胶水/胶棒", ["胶水", "固体胶", "发胶", "胶棒"]),
    ("brim", "裙边/raft", ["裙边", "brim", "raft", "底座"]),
    ("drying", "烘干", ["烘干", "干燥", "烘干箱"]),
    ("leveling", "调平/Z 偏移", ["调平", "leveling", "z偏移", "z-offset", "z offset"]),
    ("cleaning", "平台清洁", ["洗洁精", "酒精", "擦平台", "清洗"]),
    ("speed", "降速", ["降速", "慢一点", "速度调低"]),
    ("retraction", "调回抽", ["回抽", "retraction"]),
]


# --------------------------------------------------------------- lexicon v2
# The lists above are the safe built-in fallback. Data/lexicon.json extends and
# overrides them, so a contributor can add a printer or a localism without
# editing Python. Unknown keys are ignored on purpose: old lexicons still work.
_LEX = get_lexicon()


def _dedupe(items):
    seen = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)


if _LEX:
    _models = _LEX.get("models") or []
    if _models:
        MODEL_META = {
            m["name"]: {
                "brand": m.get("brand", ""),
                "site": m.get("site", ""),
                "released": m.get("released", ""),
            }
            for m in _models
        }
        MODEL_ALIASES = sorted(
            [(alias.lower(), m["name"]) for m in _models for alias in m.get("aliases", [])],
            key=lambda item: len(item[0]),
            reverse=True,
        )

    _materials = _LEX.get("materials") or []
    if _materials:
        MATERIALS = [
            (m["name"], [a.lower() for a in m.get("aliases", [])], bool(m.get("hygroscopic")))
            for m in _materials
        ]

    for _sid, _spec in (_LEX.get("symptoms") or {}).items():
        if _sid in SYMPTOMS:
            SYMPTOMS[_sid]["keywords"] = _dedupe(
                list(SYMPTOMS[_sid].get("keywords", [])) + list(_spec.get("keywords", []))
            )
        else:
            SYMPTOMS[_sid] = _spec

    if _LEX.get("environments"):
        ENV_WORDS = [
            (e["kind"], e["label"], e.get("words", []))
            for e in _LEX["environments"]
        ]
    for _region in _LEX.get("regions") or []:
        ENV_WORDS.append((
            f"region_{_region['name']}",
            f"{_region['name']}（{_region.get('climate', '')}）" if _region.get("climate") else _region["name"],
            _region.get("words", []),
        ))

    if _LEX.get("tried"):
        TRIED_WORDS = [
            (t["kind"], t["label"], t.get("words", []))
            for t in _LEX["tried"]
        ]


BRAND_ALIASES = sorted(
    [(alias.lower(), b["name"]) for b in (_LEX.get("brands") or []) for alias in b.get("aliases", [])],
    key=lambda item: len(item[0]),
    reverse=True,
)
FILAMENT_BRANDS = sorted(
    [(alias.lower(), b["name"]) for b in (_LEX.get("filament_brands") or []) for alias in b.get("aliases", [])],
    key=lambda item: len(item[0]),
    reverse=True,
)
SYMPTOM_PRIORITY = [
    "safety", "clog", "warping", "first_layer", "stringing",
    "multi_color", "layer_shift", "surface",
]


def _symptom_obj(symptom_id: str) -> dict:
    spec = SYMPTOMS[symptom_id]
    return {
        "id": symptom_id,
        "label": spec["label"],
        "mechanisms": spec.get("mechanisms", []),
        "query_symptom": spec.get("query_symptom", spec["label"]),
        "parameter_sensitive": bool(spec.get("parameter_sensitive", True)),
    }


def _symptom_label(slots: dict) -> str:
    symptoms = slots.get("symptoms") or []
    if symptoms:
        return "、".join(s["label"] for s in symptoms)
    return "打印异常"


def _has(text: str, word: str) -> bool:
    return word.lower() in text.lower()


def _match_alias(text: str, alias: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _priority(symptom_id: str) -> int:
    return SYMPTOM_PRIORITY.index(symptom_id) if symptom_id in SYMPTOM_PRIORITY else 99


def extract_slots(question: str) -> dict:
    raw = (question or "").strip()
    # A pasted "case + solution" should not count the solution as something the
    # user already tried. Parse only the problem half.
    text = re.split(r"(?:解决(?:方法|办法|过程)|已解决|修复方法|处理方式)\s*[:：]", raw, maxsplit=1)[0].strip()
    low = text.lower()

    model = None
    for alias, canonical in MODEL_ALIASES:
        if _match_alias(low, alias):
            model = canonical
            break

    brand = MODEL_META.get(model, {}).get("brand") if model else None
    if not brand:
        for alias, name in BRAND_ALIASES:
            if _match_alias(low, alias):
                brand = name
                break

    material_hits = [
        canonical
        for canonical, aliases, _hygroscopic in MATERIALS
        if any(_has(low, a) for a in aliases)
    ]
    materials = _dedupe(material_hits)
    material = materials[0] if materials else None

    material_brand = None
    for alias, name in FILAMENT_BRANDS:
        if _match_alias(low, alias):
            material_brand = name
            break
    # A machine brand mentioned as "拓竹 A1" is not the filament brand.
    if material_brand and material_brand == brand and not any(
        _has(low, word) for word in ("耗材", "材料", "线材", "用料", "料盘")
    ):
        material_brand = None

    safety_hit = any(_has(low, k) for k in SYMPTOMS["safety"]["keywords"])
    safety_context = material == "光敏树脂" or any(
        _has(low, k) for k in ["有毒", "孕妇", "废液", "皮肤", "过敏", "通风", "气味"]
    )

    scores: dict[str, int] = {}
    for sid, spec in SYMPTOMS.items():
        score = sum(1 for k in spec["keywords"] if _has(low, k))
        if score:
            scores[sid] = score
    if safety_hit and safety_context:
        scores["safety"] = max(scores.get("safety", 0), 2)
    elif "safety" in scores:
        scores.pop("safety", None)

    symptom_ids = sorted(
        scores,
        key=lambda sid: (-scores[sid], _priority(sid)),
    )
    if safety_hit and safety_context:
        symptom_ids = ["safety"] + [sid for sid in symptom_ids if sid != "safety"]
    # "首层不沾" is a warping/attachment case, not two separate diseases.
    if "warping" in symptom_ids and "first_layer" in symptom_ids:
        symptom_ids.remove("first_layer")

    symptoms = [_symptom_obj(sid) for sid in symptom_ids]
    symptom = symptoms[0] if symptoms else None

    tried: list[dict] = []
    ambient: list[int] = []
    for match in re.finditer(r"(\d{2,3})\s*(?:℃|°c|度)", text, re.IGNORECASE):
        value = int(match.group(1))
        window = text[max(0, match.start() - 18):match.start()]
        # 取离数字最近的那个关键词，避免“喷头堵料，单色不堵，室温28度”
        # 因为前面 14 个字里出现“喷头”而被误判成“喷嘴 28℃”。
        positions = []
        for kind, words in (
            ("bed_temp", ("热床", "平台", "床温", "bed")),
            ("nozzle_temp", ("喷嘴", "喷头", "nozzle")),
            ("ambient_temp", ("室内", "室温", "环境", "房间", "工位")),
        ):
            pos = max((window.lower().rfind(w.lower()) for w in words), default=-1)
            if pos >= 0:
                positions.append((pos, kind))
        if positions:
            _, nearest = max(positions)
            if nearest == "bed_temp":
                tried.append({"kind": "bed_temp", "label": f"热床 {value}℃", "value": value})
            elif nearest == "nozzle_temp":
                tried.append({"kind": "nozzle_temp", "label": f"喷嘴 {value}℃", "value": value})
            else:
                ambient.append(value)
    for kind, label, words in TRIED_WORDS:
        if any(_has(low, w) for w in words):
            tried.append({"kind": kind, "label": label})
    deduped = {}
    for item in tried:
        deduped[(item["kind"], item.get("value"))] = item
    tried = list(deduped.values())

    environment = [
        {"kind": kind, "label": label}
        for kind, label, words in ENV_WORDS
        if any(_has(low, w) for w in words)
    ]
    if ambient:
        environment = [e for e in environment if e["kind"] != "hot"]
        seen = {e["kind"] for e in environment}
        for value in ambient[:2]:
            if "ambient_temp" not in seen:
                environment.append({"kind": "ambient_temp", "label": f"室温 {value}℃", "value": value})
                seen.add("ambient_temp")

    intent = {
        "freshness": any(_has(low, k) for k in ["最新", "最近", "刚", "新固件", "固件", "升级", "更新", "召回", "批次", "降价", "2026", "本月", "上周"]),
        "safety": "safety" in symptom_ids,
        "official": any(_has(low, k) for k in ["官方", "厂家", "说明书", "参数", "规格"]),
        "price": any(_has(low, k) for k in ["价格", "多少钱", "值得买", "推荐", "选机"]),
        "multi_color": "multi_color" in symptom_ids,
    }

    missing = []
    if not model:
        missing.append("model")
    if not material:
        missing.append("material")
    if not symptom:
        missing.append("symptom")

    required = 3 - len(missing)
    confidence = "high" if required == 3 else ("medium" if required == 2 else "low")
    return {
        "raw": raw,
        "parse_text": text,
        "model": model,
        "brand": brand,
        "material": material,
        "materials": materials,
        "material_brand": material_brand,
        "symptom": symptom,
        "symptoms": symptoms,
        "symptom_ids": symptom_ids,
        "tried": tried,
        "environment": environment,
        "intent": intent,
        "missing": missing,
        "confidence": confidence,
    }


def _rewrite(slots: dict) -> str:
    model = slots["model"]
    materials = slots.get("materials") or ([slots["material"]] if slots["material"] else [])
    material = "/".join(materials)
    label = _symptom_label(slots)
    if model and material:
        head = f"{model} 打 {material} 时出现「{label}」"
    elif model:
        head = f"{model} 出现「{label}」"
    elif material:
        head = f"{material} 打印出现「{label}」"
    else:
        head = f"3D 打印出现「{label}」"
    if "multi_color" in (slots.get("symptom_ids") or []):
        head += "（多色 / AMS 换料场景）"
    parts = [head]
    if slots["tried"]:
        parts.append("已经试过 " + "、".join(t["label"] for t in slots["tried"]))
    if slots["environment"]:
        parts.append("环境里有 " + "、".join(e["label"] for e in slots["environment"]))
    sentence = "；".join(parts) + "。"
    if slots["intent"]["safety"]:
        sentence += "想知道风险边界、防护要求和废液处理方式。"
    else:
        sentence += "想知道最可能的原因，以及下一步按什么顺序处理。"
    if slots["intent"]["freshness"]:
        sentence += "另外，最近是否有固件或批次相关的已知问题？"
    return sentence


def analyze_gaps(slots: dict, kb_hits: list[dict]) -> list[dict]:
    gaps: list[dict] = []

    def add(gid: str, gtype: str, priority: str, question: str, why: str,
            action: str = "search", extra: dict | None = None) -> None:
        gap = {
            "id": gid,
            "type": gtype,
            "priority": priority,
            "question": question,
            "why": why,
            "action": action,
            "status": "need_user" if action == "ask_user" else "pending",
        }
        if extra:
            gap.update(extra)
        gaps.append(gap)

    note_text = " ".join(f"{h.get('title','')} {h.get('body','')} {h.get('tags','')}" for h in kb_hits)
    model = slots["model"]
    material = slots["material"]
    materials = slots.get("materials") or ([material] if material else [])
    material_text = "/".join(materials)
    symptom = slots["symptom"]
    symptom_ids = slots.get("symptom_ids") or ([symptom["id"]] if symptom else [])
    symptom_label = _symptom_label(slots)

    model_notes = [h for h in kb_hits if model and _has(f"{h.get('title','')} {h.get('body','')} {h.get('tags','')}", model)]
    material_notes = [h for h in kb_hits if material and _has(f"{h.get('title','')} {h.get('body','')} {h.get('tags','')}", material)]
    symptom_notes = [
        h for h in kb_hits
        if symptom_ids and any(
            _has(f"{h.get('title','')} {h.get('body','')} {h.get('tags','')}", k)
            for sid in symptom_ids for k in SYMPTOMS[sid]["keywords"]
        )
    ]

    if not model and not slots["intent"]["safety"]:
        add("G1", "clarify_model", "high",
            "你的机型是哪一台？（品牌 + 型号）",
            "不同机型的首层结构、调平方式和热床材质差异很大，机型不明会让建议失焦。",
            action="ask_user")
    elif model and not model_notes:
        add("G1", "model_experience", "high",
            f"{model} 在 {material_text or '这种耗材'} 上出现「{symptom_label}」，最常见的三个原因是什么？",
            f"私域库里没有 {model} 的直接案例，只有通用经验。")
    elif model_notes:
        stale_notes = [h for h in model_notes if h.get("stale")]
        if len(stale_notes) == len(model_notes):
            add("G1", "stale_private_note", "high",
                f"{model} 的 {material or ''} 基线参数最近有没有更新？",
                f"私域库里关于 {model} 的笔记已过期（{model_notes[0].get('created_at','')}），不能直接当依据。")
        elif stale_notes:
            add("G1", "stale_private_note", "medium",
                f"{model} 的旧笔记（{stale_notes[0].get('created_at','')}）里的数值还成立吗？",
                "私域库里同时有新旧两条经验，旧的那条可能把你带偏。")

    if not symptom:
        add("G2", "clarify_symptom", "high",
            "你看到的具体现象是什么？（翘边 / 拉丝 / 堵头 / 多色换料 / 错层 / 表面粗糙 / 气味）",
            "现象描述决定检索方向；'打印不好' 无法被有效检索。",
            action="ask_user")
    elif not symptom_notes:
        add("G2", "symptom_mechanism", "high",
            f"「{symptom_label}」通常由哪些机制造成？按可能性怎么排序？",
            "私域库里没有这个现象的直接记录，需要外部案例补齐。")

    if any(SYMPTOMS[sid].get("parameter_sensitive") for sid in symptom_ids):
        target = "/".join(materials) if materials else (model or "这台机型")
        add("G3", "official_parameter", "high",
            f"{target} 的官方基线是什么：热床/喷嘴温度、首层速度、调平要求分别是什么？",
            "私域笔记只有个人经验值，缺厂家基线；没有基线就无法判断你现在的参数是偏高还是偏低。")

    wet_materials = [c for c, _a, h in MATERIALS if h and c in materials]
    if wet_materials and any(sid in {"stringing", "surface", "clog", "multi_color"} for sid in symptom_ids):
        wet_text = "/".join(wet_materials)
        add("G4", "material_condition", "medium",
            f"{wet_text} 是否需要烘干？推荐温度和时间是多少？",
            "拉丝/气泡/多色堵料常被误判为参数问题，实际是耗材含水率或材料兼容性。")

    if "multi_color" in symptom_ids:
        add("G5", "multi_color_setting", "high",
            f"{model or '这台机型'} 的 AMS / 多色换料，冲刷量、废料塔和换料温度怎么设？",
            "多色堵头常来自换料残留、冲刷不足或材料兼容，不是喷嘴本身；这条要单独查。")

    if slots["intent"]["freshness"]:
        add("G5", "freshness", "high",
            f"{model or '这台机型'} 最近是否有与「{symptom_label}」相关的固件、批次或召回信息？",
            "机型相关事实会过期；不限定时间窗，搜到的可能是三年前的旧版本经验。")

    if slots["intent"]["safety"]:
        add("G6", "official_safety", "high",
            f"{material or '光敏树脂'} 的通风、皮肤防护、废液处理，厂家要求是什么？",
            "安全结论不能只来自社区经验，必须回到厂家说明与合规要求。")
        env_note = ""
        if slots["environment"]:
            env_note = "（你的环境：" + "、".join(e["label"] for e in slots["environment"]) + "）"
        add("G7", "safety_mechanism", "high",
            f"气味和毒性在真实使用场景里的风险边界是什么？{env_note}",
            "需要区分“闻起来不舒服”和“有明确健康风险”，两者的处理方式不同。")
        add("G8", "waste", "medium",
            "清洗液、废树脂和后处理耗材应该怎么处理？",
            "废液是树脂用户最容易违规的一步，必须有可执行的合规做法。")

    hypothesis = _hypothesis(slots.get("parse_text") or slots["raw"])
    if hypothesis:
        add("G7", "rule_out", "medium",
            f"你怀疑「{hypothesis}」，这个方向成立吗？需要哪些证据才能排除它？",
            "先验证怀疑，避免直接换件或回滚固件。")

    if slots["tried"] and not hypothesis:
        add("G7", "rule_out", "medium",
            "已经试过 " + "、".join(t["label"] for t in slots["tried"]) + "，还需要排除哪些替代解释？",
            "避免在无效方向上继续加码；先确认哪些变量已经被排除。")

    if kb_hits and re.search(r"\d", note_text) and any(g["type"] == "official_parameter" for g in gaps):
        add("G8", "verify_conflict", "medium",
            f"私域笔记里的数值（{_numbers(note_text)}）与公开资料是否一致？",
            "私域笔记可能过期，也可能只适用于旧版本或特定平台。")

    if not slots["intent"]["safety"] and (
        slots["environment"]
        or any(sid in {"warping", "first_layer", "clog", "multi_color"} for sid in symptom_ids)
    ):
        add("G9", "environment", "low",
            "环境温度、空调直吹、湿度或地区气候，是否足以解释这个现象？",
            "这是成本最低、最容易被忽略的变量，先用一条检索排除。")

    gaps.sort(key=lambda g: (0 if g["action"] == "ask_user" else 1, PRIORITY_ORDER.get(g["priority"], 3)))
    gaps = gaps[:6]
    for index, gap in enumerate(gaps, start=1):
        gap["id"] = f"G{index}"
    return gaps


def _hypothesis(text: str) -> str:
    match = re.search(r"(是不是|要不要|会不会|怀疑)([^，。？?；;]{0,20})", text or "")
    if not match:
        return ""
    return (match.group(1) + match.group(2)).strip()[:26]


def _numbers(text: str) -> str:
    found = re.findall(r"\d{2,3}\s*(?:℃|度|%|小时|h|mm|毫米)", text)
    return "、".join(dict.fromkeys(found))[:80] or "若干数值"


def build_queries(slots: dict, gaps: list[dict]) -> list[dict]:
    gap_ids = {g["id"] for g in gaps}
    model = slots["model"]
    material = slots["material"]
    materials = slots.get("materials") or ([material] if material else [])
    material_text = "/".join(materials)
    symptom = slots["symptom"]
    symptom_label = _symptom_label(slots)
    site = MODEL_META.get(model, {}).get("site") if model else None
    queries: list[dict] = []

    def gids(*types: str) -> list[str]:
        return [g["id"] for g in gaps if g["type"] in types]

    def add(text: str, purpose: str, covers: list[str], mode: int = 2, cnt: int = 10,
            site_filter: str | None = None, freshness: str | None = None,
            industry: str | None = None, weight: float = 1.0,
            allow_empty: bool = False) -> None:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        params: dict = {"Mode": mode, "Cnt": cnt}
        if site_filter:
            params["Site"] = site_filter
        if freshness:
            params["Freshness"] = freshness
        if industry:
            params["Industry"] = industry
        real_covers = [c for c in covers if c in gap_ids]
        if not real_covers and not allow_empty:
            return
        for existing in queries:
            if existing["text"].lower() == text.lower():
                existing["covers"] = sorted(set(existing["covers"]) | set(real_covers))
                existing["weight"] = max(existing["weight"], weight)
                return
        queries.append({
            "id": f"Q{len(queries) + 1}",
            "text": text,
            "params": params,
            "purpose": purpose,
            "covers": real_covers,
            "weight": round(weight, 2),
        })

    # 1. Official baseline: the anchor that the private notes are compared to.
    official_covers = gids("official_parameter", "verify_conflict", "stale_private_note")
    if official_covers:
        symptom_hint = symptom["query_symptom"] if symptom else "首层 温度 参数"
        if material_text:
            text = f"{model or ''} {material_text} {symptom_hint} 官方 参数 热床 喷嘴 温度"
        elif symptom and symptom["id"] == "first_layer":
            text = f"{model or ''} 官方 {symptom_hint} 调平 Z偏移 指南"
        else:
            text = f"{model or ''} 官方 {symptom_hint} 参数 温度 指南"
        add(text, "拿厂家基线，校准私域里的经验值", official_covers,
            mode=2 if site else 0, site_filter=site, weight=1.3)

    # 2. Community cases: the operational order that manuals rarely give.
    symptom_covers = gids("symptom_mechanism", "model_experience")
    if symptom and symptom_covers:
        add(f"3D打印 {model or ''} {material_text or ''} {symptom['query_symptom']}",
            "找同机型/同材料的真实案例，补齐处理顺序", symptom_covers,
            mode=2, weight=1.0)

    # 2b. Multi-color: clog is often a filament-change residue problem.
    multi_covers = gids("multi_color_setting")
    if multi_covers:
        add(f"{model or ''} AMS Lite 多色 换料 堵头 冲刷 废料塔 设置",
            "多色换料的冲刷量、废料塔与材料兼容性单独排查", multi_covers,
            mode=2, site_filter=site, weight=1.25)

    # 3. Rule out the user's own hypothesis (firmware, nozzle, machine broken).
    rule_covers = gids("rule_out")
    if symptom and rule_covers:
        tried_text = " ".join(t["label"] for t in slots["tried"])
        if tried_text:
            text = f"3D打印 {model or ''} {material_text or ''} {symptom['query_symptom']} {tried_text} 无效 其他原因"
            purpose = "验证已经试过的方向为什么无效，避免继续加码"
        else:
            text = f"3D打印 {model or ''} {symptom['query_symptom']} 排除 其他 原因"
            purpose = "验证用户的怀疑，避免直接换件或回滚"
        add(text, purpose, rule_covers, mode=2, weight=0.95)

    # 4. Material condition: drying is often misread as a parameter problem.
    if gids("material_condition"):
        add(f"3D打印 {material_text} 受潮 烘干 温度 时间",
            "判断是不是耗材含水率问题", gids("material_condition"),
            mode=2, weight=1.0)
        if site and material_text:
            add(f"{model} {material_text} 烘干 温度 时间 官方",
                "到厂商站点确认该材料的烘干制度", gids("material_condition"),
                mode=2, site_filter=site, weight=1.15)

    # 5. Environment: cheapest variable to rule out.
    if gids("environment"):
        add(f"3D打印 {symptom_label} 环境 温度 空调 直吹",
            "用一条低成本检索排除环境变量", gids("environment"),
            mode=2, weight=0.7)

    # 6. Freshness: facts with a shelf life get an explicit time window.
    fresh_covers = gids("freshness")
    if fresh_covers:
        add(f"3D打印 {model or ''} 固件 更新 {symptom['query_symptom'] if symptom else ''} 问题",
            "限定最近半年，确认是否有已知固件/批次问题", fresh_covers,
            mode=2, freshness="m6", weight=1.2)
        if site:
            add(f"{model} 固件 更新 已知 问题 官方",
                "到厂商站点确认是否有公告或回滚说明", fresh_covers,
                mode=2, site_filter=site, freshness="m6", weight=1.15)

    # 7. Safety: official requirements, real-world risk, waste compliance.
    if gids("official_safety"):
        add(f"3D打印 {material_text or '光敏树脂'} 安全 使用 通风 手套 防护",
            "拿厂家安全要求，而不是社区口口相传", gids("official_safety"),
            mode=2, site_filter=site, weight=1.3)
    if gids("safety_mechanism"):
        add(f"3D打印 {material_text or '光敏树脂'} 气味 毒性 卧室 通风",
            "看真实使用场景里的风险边界", gids("safety_mechanism"),
            mode=2, weight=1.0)
    if gids("waste"):
        add(f"3D打印 {material_text or '光敏树脂'} 废液 清洗 处理 危险废物",
            "确认废液与后处理的合规做法", gids("waste"),
            mode=2, weight=0.8)

    # 8. Stale-note-only case: still need a public anchor.
    if "stale_private_note" in {g["type"] for g in gaps} and not official_covers:
        add(f"{model or ''} {material_text or ''} 官方 推荐 参数",
            "用公开资料校准过期笔记", gids("stale_private_note"),
            mode=2 if site else 0, site_filter=site, weight=1.1)

    # 9. Nothing identifiable: do not invent a plan, just hand over the raw ask.
    if not queries:
        add(slots["raw"], "没有识别出明确缺口，先把原问题交给搜索引擎",
            [], mode=2, weight=0.8, allow_empty=True)

    for index, query in enumerate(queries, start=1):
        query["id"] = f"Q{index}"
    return queries


def _strategy(gaps: list[dict]) -> str:
    types = {g["type"] for g in gaps}
    if "official_safety" in types:
        return "安全题不赌经验：先用厂家要求定边界，再看真实场景，最后确认废液合规；三条线互相印证。"
    if "multi_color_setting" in types:
        return "多色题先分清「喷嘴本身堵」还是「换料残留/冲刷不足」：先查 AMS 换料设置，再查材料干燥与兼容，最后才拆喷嘴。"
    if "freshness" in types:
        return "先用官方基线定锚，再用最近半年的时间窗验证固件/批次事实，最后用社区案例补操作顺序。"
    return "先补私域缺口，再拿官方基线，最后用社区案例交叉验证；私域笔记与公开资料冲突时，以官方和更新时间更近者为准。"


def compile_question(question: str, kb_hits: list[dict] | None = None) -> dict:
    slots = extract_slots(question)
    kb_hits = kb_hits or []
    gaps = analyze_gaps(slots, kb_hits)
    queries = build_queries(slots, gaps)

    model_value = slots["model"]
    if model_value and slots.get("brand") and slots["brand"] not in model_value:
        model_value = f"{model_value}（{slots['brand']}）"
    material_value = "/".join(slots.get("materials") or ([slots["material"]] if slots["material"] else [])) or None
    symptom_value = _symptom_label(slots) if slots.get("symptoms") else None

    chips = [
        {"key": "model", "label": "机型", "value": model_value, "state": "filled" if slots["model"] else "missing"},
        {"key": "material", "label": "材料", "value": material_value, "state": "filled" if slots["material"] else "missing"},
        {"key": "symptom", "label": "现象", "value": symptom_value,
         "state": "filled" if slots["symptom"] else "missing"},
        {"key": "tried", "label": "已尝试", "value": "、".join(t["label"] for t in slots["tried"]) or None,
         "state": "filled" if slots["tried"] else "missing"},
        {"key": "environment", "label": "环境", "value": "、".join(e["label"] for e in slots["environment"]) or None,
         "state": "filled" if slots["environment"] else "missing"},
    ]
    filled = sum(1 for chip in chips if chip["state"] == "filled")

    return {
        "slots": slots,
        "chips": chips,
        "gaps": gaps,
        "queries": queries,
        "strategy": _strategy(gaps),
        "rewritten_question": _rewrite(slots),
        "naive_query": question,
        "confidence": slots.get("confidence", "low"),
        "coverage": {"filled": filled, "total": len(chips)},
    }
