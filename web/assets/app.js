/* 得师傅·外脑 — no framework, no build step. */
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const STATUS = {
  covered: ["已覆盖", "status-covered"],
  partial: ["部分覆盖", "status-partial"],
  insufficient: ["证据不足", "status-insufficient"],
  need_user: ["需要你补充", "status-need_user"],
  pending: ["待检索", "status-pending"],
};

const CONFIDENCE = {
  high: ["高置信", "conf-high"],
  medium: ["中等置信", "conf-medium"],
  low: ["低置信", "conf-low"],
};

const MODE_TEXT = { 0: "公网", 1: "权威垂类", 2: "混合" };

const state = {
  data: null,
  cases: [],
  loading: false,
  timer: null,
  activeTab: "answer",
};

/* ------------------------------------------------------------------ DOM */
function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else {
      node.setAttribute(key, value);
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function text(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function safeUrl(url) {
  return /^https?:\/\//i.test(url || "") ? url : "#";
}

function fmtMs(ms) {
  if (ms === null || ms === undefined) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`;
}

function pct(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function paramsRow(params) {
  const wrap = h("div", { class: "params" });
  for (const [key, value] of Object.entries(params || {})) {
    const title = key === "Mode" ? `Mode ${value} · ${MODE_TEXT[value] || ""}` : `${key}=${value}`;
    wrap.append(h("span", { class: "param", title }, h("b", null, key), " ", String(value)));
  }
  return wrap;
}

/* --------------------------------------------------------------- health */
async function loadHealth() {
  const badge = $("#modeBadge");
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const info = await response.json();
    const mode = info.mode || "auto";
    const kind = info.credential_kind || "none";
    badge.classList.remove("is-pending", "is-live", "is-replay", "is-error");
    if (mode === "live") {
      badge.classList.add("is-live");
      badge.textContent = "实时 · SearchPro";
    } else if (mode === "replay") {
      badge.classList.add("is-replay");
      badge.textContent = "回放 · 已录制";
      showReplay("当前服务运行在回放模式；所有结果来自已录制的 SearchPro 响应，不产生实时调用。");
    } else {
      badge.classList.add("is-live");
      badge.textContent = kind === "none" ? "自动 · 无凭证" : "自动 · SearchPro";
    }
    badge.title = `mode=${mode}, credential=${kind}, fixtures=${info.fixtures ?? "?"}, notes=${info.kb_notes ?? "?"}`;
  } catch (error) {
    badge.classList.remove("is-pending", "is-replay");
    badge.classList.add("is-error");
    badge.textContent = "服务未连接";
    badge.title = String(error);
  }
}

function showReplay(message) {
  const banner = $("#replayBanner");
  const span = banner.querySelector("span:last-child");
  if (span) span.textContent = message;
  banner.classList.remove("hidden");
}

/* ---------------------------------------------------------------- cases */
async function loadCases() {
  let cases = [];
  try {
    const response = await fetch("/api/cases", { cache: "no-store" });
    if (response.ok) cases = (await response.json()).cases || [];
  } catch (_) {
    /* fall through to defaults */
  }
  if (!Array.isArray(cases) || cases.length === 0) {
    cases = [
      { id: "a1-warping", tag: "A1 mini", title: "PLA 首层翘边，60℃ + 胶水也没用",
        question: "A1 mini 打 PLA，首层老翘边，热床 60℃ 还加了胶水也没用，是不是机器坏了？" },
      { id: "p1s-stringing", tag: "P1S", title: "PETG 拉丝，回抽 0.8→1.2 仍无效",
        question: "P1S 打 PETG 拉丝特别严重，回抽从 0.8 调到 1.2 了还是不行，是不是要换喷嘴？" },
      { id: "k1-firmware", tag: "K1", title: "升级固件后首层变薄，要不要回滚",
        question: "K1 升级最新固件以后首层压得很薄，是不是固件有问题？要不要回滚？" },
      { id: "resin-safety", tag: "光敏树脂", title: "树脂机放卧室，气味与防护边界",
        question: "光敏树脂打印机放在卧室里，味道很大，对人有毒吗？需要怎么防护？" },
    ];
  }
  state.cases = cases;
  const list = $("#caseList");
  clear(list);
  for (const item of cases) {
    list.append(h("button", {
      class: "case-btn", type: "button", title: "点击填入并直接运行",
      onclick: () => {
        $("#question").value = item.question;
        updateCount();
        ask();
      },
    }, h("span", { class: "case-tag" }, item.tag || "案例"), h("span", { class: "case-title" }, item.title || item.question)));
  }
}

/* --------------------------------------------------------------- input */
function updateCount() {
  const value = $("#question").value;
  $("#charCount").textContent = `${value.length} / 1200`;
}

function setLoading(active) {
  state.loading = active;
  const button = $("#askBtn");
  button.disabled = active;
  button.querySelector(".btn-label").textContent = active ? "正在检索…" : "编译并检索";
  button.querySelector(".spinner").classList.toggle("hidden", !active);
}

function startStageAnimation() {
  const steps = $$(".load-step");
  steps.forEach((step) => step.classList.remove("is-active", "is-done"));
  let index = 0;
  if (state.timer) clearInterval(state.timer);
  steps[0].classList.add("is-active");
  $("#loadingText").textContent = "正在编译问题…";
  state.timer = setInterval(() => {
    if (index < steps.length) {
      steps[index].classList.remove("is-active");
      steps[index].classList.add("is-done");
      index += 1;
    }
    if (index < steps.length) {
      steps[index].classList.add("is-active");
      $("#loadingText").textContent = steps[index].textContent;
    }
  }, 480);
}

function stopStageAnimation() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

/* ----------------------------------------------------------------- ask */
async function ask() {
  if (state.loading) return;
  const question = $("#question").value.trim();
  if (!question) {
    $("#question").focus();
    return;
  }
  setLoading(true);
  $("#emptyState").classList.add("hidden");
  $("#answerPane").classList.add("hidden");
  $("#evidencePane").classList.add("hidden");
  $("#planPane").classList.add("hidden");
  $("#tracePane").classList.add("hidden");
  $("#loadingState").classList.remove("hidden");
  startStageAnimation();

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
    state.data = payload;
    $("#loadingState").classList.add("hidden");
    renderAll(payload);
    switchTab(initialTab(), true);
    if (payload.replayed) {
      showReplay("本次结果为已录制的元宝 SearchPro 响应，未产生实时调用；界面仍走完整链路。");
    }
  } catch (error) {
    $("#loadingState").classList.add("hidden");
    renderError(error.message || String(error));
    switchTab("answer");
  } finally {
    stopStageAnimation();
    setLoading(false);
  }
}

function renderError(message) {
  const pane = $("#answerPane");
  clear(pane);
  pane.append(h("div", { class: "error-card" },
    h("strong", null, "这次没有跑通"),
    h("p", null, message),
    h("p", { class: "muted" }, "检查服务日志；如果是实时模式，确认 WSA_API_KEY 或腾讯云 SecretId/SecretKey 已配置。"),
  ));
  pane.classList.remove("hidden");
}

/* ---------------------------------------------------------------- render */
function renderAll(payload) {
  renderCompiler(payload);
  renderAnswer(payload);
  renderEvidence(payload);
  renderPlan(payload);
  renderTrace(payload);
  $("#evidenceCount").textContent = String((payload.evidence || []).length);
  $("#queryCount").textContent = String((payload.plan || {}).queries?.length || 0);
  const badge = $("#modeBadge");
  if (payload.mode === "live") {
    badge.classList.remove("is-pending", "is-replay");
    badge.classList.add("is-live");
    badge.textContent = "实时 · SearchPro";
  } else if (payload.mode === "replay") {
    badge.classList.remove("is-pending", "is-live");
    badge.classList.add("is-replay");
    badge.textContent = "回放 · 已录制";
  }
}

function renderCompiler(payload) {
  const plan = payload.plan || {};
  const chips = plan.chips || [];
  const gaps = plan.gaps || [];
  const queries = plan.queries || [];
  const compiler = $("#compiler");
  compiler.classList.remove("hidden");
  $("#gapSummary").textContent = `${gaps.length} 个缺口 · ${queries.length} 条查询`;

  const slots = $("#slots");
  clear(slots);
  for (const chip of chips) {
    const filled = chip.state === "filled" && chip.value;
    slots.append(h("div", { class: `slot ${filled ? "is-filled" : "is-missing"}` },
      h("span", { class: "slot-label" }, chip.label),
      h("span", { class: "slot-value" }, filled ? chip.value : "未识别"),
    ));
  }
  if (chips.length === 0) {
    slots.append(h("div", { class: "slot is-missing" }, h("span", { class: "slot-value" }, "没有抽出结构化槽位")));
  }

  const gapList = $("#gaps");
  clear(gapList);
  for (const gap of gaps) {
    const [label, cls] = STATUS[gap.status] || STATUS.pending;
    const node = h("div", { class: `gap is-${gap.status || "pending"}` },
      h("div", { class: "gap-top" },
        h("span", { class: "gap-id" }, gap.id || "G?"),
        h("span", { class: "gap-q" }, gap.question || ""),
        h("span", { class: `status ${cls}` }, label),
      ),
      h("p", { class: "gap-why" }, gap.why || ""),
    );
    if (gap.note && gap.status !== "covered") {
      node.append(h("p", { class: "gap-why", style: "color:#9a7418" }, gap.note));
    }
    gapList.append(node);
  }
  if (gaps.length === 0) {
    gapList.append(h("p", { class: "muted" }, "没有识别出需要外部证据的缺口。"));
  }
}

function renderAnswer(payload) {
  const answer = payload.answer || {};
  const pane = $("#answerPane");
  clear(pane);

  const head = h("div", { class: "answer-head" },
    h("div", null,
      h("h2", null, text(answer.headline, "诊断结果")),
      h("p", { class: "answer-sub" },
        [answer.model, answer.material, answer.symptom].filter(Boolean).join(" · ") || payload.question,
      ),
    ),
    h("div", { class: "answer-badges" }),
  );
  const badges = head.querySelector(".answer-badges");
  const [confLabel, confClass] = CONFIDENCE[answer.confidence] || CONFIDENCE.medium;
  badges.append(h("span", { class: `badge ${confClass}` }, confLabel));
  const coverage = answer.coverage || {};
  const covered = coverage.covered || 0;
  const total = covered + (coverage.partial || 0) + (coverage.insufficient || 0) + (coverage.need_user || 0);
  if (total) badges.append(h("span", { class: "badge" }, `缺口覆盖 ${covered}/${total}`));
  if (payload.replayed) badges.append(h("span", { class: "badge replay" }, "回放"));
  pane.append(head);

  pane.append(h("p", { class: "summary" }, text(answer.summary, "没有生成摘要。")));

  if (Array.isArray(answer.steps) && answer.steps.length) {
    const steps = h("div", { class: "steps" });
    for (const step of answer.steps) {
      const sids = h("div", { class: "step-sids" });
      for (const sid of step.sids || []) {
        sids.append(h("button", {
          class: "cite", type: "button", title: `查看 ${sid} 证据`,
          onclick: () => focusEvidence(sid),
        }, sid));
      }
      steps.append(h("div", { class: "step-row" },
        h("div", { class: "step-num" }, String(step.n || "")),
        h("div", { class: "step-body" },
          h("div", { class: "step-title" }, step.title || ""),
          h("p", { class: "step-text" }, step.text || ""),
          sids,
        ),
      ));
    }
    pane.append(h("div", { class: "block" }, h("div", { class: "block-title" }, "下一步，按这个顺序"), steps));
  }

  if (Array.isArray(answer.conflict_notes) && answer.conflict_notes.length) {
    const block = h("div", { class: "block" }, h("div", { class: "block-title" }, "需要你知道的分歧"));
    for (const note of answer.conflict_notes) {
      const textValue = typeof note === "string" ? note : (note && note.text) || "";
      const sids = (typeof note === "object" && note && note.sids) || [];
      const card = h("div", { class: "conflict-card" }, textValue);
      if (sids.length) {
        const row = h("div", { class: "step-sids" });
        for (const sid of sids) {
          row.append(h("button", {
            class: "cite", type: "button", title: `查看 ${sid} 证据`,
            onclick: () => focusEvidence(sid),
          }, sid));
        }
        card.append(row);
      }
      block.append(card);
    }
    pane.append(block);
  }

  if (answer.followup) {
    pane.append(h("div", { class: "block" },
      h("div", { class: "block-title" }, "还需要你确认"),
      h("div", { class: "followup-card" },
        h("p", { class: "q" }, answer.followup),
        h("p", { class: "why" }, "补上这条信息，下一轮检索才能收敛；现在给的是保守结论。"),
      ),
    ));
  }

  if (Array.isArray(answer.uncertainties) && answer.uncertainties.length) {
    const list = h("ul", { class: "uncertainty-list" });
    for (const item of answer.uncertainties) list.append(h("li", null, item));
    pane.append(h("div", { class: "block" }, h("div", { class: "block-title" }, "边界与不确定"), list));
  }

  if (answer.kb_note) {
    const note = answer.kb_note;
    const block = h("div", { class: "block" });
    const line = h("div", { class: "kb-note" }, h("strong", null, "私域笔记"));
    if (typeof note === "string") {
      line.append(h("span", null, note));
    } else if (Array.isArray(note.items)) {
      const list = h("div", { class: "kb-items" });
      for (const item of note.items) {
        list.append(h("div", { class: "kb-item" },
          h("span", null, item.title || item.id || ""),
          h("span", { class: "muted" }, `${item.created_at || ""}${item.stale ? " · 旧笔记" : ""}`),
        ));
      }
      line.append(list);
    }
    block.append(line);
    pane.append(block);
  }

  const stats = (payload.search || {}).stats || {};
  pane.append(h("div", { class: "answer-footer" },
    h("span", null, `run ${payload.run_id || "—"}`),
    h("span", null, `耗时 ${fmtMs(payload.elapsed_ms)}`),
    h("span", null, `证据 ${stats.evidence_count ?? (payload.evidence || []).length} 条`),
    h("span", null, `调用 ${stats.calls ?? (payload.search?.calls || []).length} 次`),
    h("span", null, `数值断言 ${stats.claims ?? (payload.claims || []).length} 条`),
    h("span", null, `冲突 ${stats.conflicts ?? (payload.conflicts || []).length} 处`),
  ));
}

function renderEvidence(payload) {
  const pane = $("#evidencePane");
  clear(pane);
  const evidence = payload.evidence || [];
  pane.append(h("div", { class: "evidence-head" },
    h("h2", null, "公开证据"),
    h("span", null, `${evidence.length} 条 · 按权威度 / 新鲜度 / 相关度排序`),
  ));
  if (!evidence.length) {
    pane.append(h("p", { class: "muted" }, "这次没有拿到公开证据；回答应当降级为追问，而不是硬给结论。"));
    return;
  }
  for (const item of evidence) {
    const card = h("article", { class: "evidence-card", id: `ev-${item.id}` },
      h("div", { class: "ev-top" },
        h("span", { class: "rank" }, item.id || "S?"),
        h("div", { class: "ev-title" },
          h("a", { href: safeUrl(item.url), target: "_blank", rel: "noopener noreferrer" }, text(item.title, "无标题")),
        ),
      ),
      h("div", { class: "ev-meta" },
        h("span", { class: `tier tier-${item.tier || "general"}` }, item.tier_label || item.tier || "网页"),
        h("span", null, item.site || ""),
        item.date ? h("span", null, item.date) : null,
        h("span", null, `相关度 ${pct(item.relevance)}`),
        h("span", null, `新鲜度 ${pct(item.freshness)}`),
        item.authority_level !== null && item.authority_level !== undefined
          ? h("span", null, `权威 ${item.authority_level}/5`) : null,
      ),
      h("p", { class: "ev-passage" }, text(item.passage || item.content, "（无摘要）")),
    );
    const foot = h("div", { class: "ev-foot" });
    for (const qid of item.qids || []) foot.append(h("span", { class: "mini-chip" }, qid));
    for (const gid of item.covers || []) foot.append(h("span", { class: "mini-chip g1" }, gid));
    if (foot.childNodes.length) card.append(foot);
    pane.append(card);
  }
}

function renderPlan(payload) {
  const plan = payload.plan || {};
  const pane = $("#planPane");
  clear(pane);
  pane.append(h("div", { class: "plan-hero" },
    h("span", { class: "k" }, "编译器改写后的问题"),
    h("p", null, text(plan.rewritten_question, payload.question)),
    h("div", { class: "strategy" }, text(plan.strategy, "先补私域缺口，再用公开证据校验。")),
  ));
  if (plan.naive_query) {
    pane.append(h("div", { class: "block" },
      h("div", { class: "block-title" }, "对照：如果只把原话丢给搜索"),
      h("div", { class: "plan-hero" }, h("p", { style: "font-family:ui-monospace,Consolas,monospace;font-size:12px" }, plan.naive_query)),
    ));
  }
  const queries = plan.queries || [];
  const block = h("div", { class: "block" }, h("div", { class: "block-title" }, `检索任务书 · ${queries.length} 条`));
  for (const query of queries) {
    const card = h("div", { class: "query-card" },
      h("div", { class: "query-top" },
        h("span", { class: "qid" }, query.id || "Q?"),
        h("span", { class: "query-purpose" }, query.purpose || ""),
      ),
      h("p", { class: "query-text" }, query.text || ""),
      paramsRow(query.params),
    );
    const foot = h("div", { class: "params" });
    for (const gid of query.covers || []) foot.append(h("span", { class: "mini-chip g1" }, gid));
    if (query.weight !== undefined) foot.append(h("span", { class: "mini-chip" }, `w=${query.weight}`));
    if (foot.childNodes.length) card.append(foot);
    block.append(card);
  }
  if (!queries.length) block.append(h("p", { class: "muted" }, "没有生成检索任务。"));
  pane.append(block);
}

function renderTrace(payload) {
  const pane = $("#tracePane");
  clear(pane);
  const trace = payload.trace || {};
  const stats = trace.stats || (payload.search || {}).stats || {};
  const calls = trace.calls || (payload.search || {}).calls || [];

  pane.append(h("div", { class: "trace-summary" },
    metric(fmtMs(payload.elapsed_ms), "总耗时"),
    metric(String(calls.length), "SearchPro 调用"),
    metric(String(stats.evidence_count ?? (payload.evidence || []).length), "证据"),
    metric(String(stats.claims ?? (payload.claims || []).length), "数值断言"),
  ));

  const stages = trace.stages || payload.stages || [];
  if (stages.length) {
    const timeline = h("div", { class: "timeline" });
    for (const stage of stages) {
      timeline.append(h("div", { class: "stage" },
        h("div", { class: "stage-dot" }),
        h("div", { class: "stage-body" },
          h("div", { class: "stage-name" }, stage.name || ""),
          h("div", { class: "stage-detail" }, stage.detail || ""),
        ),
        h("div", { class: "stage-ms" }, `${stage.ms ?? 0}ms`),
      ));
    }
    pane.append(h("div", { class: "block" }, h("div", { class: "block-title" }, "链路耗时"), timeline));
  }

  if (calls.length) {
    const table = h("div", { class: "trace-table" });
    table.append(h("div", { class: "trace-row head" },
      h("span", null, "Q"), h("span", null, "查询"), h("span", null, "页数"), h("span", null, "耗时"), h("span", null, "RequestId"),
    ));
    for (const call of calls) {
      const params = Object.entries(call.params || {}).map(([k, v]) => `${k}=${v}`).join(" · ");
      table.append(h("div", { class: "trace-row" },
        h("span", { class: "mono" }, call.qid || ""),
        h("div", null,
          h("div", { class: "q-text" }, call.query || ""),
          h("div", { class: "mono", style: "margin-top:3px" }, params + (call.fallback ? ` · fallback=${call.fallback}` : "")),
          call.error ? h("div", { class: "err" }, `${call.error}: ${call.detail || ""}`) : null,
        ),
        h("span", { class: "mono" }, String(call.pages ?? 0)),
        h("span", { class: "mono" }, fmtMs(call.latency_ms)),
        h("span", { class: "mono" }, call.request_id || "—"),
      ));
    }
    pane.append(h("div", { class: "block" }, h("div", { class: "block-title" }, "调用明细"), table));
  }

  const actions = h("div", { class: "trace-actions" });
  if (payload.run_id) {
    actions.append(h("a", { href: `/api/runs/${payload.run_id}?download=1` }, "下载本次 trace JSON ↗"));
  }
  actions.append(h("span", { class: "muted" },
    `official ${stats.official ?? 0} · community ${stats.community ?? 0} · 冲突 ${stats.conflicts ?? 0} · ${trace.credential_kind || payload.credential_kind || ""}`,
  ));
  pane.append(actions);
}

function metric(number, label) {
  return h("div", { class: "metric" }, h("span", { class: "num" }, number), h("span", { class: "lbl" }, label));
}

/* ---------------------------------------------------------------- tabs */
function switchTab(name, silent = false) {
  const valid = ["answer", "evidence", "plan", "trace"];
  if (!valid.includes(name)) name = "answer";
  state.activeTab = name;
  for (const tab of $$(".tab")) {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  }
  for (const pane of ["answer", "evidence", "plan", "trace"]) {
    const node = $(`#${pane}Pane`);
    if (node) node.classList.toggle("hidden", pane !== name);
  }
  if (!silent) {
    const url = new URL(location.href);
    if (name === "answer") url.searchParams.delete("tab");
    else url.searchParams.set("tab", name);
    history.replaceState(null, "", url);
  }
}

function focusEvidence(sid) {
  switchTab("evidence");
  const target = document.getElementById(`ev-${sid}`);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("is-focus");
  setTimeout(() => target.classList.remove("is-focus"), 1800);
}

function initialTab() {
  const tab = new URLSearchParams(location.search).get("tab");
  return ["answer", "evidence", "plan", "trace"].includes(tab) ? tab : "answer";
}

/* ---------------------------------------------------------------- boot */
function boot() {
  updateCount();
  $("#question").addEventListener("input", updateCount);
  $("#question").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      ask();
    }
  });
  $("#askBtn").addEventListener("click", ask);
  for (const tab of $$(".tab")) {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  }
  loadHealth();
  loadCases().then(() => {
    const params = new URLSearchParams(location.search);
    const caseId = params.get("case");
    const question = params.get("q");
    if (caseId) {
      const found = state.cases.find((item) => item.id === caseId);
      if (found) {
        $("#question").value = found.question;
        updateCount();
        ask();
        return;
      }
    }
    if (question) {
      $("#question").value = question.slice(0, 1200);
      updateCount();
      ask();
    }
  });
}

document.addEventListener("DOMContentLoaded", boot);
