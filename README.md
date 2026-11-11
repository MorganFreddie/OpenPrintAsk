# 得师傅·外脑

> **v2 开发版**：界面 V2 + 词表外置 + 7 个真实病例 + 复现回执。v1 已冻结在 `../deshifu-wsa`；本版计划与分工见 [docs/v2-plan.md](docs/v2-plan.md)，输入方法见 [docs/input-guide.md](docs/input-guide.md)，征文底稿见 [docs/article-draft.md](docs/article-draft.md)。

> 把 3D 打印新手的「打不好」翻译成可检索的问题，再用元宝搜索 SearchPro 补私域知识缺口，最后给出带编号引用的下一步。

这是「得师傅」打印工艺向导的搜索增强 sidecar：它不替换原来的本地 RAG，而是在「私域笔记不够用」的那一刻，先判断缺什么，再决定搜什么。

- 赛事：CSDN 元宝搜索开发者征文大赛 · 模型智答与产品问答
- 形态：本地 Web 原型（Python 标准库 + 原生 HTML/CSS/JS，无构建步骤）
- 模式：`live`（真实 SearchPro）/ `replay`（离线回放，界面明确标记）/ `auto`（有凭证走 live）
- 原则：私域笔记不出机；公开证据带 S 编号和 RequestId；证据不足就追问，不硬编答案

---

## 1. 它解决什么问题

3D 打印新手的抱怨通常不是「参数查询」，而是三件事叠在一起：

1. **现象描述不准**：「模型打一半掉了」可能是层间粘附、Z 轴丢步、挤出不足。
2. **私域经验过期**：自己的旧笔记写着「PLA 热床 50–60℃」，但机器、平台、环境已经变了。
3. **公开资料互相打架**：官方给区间，社区帖子给单点，论坛说「换喷嘴」，新手不知道该信哪个。

直接把这句抱怨丢给搜索引擎，会得到一坨「看起来相关」的页面；直接丢给大模型，会得到一段「听起来合理」但没有出处的建议。

这个原型把动作拆成四步：

```text
一句抱怨
  → 槽位：机型 / 材料 / 现象 / 已尝试 / 环境 / 意图
  → 缺口：私域覆盖了什么、还缺什么、哪个缺口需要问用户
  → 任务书：每条 query 带 Mode / Site / Cnt / Freshness / Industry + purpose + covers
  → 证据：去重、排序、抽数值、找冲突、算覆盖率
  → 回答：结论 + 步骤 + S 编号 + 分歧 + 追问
```

关键不是「多搜几条」，而是**先知道自己不知道什么**。这就是「提出问题比解决问题更重要」在工程上的落点。

---

## 2. 快速开始

要求：Python 3.11+，SQLite 带 FTS5（标准库即可）。

```powershell
# 在仓库根目录（本文件所在目录）执行
Copy-Item .env.example .env
# 没有 key 也能跑：auto 会自动落到 replay
python server.py --mode replay --port 8766
```

打开 <http://127.0.0.1:8766/>。

也可以直接：

```powershell
.\run.ps1 -Mode replay -Open
```

### 接真实 SearchPro

在 `.env` 里二选一：

```dotenv
# 路径 A：服务 API KEY（推荐，简单）
# 控制台：元宝搜索 -> 概览 -> 服务 API KEY 方式 -> 创建 API KEY
WSA_API_KEY=sk-你的key

# 路径 B：腾讯云 TC3（SecretId + SecretKey，二者必须配对）
# 控制台：访问管理 -> API 密钥管理 -> 新建密钥
WSA_SECRET_ID=你的SecretId
WSA_SECRET_KEY=你的SecretKey
```

注意：`AKI...` 开头的是腾讯云 SecretId，不是 `sk-` 服务 API KEY；单独一个 SecretId 不能当 Bearer key。分不清时看 [docs/凭证配置.md](docs/凭证配置.md)。

然后：

```powershell
python server.py --mode live --port 8766
```

免费额度与申请入口以赛事页/腾讯云文档为准；不要把 key 写进文章、截图或仓库。

先用一条请求确认凭证与网络都通：

```powershell
python live_check.py
```

成功时会打印 `RequestId`、版本、延迟和前三条结果，并把完整响应写到 `runs/live_check.json`。这一步不经过回放层，是真正的 SearchPro 调用。

