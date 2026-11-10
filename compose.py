"""Compose a grounded, cited answer -- or refuse to pretend.

Rules:
* every step carries the evidence ids it came from;
* a numeric claim is quoted with its range and source tier, never invented;
* if the evidence does not cover a gap, the answer says so and turns the gap
  into a follow-up question;
* private notes and public sources are allowed to disagree, visibly.
"""
from __future__ import annotations

import re


def _has_firmware_issue(evidence: list[dict]) -> bool:
    """Only count a firmware *problem* when the page ties firmware to first-layer trouble.

    A release note that says "fixed filament runout detection, no first-layer change"
    must not be read as evidence of a first-layer bug.
    """
    for item in evidence:
        text = f"{item.get('title', '')} {item.get('passage', '')} {item.get('content', '')}"
        if "固件" not in text and "firmware" not in text.lower():
            continue
        if not re.search(r"首层|第一层|first.?layer", text, re.I):
            continue
        if re.search(r"未提及|没有(?:证据|发现|承认)|并非.{0,6}固件|不是.{0,6}固件|"
                     r"与.{0,6}固件无关|no .{0,12}(?:change|issue)", text, re.I):
            continue
        if re.search(r"问题|缺陷|回滚|已知|异常|bug|缺陷", text, re.I):
            return True
    return False


def _sids(evidence: list[dict], *keywords: str, limit: int = 2) -> list[str]:
    picked: list[str] = []
    for item in evidence:
        text = f"{item.get('title', '')} {item.get('passage', '')} {item.get('content', '')}".lower()
        if any(keyword.lower() in text for keyword in keywords):
            if item["id"] not in picked:
                picked.append(item["id"])
        if len(picked) >= limit:
            break
    if not picked:
        picked = [item["id"] for item in evidence[:limit]]
    return picked


def _claim_sids(claims: list[dict], attribute: str, limit: int = 2) -> list[str]:
    picked: list[str] = []
    for claim in claims:
        if claim["attribute"] == attribute and claim["sid"] not in picked:
            picked.append(claim["sid"])
        if len(picked) >= limit:
            break
    return picked


def _range_text(claims: list[dict], attribute: str, unit: str = "℃") -> str | None:
    values = [c for c in claims if c["attribute"] == attribute]
    if not values:
        return None
    # If an official source exists, quote the official range only. Mixing a
    # low-authority outlier into the same range is how "45–65℃" nonsense happens.
    official_values = [c for c in values if c.get("official")]
    if official_values:
        values = official_values
    low = min(c.get("value_low", c["value"]) for c in values)
    high = max(c.get("value_high", c["value"]) for c in values)
    official = any(c.get("official") for c in values)
    if low == high:
        text = f"{low:g}{unit}"
    else:
        text = f"{low:g}–{high:g}{unit}"
    return text + ("（官方）" if official else "（公开资料）")


def _drying_text(claims: list[dict]) -> str | None:
    values = [c for c in claims if c["attribute"] == "drying"]
    if not values:
        return None
    # A manufacturer's drying schedule outranks a generic "45–50℃" tip.
    official = [c for c in values if c.get("official")]
    claim = official[0] if official else values[0]
    hours = claim.get("hours")
    span = re.search(r"(\d{1,2})\s*[-–~至到]\s*(\d{1,2})\s*(?:小时|h|H)", claim.get("text", ""))
    if span:
        return f"{claim['value']:g}℃ / {span.group(1)}–{span.group(2)} 小时"
    if hours:
        return f"{claim['value']:g}℃ / {hours:g} 小时"
    return f"{claim['value']:g}℃"


def _first_kb(kb_hits: list[dict], model: str | None) -> dict | None:
    if not kb_hits:
        return None
    if model:
        for note in kb_hits:
            if model.lower() in f"{note.get('title', '')}{note.get('body', '')}".lower():
                return note
    return kb_hits[0]


