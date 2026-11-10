"""Build the offline replay fixture from the four demo cases.

The fixture is deliberately synthetic: it keeps the *shape* of a SearchPro
response (Pages is a list of JSON strings) while pinning the pages so that the
same run can be replayed on a machine without a key. Live mode never reads it.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from config import FIXTURE_DIR, ensure_dirs
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

PAGES: dict[str, dict] = {}


def page(key: str, title: str, date: str, url: str, site: str,
         passage: str, content: str, score: float, authority: int,
         tags: list[str]) -> None:
    PAGES[key] = {
        "id": key,
        "title": title,
        "date": date,
        "url": url,
        "site": site,
        "passage": passage,
        "content": content,
        "score": score,
        "authority_level": authority,
        "tags": tags,
        "synthetic": True,
    }


page(
    "a1_official",
    "A1 mini 热床温度与首层附着",
    "2025-08-12",
    "https://wiki.bambulab.com/en/a1-mini/manual/bed-temperature",
    "wiki.bambulab.com",
    "PLA 的热床温度建议 60–65℃，首层速度 50 mm/s。PEI 打印板每完成 10 次打印，"
    "用中性洗洁精和温水清洗，冲净后晾干；不要用手直接触摸板面。",
    "PLA 的热床温度建议 60–65℃，首层速度 50 mm/s。PEI 打印板每完成 10 次打印，"
    "用中性洗洁精和温水清洗，冲净后晾干；不要用手直接触摸板面。"
    "如果首层仍然翘边，先确认打印板卡扣到位，再检查环境气流。"
    "这类翘边通常不是机器故障，先按清洁、温度、气流三步排查。"
    "官方不建议把胶水作为长期方案，残留胶水会污染 PEI 表面。",
    0.94, 5, ["A1 mini", "PLA", "热床", "首层", "PEI", "官方"],
)
page(
    "a1_community",
    "A1 mini 首层翘边，先别换机器：我踩过的 4 个坑",
    "2025-10-20",
    "https://www.reddit.com/r/BambuLab/comments/1a1mini_warping/",
    "reddit.com",
    "热床 60℃ 并不总能救翘边。把 PEI 板用洗洁精洗干净、预热 5 分钟、关掉空调直吹，"
    "我的 A1 mini 首层附着明显变好；胶水反而会污染板面。这不是机器坏了，先排除板面油污和气流问题。",
    "我前后试了升温、加胶水、换耗材，最后发现是板面油污和空调直吹叠加。"
    "洗板后第一层纹路均匀，四角不再翘；胶水残留还会让下一锅更粘不住。",
    0.82, 3, ["A1 mini", "翘边", "PEI", "空调", "环境"],
)
page(
    "a1_env",
    "空调直吹导致 3D 打印翘边的实测",
    "2025-07-03",
    "https://www.printables.com/model/xxxx-draft-test",
    "printables.com",
    "环境温度每下降 5℃，PLA 边缘收缩应力明显增加；把打印机从空调出风口移开，"
    "翘边概率下降。",
    "我在 24℃ 房间和 19℃ 空调房各打了 6 个 20mm 方片，空调房四角翘起 4 个。"
    "给机器加亚克力罩后，翘边降到 1 个。环境变量比很多人想的更重要。",
    0.70, 2, ["翘边", "环境", "空调", "PLA"],
)
page(
    "a1_conflict",
    "PLA 热床 45℃ 也能打印？低温省电方案",
    "2024-02-11",
    "https://blog.example-3d.com/pla-low-temp-bed",
    "blog.example-3d.com",
    "把 PLA 热床降到 45℃，配合固体胶，首层也能粘住，还能减少耗材底部变形。",
    "低温打印的代价是首层附着窗口变窄。我的测试里 45℃ 需要更慢的首层速度和更多胶水，"
    "并不适合所有 PEI 板。",
    0.55, 1, ["PLA", "热床", "低温"],
)
page(
    "p1s_official",
    "P1S PETG 打印参数",
    "2025-06-18",
    "https://wiki.bambulab.com/en/p1/manual/filament-parameters",
    "wiki.bambulab.com",
    "PETG 喷嘴温度 250–270℃，热床 70–80℃，回抽 0.8–1.2 mm。"
    "打印前建议 65℃ 烘干 4–6 小时，受潮的 PETG 会明显拉丝。"
    "拉丝通常不是喷嘴问题，先把耗材烘干，再考虑回抽和温度。",
    "PETG 喷嘴温度 250–270℃，热床 70–80℃，回抽 0.8–1.2 mm。"
    "打印前建议 65℃ 烘干 4–6 小时；受潮的 PETG 会明显拉丝、产生气泡。"
    "如果更换喷嘴，需要重新做温度塔和流量校准。",
    0.94, 5, ["P1S", "PETG", "喷嘴", "热床", "回抽", "烘干"],
)
page(
    "p1s_community",
    "PETG 拉丝排查：烘干比回抽更重要",
    "2025-09-05",
    "https://www.reddit.com/r/3Dprinting/comments/petg_stringing_dry/",
    "reddit.com",
    "回抽从 0.8 加到 1.2 仍拉丝，先把线轴 65℃ 烘干 4 小时；再把喷嘴降 5–10℃、"
    "速度提到 80 mm/s，拉丝会明显减少。",
    "我试过回抽 0.8、1.2、1.6，只有烘干后拉丝才明显下降。"
    "烘干箱用 65℃ 4 小时，拿出来立刻打；南方梅雨季建议每次打前都烘。",
    0.80, 3, ["PETG", "拉丝", "烘干", "回抽"],
)
page(
    "p1s_nozzle",
    "什么时候该换喷嘴，而不是继续调回抽",
    "2025-04-12",
    "https://www.all3dp.com/2/3d-printer-nozzle-wear/",
    "all3dp.com",
    "喷嘴磨损会让挤出方向偏移、拉丝变粗；检查喷嘴尖端是否变圆、挤出线条是否偏斜。"
    "仅凭拉丝不建议直接换喷嘴：这多半不是喷嘴本身的问题，先把耗材烘干。",
    "喷嘴磨损是渐进过程，典型信号是挤出线条变粗、尺寸偏大、拉丝方向不固定。"
    "如果烘干和温度塔都做完仍然拉丝，再拆喷嘴检查。",
    0.72, 3, ["喷嘴", "回抽", "拉丝", "磨损"],
)
page(
    "p1s_conflict",
    "PETG 热床 60℃ 就够，70℃ 容易粘太牢",
    "2024-08-22",
    "https://blog.example-3d.com/petg-bed-60",
    "blog.example-3d.com",
    "PETG 热床 60℃ 即可，70℃ 容易粘太牢，拆件时可能撕裂 PEI 板。",
    "这条经验来自旧款 PEI 板。新板涂层不同，60℃ 可能粘不住；"
    "建议先按厂家区间，再用单变量测试调整。",
    0.60, 1, ["PETG", "热床"],
)
page(
    "k1_official",
    "K1 首层调平与 Z 偏移指南",
    "2025-07-21",
    "https://www.creality.com/blog/k1-first-layer-guide",
    "creality.com",
    "升级固件后请重新执行自动调平。首层偏薄时，把 Z 偏移向更贴近方向微调 0.02–0.05 mm；"
    "不要直接回滚固件，先排除平台和调平问题。",
    "升级固件后请重新执行自动调平。首层偏薄时，把 Z 偏移向更贴近方向微调 0.02–0.05 mm；"
    "同时确认 PEI 板没有装反、卡扣到位。不要直接回滚固件，先排除平台和调平问题。",
    0.93, 5, ["K1", "首层", "Z偏移", "调平", "固件"],
)
page(
    "k1_release",
    "K1 固件 3.2.5 发布说明",
    "2025-09-15",
    "https://www.creality.com/download/k1-firmware-3-2-5",
    "creality.com",
    "本次更新修复断料检测误报和 Wi-Fi 重连问题，优化运动控制噪声；"
    "发布说明未提及首层厚度变化。",
    "本次更新修复断料检测误报和 Wi-Fi 重连问题，优化运动控制噪声。"
    "发布说明未提及首层厚度变化，也没有要求用户重新调平。",
    0.90, 5, ["K1", "固件", "发布说明", "首层"],
)
page(
    "k1_community",
    "K1 3.2.x 首层变薄，回滚有用吗？",
    "2025-10-02",
    "https://www.reddit.com/r/Creality/comments/k1_first_layer_firmware/",
    "reddit.com",
    "升级 3.2.1 后首层明显变薄，重新调平并把 Z 偏移调低 0.05 后恢复；"
    "回滚到 3.1.8 也能缓解，但官方说不是固件问题。",
    "我记录了升级前后同一模型的切片：首层流量没变，Z 偏移需要重新校准。"
    "重新调平后恢复正常，所以更像升级后平台参数丢失，而不是固件缺陷。",
    0.84, 3, ["K1", "固件", "首层", "Z偏移", "回滚"],
)
page(
    "k1_conflict",
    "K1 固件 3.2 首层缺陷汇总",
    "2025-10-10",
    "https://www.reddit.com/r/Creality/comments/k1_firmware_32_megathread/",
    "reddit.com",
    "大量用户反馈 3.2 固件首层偏薄，建议统一回滚到 3.1.8；"
    "也有人认为是升级后没有重新调平。",
    "这个汇总帖把“升级后首层变薄”的帖子集中在一起，但没有控制变量。"
    "回滚有效的案例，很多也同时重新调平了。",
    0.66, 2, ["K1", "固件", "首层", "回滚"],
)
page(
    "r_official",
    "光敏树脂安全使用说明",
    "2025-05-10",
    "https://www.elegoo.com/pages/resin-safety",
    "elegoo.com",
    "请在通风良好处使用光敏树脂，佩戴丁腈手套和护目镜；皮肤接触后立即用肥皂水清洗。"
    "废液不可倒入下水道，应交由危险废物回收机构处理。",
    "请在通风良好处使用光敏树脂，佩戴丁腈手套和护目镜；皮肤接触后立即用肥皂水清洗。"
    "废液不可倒入下水道，应交由危险废物回收机构处理。"
    "孕妇、儿童和呼吸道敏感人群应远离打印区。",
    0.95, 5, ["光敏树脂", "安全", "通风", "手套", "废液"],
)
page(
    "r_gov",
    "光敏树脂职业健康风险提示",
    "2024-11-20",
    "https://www.gov.cn/health/resin-risk",
    "www.gov.cn",
    "光敏树脂含丙烯酸酯单体，可能引起皮肤过敏和呼吸道刺激；"
    "不建议在卧室等居住空间放置，打印区应与生活区分开并保持机械通风。",
    "光敏树脂含丙烯酸酯单体，可能引起皮肤过敏和呼吸道刺激。"
    "不建议在卧室等居住空间放置；打印区应与生活区分开，并保持机械通风。"
    "出现持续咳嗽或皮疹时应停止接触并就医。",
    0.93, 5, ["光敏树脂", "毒性", "卧室", "通风", "健康"],
)
page(
    "r_community",
    "树脂打印机放卧室，我是怎么改的",
    "2025-08-08",
    "https://www.reddit.com/r/resinprinting/comments/resin_bedroom/",
    "reddit.com",
    "味道主要来自树脂挥发和酒精清洗；把机器移到阳台、加排风扇、废液晒太阳固化后丢弃，"
    "室内味道明显下降。",
    "我先测了 VOC，打印时峰值很高；把机器移到阳台并加排风扇后，室内读数明显下降。"
    "废液不再倒下水道，而是晒太阳固化后按有害垃圾处理。",
    0.70, 2, ["树脂", "卧室", "通风", "废液"],
)
page(
    "r_waste",
    "光敏树脂废液处理：别倒下水道",
    "2025-03-14",
    "https://www.gov.cn/health/resin-waste",
    "www.gov.cn",
    "清洗废液属于危险废物，应密闭收集并交给有资质单位；"
    "少量废液可紫外线固化后按当地规定处理，不要倒入下水道或生活垃圾。",
    "清洗废液属于危险废物，应密闭收集并交给有资质单位。"
    "少量废液可紫外线固化后按当地规定处理，不要倒入下水道或混入生活垃圾。",
    0.90, 5, ["树脂", "废液", "危险废物", "处理", "合规"],
)

# Per case, per query index: which pages the replay should return.
ENTRY_PAGES = {
    0: [["a1_official", "a1_community"], ["a1_community", "a1_conflict"], ["a1_env", "a1_community"]],
    1: [["p1s_official", "p1s_conflict"], ["p1s_nozzle", "p1s_community", "p1s_official"]],
    2: [["k1_official", "k1_release"], ["k1_community", "k1_official"],
        ["k1_community", "k1_conflict"], ["k1_release", "k1_official"]],
    3: [["r_official", "r_gov"], ["r_gov", "r_community"], ["r_waste", "r_gov", "r_community"]],
}


def main() -> None:
    ensure_dirs()
    kb = KnowledgeBase().init()
    entries = []
    for case_index, question in enumerate(CASES):
        hits = kb.search(question, 4)
        plan = compile_question(question, hits)
        queries = plan["queries"]
        mapping = ENTRY_PAGES[case_index]
        if len(queries) != len(mapping):
            print(f"case {case_index}: {len(queries)} queries != {len(mapping)} mappings")
            for q in queries:
                print("  ", q["id"], q["text"])
            raise SystemExit(1)
        for query, keys in zip(queries, mapping):
            entries.append({
                "query": query["text"],
                "params": query["params"],
                "covers": query["covers"],
                "pages": [PAGES[key] for key in keys],
            })
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Synthetic replay fixture for the four demo cases. Live mode never reads this.",
        "entries": entries,
        "pages": list(PAGES.values()),
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / "demo.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path} ({len(entries)} entries, {len(PAGES)} pages)")


if __name__ == "__main__":
    main()