### 主要接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 模式、凭证、KB 条数、SearchPro 探活 |
| POST | `/api/compile` | 只编译问题：槽位 / 缺口 / 查询任务书 |
| POST | `/api/ask` | 全链路：编译 → 检索 → 证据 → 回答 |
| GET | `/api/receipts?model=&material=&symptom=` | 按机型/材料/现象取复现回执 |
| POST | `/api/receipts` | 记录某一步「有效 / 没解决 / 还没试」 |
| GET | `/api/runs/{id}` | 下载一次运行的完整 trace |

---

## 3. 目录

```text
deshifu-wsa/
├─ config.py            # 环境变量、路径、模式
├─ kb.py                # SQLite FTS5 私域笔记（按线程独立连接）
├─ planner.py           # 问题编译器：槽位 / 缺口 / 查询任务书
├─ lexicon.py           # 词表加载与热重载
├─ wsa.py               # SearchPro 客户端：Bearer + TC3 + replay + record
├─ fuse.py              # 证据融合：排序 / 数值断言 / 冲突 / 缺口覆盖
├─ compose.py           # 回答生成：按症状组装步骤与引用
├─ pipeline.py          # 全链路编排 + trace
├─ server.py            # 本地 HTTP 服务 + 静态页面
├─ bench.py             # 案例验证表
├─ live_check.py        # 一条真实 SearchPro 请求，验证凭证/网络/RequestId
├─ smoke.py             # 只跑编译器的冒烟测试
├─ check_demo.py        # 全案例全链路检查
├─ make_fixtures.py     # 生成合成回放语料（synthetic=true）
├─ data/
│  ├─ lexicon.json      # 品牌 / 机型 / 材料 / 现象 / 环境 / 地区 / 已尝试
│  ├─ kb_seed.json      # 20 条私域笔记（含过期笔记）
│  ├─ cases.json        # 7 个演示案例
│  └─ fixtures/demo.json# 12 条查询记录 / 16 张合成页面
├─ web/                 # 无框架前端（V2）
├─ runs/                # 每次运行的 trace JSON
└─ docs/                # 参赛方案 / 输入手册 / 征文底稿 / 截图清单
```

---

## 4. 七个演示案例

| 案例 | 用户表面问题 | 编译器看到的真问题 | 回答落点 |
|---|---|---|---|
| A1 mini / PLA / 翘边 | 「是不是机器坏了」 | 平台清洁 + 热床基线 + 环境气流；旧笔记 50–60℃ 已过期 | 先洗板，再升温，最后挡风 |
| P1S / PETG / 拉丝 | 「是不是要换喷嘴」 | 回抽已试错；含水率才是优先变量 | 先烘干（65℃ / 4–6h），再谈回抽 |
| K1 / 首层变薄 | 「是不是固件问题，要不要回滚」 | 强假设需要反向证据 + 时间窗口 | 先排除固件，再谈回滚 |
| 光敏树脂 / 卧室 | 「有毒吗，怎么防护」 | 安全类必须官方 + 合规，不能只靠社区 | 先搬出卧室，再谈参数 |
| A1 / PETG / 单色堵料 | 「打龟壳就堵」 | 已停打退料；室温 30℃；要分喷嘴/挤出机/热蠕变 | 先停打，再分堵在哪 |
| A1 / AMS Lite / 多色堵料 | 「换色就堵，单色不堵」 | 换料残留 + 冲刷不足；AMS 细节公开证据不足 | 先查换料残留，再通喷嘴 |
| A1 / PLA / 首层炒面 | 「底部不在热床还在打」 | 首层附着失效 + 没及时停打；平台清洁优先 | 先洗板，再升温，最后挡风 |

每个案例都会产出：

- 5 个左右的缺口（`G1..`），每个都有「问题 / 为什么问 / 谁来回答」
- 2–4 条查询（`Q1..`），每条都有参数、目的、覆盖的缺口
- 4 条左右证据（`S1..`），带来源层级、日期、相关度、新鲜度
- 回答步骤逐条挂 `S` 编号；有冲突时单独列「需要你知道的分歧」
- 证据不足时输出追问，而不是把「可能」写成「一定」

---

## 5. 验证

```powershell
python smoke.py        # 编译器冒烟：槽位 / 缺口 / 查询
python check_demo.py   # 全案例全链路，写 runs/demo_check.json
python bench.py --live # live 汇总表，写 runs/bench.json
```

`bench.py` 的输出是**一次 live 运行的原样汇总**，不是线上准确率：