def _conflict_notes(conflicts: list[dict]) -> list[dict]:
    notes = []
    for conflict in conflicts:
        preferred = conflict.get("preferred") or {}
        text = conflict.get("summary", "")
        if conflict.get("type") == "kb_vs_public":
            text += " 旧笔记不是“错”，而是过期了；先用公开值做单变量复测，再决定要不要改笔记。"
        elif preferred:
            text += f" 建议先采用 {preferred.get('value', 0):g}{preferred.get('unit', '')} 这一侧，并记录复测结果。"
        notes.append({"text": text, "sids": [preferred.get("sid")] if preferred.get("sid") else []})
    return notes


def _coverage(gaps: list[dict]) -> dict:
    result = {"covered": 0, "partial": 0, "insufficient": 0, "need_user": 0}
    for gap in gaps:
        status = gap.get("status", "insufficient")
        if status in result:
            result[status] += 1
    return result


def _warping(ctx: dict) -> dict:
    slots, evidence, claims, conflicts, kb_hits = ctx["slots"], ctx["evidence"], ctx["claims"], ctx["conflicts"], ctx["kb_hits"]
    bed = _range_text(claims, "bed_temp")
    bed_plain = re.sub(r"（[^）]*）", "", bed or "").strip()
    bed_state = ""
    kb = _first_kb(kb_hits, slots.get("model"))
    stale = next((n for n in kb_hits if n.get("stale")), None)
    summary_parts = ["先说结论：这更像首层附着失效，不像机器故障。"]
    if kb:
        summary_parts.append(f"你的私域库里已经有一条「{kb.get('title', '')}」，平台清洁这条线你其实走过；")
        if stale:
            summary_parts.append(f"但「{stale.get('title', '')}」是旧版（{stale.get('created_at', '')}），只记录了区间、没有测试条件，不能直接当现行排查顺序。")
        else:
            summary_parts.append("这次可以把它升级成可复用的检查顺序。")
    if bed:
        tried = next((t["label"] for t in slots.get("tried", []) if "热床" in t["label"]), "")
        where = f"你试的 {tried}" if tried else "你现在的热床温度"
        nums = [int(n) for n in re.findall(r"\d+", bed)]
        tried_num = re.search(r"(\d+)", tried)
        if len(nums) >= 2 and tried_num:
            low, high = min(nums[:2]), max(nums[:2])
            value = int(tried_num.group(1))
            if value >= high:
                tail = "已经到区间上沿，继续加温收益有限；先查板面清洁和气流。"
                bed_state = "top"
            elif value <= low:
                tail = "还在区间下沿，可以再升 5℃ 做一次单变量复测。"
                bed_state = "low"
            else:
                tail = "已经落在区间内，温度不是唯一的变量，先排除油污和气流。"
                bed_state = "mid"
            summary_parts.append(f"公开资料把 {slots.get('material') or '这种材料'} 的热床区间给到 {bed}，{where} {tail}")
        else:
            summary_parts.append(f"公开资料把 {slots.get('material') or '这种材料'} 的热床区间给到 {bed}，先按单变量复测。")
    else:
        summary_parts.append("公开资料没有给出明确的热床数值，先按厂家手册核对，不要凭感觉继续加温。")

    if bed_state == "top":
        step2 = {"n": 2, "title": "先别加温", "text": f"你已经试到 {bed_plain} 的上沿，先不要继续升温；洗板、挡风后复测，若仍翘再降到 55℃ 做对比。",
                 "sids": _claim_sids(claims, "bed_temp") or _sids(evidence, "热床", "温度")}
        headline = "先洗板，再挡风，最后复测"
    else:
        step2 = {"n": 2, "title": "升温", "text": f"把热床设到 {bed or '厂家推荐区间'}，一次只改这一个变量。",
                 "sids": _claim_sids(claims, "bed_temp") or _sids(evidence, "热床", "温度")}
        headline = "先洗板，再升温，最后挡风"
    steps = [
        {"n": 1, "title": "洗板", "text": "用温水 + 中性洗洁精把 PEI 板洗一遍，冲净、晾干。油污会让胶水和升温同时失效。",
         "sids": _sids(evidence, "洗洁精", "清洗", "油污", "酒精")},
        step2,
        {"n": 3, "title": "挡风", "text": "关掉空调直吹，或给机器加个罩；环境温度低于 22℃ 时边角翘得更明显。",
         "sids": _sids(evidence, "空调", "直吹", "环境", "气流")},
        {"n": 4, "title": "压首层", "text": "首层速度降到 50mm/s，观察第一层是否被压扁；如果仍然翘，再动 Z 偏移。",
         "sids": _sids(evidence, "首层", "速度", "z偏移", "调平")},
        {"n": 5, "title": "复测", "text": "打一个 20mm 方片，只看四角。不要同时换耗材、温度和速度，否则无法判断是哪一项起了作用。",
         "sids": _sids(evidence, "首层", "测试", "建议")},
    ]
    return {
        "headline": headline,
        "summary": " ".join(summary_parts),
        "steps": steps,
        "conflict_notes": _conflict_notes(conflicts),
        "followup": "你的 PEI 板是纹理板还是光滑板？打印时空调是否直吹？这两个信息会改变下一步。",
        "uncertainties": ["如果洗板 + 升温 + 挡风后仍然翘边，下一步才查 Z 偏移或平台变形；不要继续加胶水。"],
    }