| 案例 | 查询 | 证据 | 官方 | 数值断言 | 冲突 | 缺口覆盖 | 有引用步骤 | 置信 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A1 mini | 3 | 10 | 3 | 9 | 1 | 5/5 | 5/5 | high |
| P1S | 4 | 10 | 5 | 6 | 1 | 4/4 | 4/4 | high |
| K1 | 4 | 10 | 4 | 3 | 0 | 4/4 | 4/4 | high |
| 光敏树脂 | 3 | 10 | 0 | 0 | 0 | 3/3 | 4/4 | medium |

合计 14 次 SearchPro 调用、40 条证据、12 条官方来源、18 条数值断言、2 处冲突、17 个有引用步骤（2026-11-09，`version=lite`，`replayed=False`）。`lite` 不返回 `score`/`authority_level`，相关度用标题/正文词面覆盖兜底；来源层级按域名白名单判断。私域笔记是合成演示数据，公网页面是真实返回；4 个案例样本不足以代表总体准确率。

2026-11-11 又用三条真实病例跑了一次 live：

- 单色堵料：5 条查询 / 10 条证据 / 5 条官方 / `high`；
- 多色堵料：5 条查询 / 10 条证据 / 10 条官方 / 0 条社区 / 0 条通用 / `medium`；
- 首层炒面：走首层附着分支，`high`。

多色那条的 `uncertainties` 明确写了「AMS / 多色换料的冲刷量、废料塔、换料温度」没有足够公开证据。这是当前的真实边界，不是 bug。

---

## 6. 设计取舍

- **先缺口、后检索**：没有缺口的搜索是「碰运气」；缺口让每条 query 有验收标准。
- **私域旧笔记不静默平均**：旧笔记与公开资料冲突时，显式列出两边数值，回答里说明「旧笔记偏保守」。
- **官方过滤失败要降级**：`Site` 过滤可能把召回打到 0；失败时自动去掉 `Site` 重试，并在 trace 里标 `fallback=site_filter_removed`，不假装没发生。
- **不用 SearchPro 的 raw score 做唯一排序**：不同 Mode/Industry 下 score 量纲会漂；本项目用「相关度 + 来源层级 + 新鲜度 + 权威度」自有排序。
- **证据不足是合法结果**：`compose.py` 在无证据时不生成确定性结论；覆盖率里的 `insufficient` 会变成追问。
- **回放必须显式标记**：UI 顶部横幅 + 每条证据 `replayed=true` + trace 的 `request_id=replay-*`，避免把演示当线上。

---

## 7. 已知限制

- 槽位与数值断言是规则 + 正则，不是通用 NLU；换到牙科、法律等域需要重写词表。
- 只有 7 个演示案例；私域笔记是合成的，不能据此宣称线上召回率。
- `lite` 版本不返回 `score`/`authority_level`，相关度与权威度是本地兜底；换 `standard`/`flagship` 后应重新校准权重。
- `compose.py` 是模板化回答，不调用 LLM；接 LLM 时仍需保留 S 编号与「证据不足」分支。
- 安全类结论只做信息整理，不构成医疗/合规建议；涉及孕期、长期暴露要回到厂家 SDS 与医生。
- 单机单进程演示，没有鉴权、限流、多租户；不要直接暴露到公网。

---

## 8. 安全

- `.env` 已在 `.gitignore`；代码与截图不出现 key。
- 私域笔记只存在本地 SQLite；`/api/ask` 不回传 key。
- 运行 trace 会写 `runs/`，里面只有 query、参数、RequestId、页面摘要；发布前请检查是否含个人信息。
- 公开页面只保留 title / url / passage / date 等必要字段，不抓取登录态内容。

---

## 9. 赛事文档

- [`docs/参赛方案.md`](docs/参赛方案.md)：赛道选择、评分拆解、13 天执行表、风险与备选
- [`docs/input-guide.md`](docs/input-guide.md)：五槽位输入模板、真实病例、常见错误
- [`docs/开发手册.md`](docs/开发手册.md)：数据流、改词表/病例/回答分支、回执调试
- [`docs/任务卡.md`](docs/任务卡.md)：数据/测试/界面/逻辑/发布五层参与任务
- [`docs/article-draft.md`](docs/article-draft.md)：征文底稿（标题、结构、live 数字、限制）
- [`docs/CSDN征文.md`](docs/CSDN征文.md)：旧版可发布稿（数字需按 v2 更新）
- [`docs/发布步骤.md`](docs/发布步骤.md)：CSDN 发布、上传图、提交与 24h 运营清单
- [`docs/截图清单.md`](docs/截图清单.md)：每张 live 截图的用途、拍摄命令、检查项