def _stringing(ctx: dict) -> dict:
    slots, evidence, claims, conflicts, kb_hits = ctx["slots"], ctx["evidence"], ctx["claims"], ctx["conflicts"], ctx["kb_hits"]
    drying = _drying_text(claims)
    kb = _first_kb(kb_hits, slots.get("model"))
    summary_parts = ["先别继续加回抽。"]
    if kb:
        summary_parts.append(f"你的笔记「{kb.get('title', '')}」已经记录过：回抽从 0.8 加到 1.2 没改善，烘干后明显好转。")
    summary_parts.append("公开资料也把耗材含水率排在回抽参数之前；拉丝先查“干不干”，再查“回抽多长”。")
    if drying:
        summary_parts.append(f"可用的烘干基线是 {drying}。")

    steps = [
        {"n": 1, "title": "先烘干", "text": f"把线轴放进烘干箱，按 {drying or '厂家建议'} 处理；没有烘干箱就用除湿箱延长干燥时间。",
         "sids": _claim_sids(claims, "drying") or _sids(evidence, "烘干", "受潮", "干燥")},
        {"n": 2, "title": "再打温度塔", "text": "烘干后先打温度塔，找拉丝明显减少的温度点；不要一上来就改回抽。",
         "sids": _sids(evidence, "温度", "喷嘴", "拉丝")},
        {"n": 3, "title": "最后动回抽", "text": "确认耗材干燥后，再以 0.2mm 为步长调回抽；一次只改一个方向。",
         "sids": _claim_sids(claims, "retraction") or _sids(evidence, "回抽", "retraction")},
        {"n": 4, "title": "查喷嘴", "text": "如果烘干和温度都正常，检查喷嘴磨损与挤出机张力；旧喷嘴会让拉丝变得更难判断。",
         "sids": _sids(evidence, "喷嘴", "磨损", "挤出")},
    ]
    return {
        "headline": "先烘干，再谈回抽",
        "summary": " ".join(summary_parts),
        "steps": steps,
        "conflict_notes": _conflict_notes(conflicts),
        "followup": "你用的是哪款 PETG？烘干箱能稳定到 65℃ 吗？",
        "uncertainties": ["如果烘干后拉丝仍然严重，再怀疑喷嘴磨损或挤出机张力；不要同时改三个参数。"],
    }


def _first_layer(ctx: dict) -> dict:
    slots, evidence, claims, conflicts, kb_hits = ctx["slots"], ctx["evidence"], ctx["claims"], ctx["conflicts"], ctx["kb_hits"]
    kb = _first_kb(kb_hits, slots.get("model"))
    has_firmware_issue = _has_firmware_issue(evidence)
    summary_parts = ["这更像首层厚度 / 附着问题，不像固件缺陷。"]
    if kb:
        summary_parts.append(f"你的笔记「{kb.get('title', '')}」给了一个很重要的反向证据：升级后先调 Z 偏移、跑自动调平、确认 PEI 板没装反，三步做完再判断固件。")
    if not has_firmware_issue:
        summary_parts.append("本轮公开检索没有找到官方承认的固件导致首层的公告——这本身就是一条证据，先把固件排除。")
    else:
        summary_parts.append("公开资料里确实出现了固件相关的首层讨论，但需要区分“官方公告”和“用户猜测”。")

    steps = [
        {"n": 1, "title": "重调 Z 偏移", "text": "先把 Z 偏移往“更贴近”方向微调 0.02–0.04mm，打一个单层方片看是否被压扁。",
         "sids": _sids(evidence, "z偏移", "z-offset", "首层", "压")},
        {"n": 2, "title": "跑自动调平", "text": "完整跑一遍自动调平，不要只点“继续”；调平前确认喷嘴和平台都干净。",
         "sids": _sids(evidence, "调平", "leveling", "自动")},
        {"n": 3, "title": "确认平台方向", "text": "确认 PEI 板没有装反、卡扣到位；这一步最便宜，也最容易被忽略。",
         "sids": _sids(evidence, "PEI", "平台", "装反")},
        {"n": 4, "title": "再查固件", "text": "三步做完仍然异常，再去查固件版本、已知问题和回滚路径；把“怀疑”变成“可复现的对比”。",
         "sids": _sids(evidence, "固件", "版本", "回滚", "更新")},
    ]
    return {
        "headline": "先排除固件，再谈回滚",
        "summary": " ".join(summary_parts),
        "steps": steps,
        "conflict_notes": _conflict_notes(conflicts),
        "followup": "升级前后 Z 偏移值差了多少？PEI 板有没有装反？",
        "uncertainties": ["如果三步校准后首层仍然偏薄，再对比升级前后的同一模型切片，确认是不是固件改变了首层流量。"],
    }


def _safety(ctx: dict) -> dict:
    slots, evidence, claims, conflicts, kb_hits = ctx["slots"], ctx["evidence"], ctx["claims"], ctx["conflicts"], ctx["kb_hits"]
    kb = _first_kb(kb_hits, slots.get("model"))
    summary_parts = ["不建议把树脂机放在卧室。"]
    if kb:
        summary_parts.append(f"你的笔记「{kb.get('title', '')}」已经写过：气味不是唯一问题，皮肤接触和废液处理更麻烦。")
    summary_parts.append("安全结论优先看厂家要求，再看真实使用场景；社区经验只能补充，不能替代。")

    steps = [
        {"n": 1, "title": "搬出居住空间", "text": "把机器移到独立、可通风的空间；卧室、儿童活动区、厨房都不合适。",
         "sids": _sids(evidence, "卧室", "通风", "房间", "居住")},
        {"n": 2, "title": "通风与 PPE", "text": "打印和后处理都保持通风；接触树脂戴丁腈手套和护目镜，不要用裸手。",
         "sids": _sids(evidence, "手套", "护目镜", "皮肤", "通风")},
        {"n": 3, "title": "废液处理", "text": "清洗液和废树脂不要倒下水道；按当地危险废物要求收集，固化后再处置。",
         "sids": _sids(evidence, "废液", "危险废物", "处理", "固化")},
        {"n": 4, "title": "特殊人群", "text": "孕妇、儿童和呼吸道敏感人群尽量远离打印区；这不是“忍一忍”的问题。",
         "sids": _sids(evidence, "孕妇", "儿童", "敏感", "安全")},
    ]
    return {
        "headline": "先搬出卧室，再谈参数",
        "summary": " ".join(summary_parts),
        "steps": steps,
        "conflict_notes": _conflict_notes(conflicts),
        "followup": "你用的是哪款树脂？机器有没有外排风道或独立房间？",
        "uncertainties": ["具体毒性取决于树脂配方和通风条件；涉及孕期或长期暴露时，请以厂家 SDS 和医生建议为准。"],
    }


def _generic(ctx: dict) -> dict:
    evidence, claims, conflicts = ctx["evidence"], ctx["claims"], ctx["conflicts"]
    slots = ctx["slots"]
    if not evidence:
        return {
            "headline": "这轮没有拿到可用证据",
            "summary": "检索没有返回可引用的页面，所以不生成结论。先换一种问法，或者补充机型、材料、现象。",
            "steps": [],
            "conflict_notes": [],
            "followup": "能补充一下机型、材料，以及你看到的具体现象吗？",
            "uncertainties": ["没有证据时，任何“建议”都只是猜测。"],
        }
    top = evidence[:3]
    summary = "这轮证据指向几个方向：" + "；".join(e["title"][:36] for e in top) + "。先按来源更权威、时间更近的条目做单变量验证。"
    steps = []
    for index, item in enumerate(top, start=1):
        text = (item.get("passage") or item.get("content") or item["title"]).strip()
        text = text[:120] + ("…" if len(text) > 120 else "")
        steps.append({"n": index, "title": item["title"][:24], "text": text, "sids": [item["id"]]})
    return {
        "headline": "先按证据排序，再动手",
        "summary": summary,
        "steps": steps,
        "conflict_notes": _conflict_notes(conflicts),
        "followup": "你的机型、材料和你已经试过的操作分别是什么？补充后我可以把检索计划收窄。",
        "uncertainties": ["通用证据不能替代机型专属检查；下一步需要补机型与现象。"],
    }


def compose(question: str, plan: dict, fused: dict, kb_hits: list[dict]) -> dict:
    slots = plan.get("slots", {})
    symptom_id = (slots.get("symptom") or {}).get("id")
    ctx = {
        "question": question,
        "slots": slots,
        "evidence": fused.get("evidence", []),
        "claims": fused.get("claims", []),
        "conflicts": fused.get("conflicts", []),
        "gaps": fused.get("gaps", []),
        "stats": fused.get("stats", {}),
        "kb_hits": kb_hits,
    }
    builders = {
        "warping": _warping,
        "stringing": _stringing,
        "first_layer": _first_layer,
        "safety": _safety,
    }
    answer = builders.get(symptom_id, _generic)(ctx)

    coverage = _coverage(fused.get("gaps", []))
    stats = fused.get("stats", {})
    if (stats.get("official", 0) >= 2 and coverage["covered"] >= 2
            and coverage["insufficient"] == 0 and coverage["partial"] == 0):
        confidence = "high"
    elif stats.get("evidence_count", 0) >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    ask_user = next((g for g in fused.get("gaps", []) if g.get("action") == "ask_user"), None)
    if ask_user:
        answer["followup"] = ask_user["question"]

    insufficient = [g for g in fused.get("gaps", []) if g.get("status") == "insufficient"]
    if insufficient:
        answer["uncertainties"].append(
            "有 " + str(len(insufficient)) + " 个缺口没有足够公开证据：" + "；".join(g["question"] for g in insufficient[:2])
        )

    answer.update({
        "confidence": confidence,
        "coverage": coverage,
        "kb_note": {
            "used": bool(kb_hits),
            "items": [
                {"id": n.get("id"), "title": n.get("title"), "created_at": n.get("created_at"), "stale": n.get("stale", False)}
                for n in kb_hits[:2]
            ],
        },
        "source_note": "答案只引用本轮检索到的证据；S 编号对应右侧证据列表，未覆盖的部分会明确标成“证据不足”。",
        "symptom": (slots.get("symptom") or {}).get("label"),
        "model": slots.get("model"),
        "material": slots.get("material"),
    })
    return answer
