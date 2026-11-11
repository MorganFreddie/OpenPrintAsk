/* 得师傅·外脑 v2 前端：无框架，所有用户/检索文本走 textContent。 */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function getClientId() {
    const key = "deshifu.client_id";
    try {
      let value = localStorage.getItem(key);
      if (!value || value.length < 8) {
        value = (crypto && crypto.randomUUID)
          ? crypto.randomUUID()
          : "c-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
        localStorage.setItem(key, value);
      }
      return value;
    } catch (err) {
      return "c-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
    }
  }

  const state = {
    plan: null,
    answer: null,
    receipts: [],
    busy: false,
    seq: 0,
    timer: 0,
    clientId: getClientId(),
  };

  const question = $("#question");
  const count = $("#count");
  const askBtn = $("#askBtn");
  const askHTML = askBtn.innerHTML;
  const toastBox = $("#toast");

  function toast(message, kind) {
    toastBox.textContent = message;
    toastBox.className = "toast show" + (kind ? " " + kind : "");
    clearTimeout(toastBox._timer);
    toastBox._timer = setTimeout(() => {
      toastBox.className = "toast";
    }, kind === "error" ? 5200 : 3200);
  }

  function seconds(ms) {
    if (!Number.isFinite(Number(ms))) return "—";
    return (Number(ms) / 1000).toFixed(1) + "s";
  }

  function safeUrl(url) {
    try {
      const parsed = new URL(String(url || ""), location.href);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "#";
    } catch (err) {
      return "#";
    }
  }

  /* ------------------------------------------------------------ health */
  async function checkHealth() {
    const dot = $("#statusDot");
    const text = $("#statusText");
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      const data = await res.json();
      const replay = data.mode === "replay";
      dot.className = "dot " + (replay ? "replay" : data.ok ? "live" : "off");
      if (replay) {
        text.textContent = "离线回放 · 不调用 API";
        text.title = "当前使用本地 fixtles 回放，结果会明确标注。";
      } else if (data.ok) {
        text.textContent = "实时 · SearchPro";
        text.title = data.detail || "SearchPro 凭证已配置。";
      } else {
        text.textContent = "检索不可用";
        text.title = data.detail || "未配置检索凭证。";
      }
    } catch (err) {
      dot.className = "dot off";
      text.textContent = "服务未连接";
      text.title = String(err);
    }
  }

  /* ----------------------------------------------------------- preview */
  const SLOT_KEYS = ["model", "material", "symptom", "tried", "environment"];
  const SLOT_LABELS = { model: "机型", material: "材料", symptom: "现象", tried: "已尝试", environment: "环境" };

  function resetPreview() {
    const grid = $("#chips");
    clear(grid);
    SLOT_KEYS.forEach((key) => {
      const chip = el("div", "chip miss");
      chip.append(el("small", null, SLOT_LABELS[key]), el("b", null, key === "tried" || key === "environment" ? "可留空" : "待补充"));
      grid.append(chip);
    });
    $$("#slotStrip span").forEach((node) => {
      node.className = "";
      node.removeAttribute("title");
    });
    $("#rewrite").textContent = "";
    $("#rewrite").append(el("small", null, "编译器改写"), document.createTextNode(" 写下问题后，这里会显示它真正拿去检索的那句话。"));
    $("#coverage").textContent = "0 / 5 格";
    clear($("#gapPreview"));
    $("#gapPreview").append(el("li", "hint", "还没有输入。"));
    clear($("#queryPreview"));
    $("#queryPreview").append(el("div", "hint", "还没有输入。"));
    state.plan = null;
  }

  function setSlotStrip(plan) {
    const chips = new Map((plan.chips || []).map((chip) => [chip.key, chip]));
    $$("#slotStrip span").forEach((node) => {
      const key = node.dataset.slot;
      const chip = chips.get(key);
      const filled = chip && chip.state === "filled";
      node.className = filled ? "on" : (key === "tried" || key === "environment" ? "" : "miss");
      node.title = filled ? chip.value : (key === "tried" || key === "environment" ? "可留空" : "建议补充");
    });
  }

  function renderPreview(plan) {
    const grid = $("#chips");
    clear(grid);
    (plan.chips || []).forEach((chip) => {
      const node = el("div", "chip " + (chip.state === "filled" ? "on" : "miss"));
      node.append(el("small", null, chip.label || SLOT_LABELS[chip.key] || chip.key));
      node.append(el("b", null, chip.value || "待补充"));
      grid.append(node);
    });

    setSlotStrip(plan);

    const rewrite = $("#rewrite");
    clear(rewrite);
    rewrite.append(el("small", null, "编译器改写"));
    rewrite.append(document.createTextNode(" " + (plan.rewritten_question || "—")));

    const coverage = plan.coverage || {};
    $("#coverage").textContent = (coverage.filled || 0) + " / " + (coverage.total || 5) + " 格";

    const gaps = $("#gapPreview");
    clear(gaps);
    if (!plan.gaps || !plan.gaps.length) {
      gaps.append(el("li", "hint", "五格都够了，直接检索。"));
    } else {
      plan.gaps.slice(0, 4).forEach((gap) => {
        const li = el("li");
        li.append(el("span", "tag", gap.id), document.createTextNode(gap.question || ""));
        gaps.append(li);
      });
      if (plan.gaps.length > 4) gaps.append(el("li", "hint", "还有 " + (plan.gaps.length - 4) + " 个缺口，诊断后看任务书。"));
    }

    const queries = $("#queryPreview");
    clear(queries);
    (plan.queries || []).slice(0, 5).forEach((query) => {
      const row = el("div", "query");
      row.append(el("span", "qid", query.id), document.createTextNode(query.text || ""));
      queries.append(row);
    });
    if (!plan.queries || !plan.queries.length) queries.append(el("div", "hint", "还没有生成查询。"));
  }

  async function compilePreview() {
    const text = question.value.trim();
    if (!text) {
      resetPreview();
      return;
    }
    const seq = ++state.seq;
    try {
      const res = await fetch("/api/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      const data = await res.json();
      if (seq !== state.seq) return;
      if (!res.ok) throw new Error(data.detail || data.error || "编译失败");
      state.plan = data.plan;
      renderPreview(data.plan);
    } catch (err) {
      if (seq === state.seq) toast("编译器暂时不可用：" + err.message, "error");
    }
  }

  /* ------------------------------------------------------------ answer */
  function sidLink(sid) {
    const link = el("a", "sid", sid);
    link.href = "#ev-" + sid;
    link.dataset.sid = sid;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      switchTab("evidence");
      const target = document.getElementById("ev-" + sid);
      if (target) {
        target.scrollIntoView({ block: "center", behavior: "smooth" });
        target.classList.add("flash");
        setTimeout(() => target.classList.remove("flash"), 1200);
      }
    });
    return link;
  }

  function renderReceiptPanel(step) {
    const box = el("div", "receipt");
    box.dataset.step = step.title || "";
    const line = el("div", "receipt-line");
    line.append(el("b", null, "复现回执 · "), el("span", "hint", "同机型 / 同材料 / 同现象，试完再记，不猜。"));
    box.append(line);
    box.append(el("div", "receipt-summary hint", "还没有同机型/同材料的回执。"));

    const actions = el("div", "receipt-actions");
    [
      ["fixed", "有效", "yes"],
      ["not_fixed", "没解决", "no"],
      ["not_tried", "还没试", "muted"],
    ].forEach(([outcome, label, cls]) => {
      const btn = el("button", cls, label);
      btn.type = "button";
      btn.addEventListener("click", () => submitReceipt(step.title || "", outcome, btn));
      actions.append(btn);
    });
    box.append(actions);
    return box;
  }

  function renderAnswer(payload) {
    const answer = payload.answer || {};
    const stats = (payload.search && payload.search.stats) || {};

    $("#headline").textContent = answer.headline || "诊断结果";
    const metaParts = [
      answer.model || "机型未识别",
      answer.material || "材料未识别",
      answer.symptom || "",
      (stats.calls || 0) + " 条查询 / " + (stats.evidence_count || 0) + " 条证据",
      seconds(payload.elapsed_ms),
    ].filter(Boolean);
    $("#metaLine").textContent = metaParts.join(" · ");

    const badge = $("#confBadge");
    const conf = answer.confidence || "medium";
    badge.className = "badge " + conf;
    badge.textContent = conf === "high" ? "高置信" : conf === "low" ? "低置信" : "中置信";

    $("#summary").textContent = answer.summary || "";

    const steps = $("#steps");
    clear(steps);
    (answer.steps || []).forEach((step) => {
      const li = el("li", "step");
      li.append(el("span", "step-num", step.n || ""));
      const body = el("div");
      body.append(el("h3", null, step.title || "步骤"));
      if (step.text) body.append(el("p", null, step.text));
      const sids = el("div", "sids");
      (step.sids || []).forEach((sid) => sids.append(sidLink(sid)));
      if (sids.childNodes.length) body.append(sids);
      body.append(renderReceiptPanel(step));
      li.append(body);
      steps.append(li);
    });
    if (!steps.childNodes.length) steps.append(el("li", "hint", "这轮没有形成可执行步骤，先补缺口。"));

    const conflicts = $("#conflicts");
    clear(conflicts);
    if (answer.conflict_notes && answer.conflict_notes.length) {
      const card = el("div", "note-card danger");
      card.append(el("h3", null, "需要你知道的分歧"));
      const ul = el("ul");
      answer.conflict_notes.forEach((note) => ul.append(el("li", null, note)));
      card.append(ul);
      conflicts.append(card);
    }

    const followup = $("#followup");
    clear(followup);
    if (answer.followup) {
      const card = el("div", "note-card");
      card.append(el("h3", null, "还需要你确认"));
      card.append(el("p", null, answer.followup));
      followup.append(card);
    }

    const uncertainties = $("#uncertainties");
    clear(uncertainties);
    if (answer.uncertainties && answer.uncertainties.length) {
      const card = el("div", "note-card");
      card.append(el("h3", null, "边界与不确定"));
      const ul = el("ul");
      answer.uncertainties.forEach((note) => ul.append(el("li", null, note)));
      card.append(ul);
      uncertainties.append(card);
    }

    if (answer.kb_note && answer.kb_note.used && answer.kb_note.items && answer.kb_note.items.length) {
      const card = el("div", "note-card");
      card.append(el("h3", null, "私域笔记（未出机）"));
      answer.kb_note.items.forEach((item) => {
        const p = el("p");
        p.append(document.createTextNode(item.title || item.id));
        p.append(document.createTextNode(" · " + (item.created_at || "")));
        if (item.stale) p.append(el("span", "tag", "可能过时"));
        card.append(p);
      });
      uncertainties.append(card);
    }

    if (answer.source_note) uncertainties.append(el("p", "hint", answer.source_note));

    const pill = $("#modePill");
    pill.className = "pill" + (payload.replayed ? " warn" : "");
    pill.textContent = payload.replayed ? "离线回放" : "实时检索";

    $("#preview").hidden = true;
    $("#answerEmpty").hidden = true;
    $("#answerBody").hidden = false;
    $("#evidenceCount").textContent = String((payload.evidence || []).length);
    $("#planCount").textContent = String(((payload.plan && payload.plan.queries) || []).length);
  }

  /* ---------------------------------------------------------- evidence */
  function renderEvidence(payload) {
    const list = $("#evidenceList");
    clear(list);
    const evidence = payload.evidence || [];
    if (!evidence.length) {
      list.append(el("div", "hint", "这轮没有检索到可用证据。可以补充机型/现象，或换一种说法再试。"));
      return;
    }
    evidence.forEach((ev) => {
      const card = el("article", "evidence");
      card.id = "ev-" + ev.id;
      const top = el("div", "top");
      const tier = ev.tier || "general";
      top.append(el("span", "kind " + (tier === "official" ? "" : tier), ev.tier_label || tier));
      const title = el("b");
      const link = el("a", null, (ev.id ? ev.id + " · " : "") + (ev.title || "未命名页面"));
      link.href = safeUrl(ev.url);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      title.append(link);
      top.append(title);
      if (ev.site) top.append(el("span", "site", ev.site));
      if (ev.date) top.append(el("span", "site", ev.date));
      card.append(top);

      const passage = String(ev.passage || ev.content || "").replace(/\s+/g, " ").trim();
      if (passage) card.append(el("p", null, passage.length > 300 ? passage.slice(0, 300) + "…" : passage));

      if (ev.url) {
        const url = el("a", "url", ev.url);
        url.href = safeUrl(ev.url);
        url.target = "_blank";
        url.rel = "noopener noreferrer";
        card.append(url);
      }
      const meta = [];
      if (ev.covers && ev.covers.length) meta.push("覆盖 " + ev.covers.join("/"));
      if (ev.qids && ev.qids.length) meta.push("来自 " + ev.qids.join("/"));
      if (ev.relevance) meta.push("相关度 " + Number(ev.relevance).toFixed(2));
      if (meta.length) card.append(el("div", "hint", meta.join(" · ")));
      list.append(card);
    });
  }

  /* -------------------------------------------------------------- plan */
  function renderPlanTab(plan) {
    const box = $("#planBox");
    clear(box);
    if (!plan) {
      box.append(el("div", "hint", "还没有诊断。"));
      return;
    }

    if (plan.strategy) {
      const strategy = el("div", "note-card");
      strategy.append(el("h3", null, "这轮策略"));
      strategy.append(el("p", null, plan.strategy));
      box.append(strategy);
    }

    const gapBlock = el("div", "plan-block");
    gapBlock.append(el("h3", null, "缺口 G：检索前先决定要补什么"));
    (plan.gaps || []).forEach((gap) => {
      const card = el("div", "gap");
      card.append(el("span", "tag", gap.id), el("b", null, gap.question || ""));
      if (gap.why) card.append(el("p", null, gap.why));
      gapBlock.append(card);
    });
    if (!plan.gaps || !plan.gaps.length) gapBlock.append(el("p", "hint", "没有明显缺口。"));
    box.append(gapBlock);

    const queryBlock = el("div", "plan-block");
    queryBlock.append(el("h3", null, "查询 Q：真正发出去的句子和参数"));
    (plan.queries || []).forEach((query) => {
      const card = el("div", "query-full");
      card.append(el("span", "qid", query.id), document.createTextNode(query.text || ""));
      if (query.params) {
        const params = Object.entries(query.params).map(([key, value]) => key + "=" + value).join(" · ");
        card.append(el("div", "params", params));
      }
      if (query.purpose) card.append(el("div", "purpose", "目的：" + query.purpose));
      const meta = [];
      if (query.covers && query.covers.length) meta.push("覆盖 " + query.covers.join("/"));
      if (query.weight) meta.push("权重 " + query.weight);
      if (meta.length) card.append(el("div", "params", meta.join(" · ")));
      queryBlock.append(card);
    });
    if (!plan.queries || !plan.queries.length) queryBlock.append(el("p", "hint", "还没有生成查询。"));
    box.append(queryBlock);
  }

  /* ------------------------------------------------------------- trace */
  function renderTrace(payload) {
    const box = $("#traceBox");
    clear(box);
    const stats = (payload.search && payload.search.stats) || {};
    const calls = (payload.search && payload.search.calls) || [];

    const metrics = el("div", "metrics");
    [
      [String(stats.calls || 0), "检索调用"],
      [String(stats.evidence_count || 0), "证据条数"],
      [String(stats.official || 0), "官方证据"],
      [seconds(stats.latency_ms || payload.elapsed_ms), "总耗时"],
    ].forEach(([value, label]) => {
      const metric = el("div", "metric");
      metric.append(el("b", null, value), el("small", null, label));
      metrics.append(metric);
    });
    box.append(metrics);

    const timeline = el("div", "timeline");
    (payload.stages || []).forEach((stage) => {
      const row = el("div", "tl");
      row.append(el("b", null, stage.name || ""));
      row.append(el("span", null, stage.ms != null ? stage.ms + "ms" : ""));
      row.append(el("p", null, stage.detail || ""));
      timeline.append(row);
    });
    box.append(timeline);

    const heading = el("div", "section-label", "调用记录");
    box.append(heading);
    calls.forEach((call) => {
      const card = el("div", "query-full");
      card.append(el("span", "qid", call.qid || ""), document.createTextNode(call.query || ""));
      const params = call.params ? Object.entries(call.params).map(([key, value]) => key + "=" + value).join(" · ") : "";
      const bits = [params, seconds(call.latency_ms), (call.pages || 0) + " 页"];
      if (call.request_id) bits.push("req " + String(call.request_id).slice(0, 8));
      if (call.fallback) bits.push("fallback=" + call.fallback);
      if (call.error) bits.push("error=" + call.error);
      card.append(el("div", "params", bits.filter(Boolean).join(" · ")));
      if (call.purpose) card.append(el("div", "purpose", call.purpose));
      box.append(card);
    });
    if (!calls.length) box.append(el("p", "hint", "这次没有调用记录。"));

    if (payload.run_id) {
      const footer = el("p", "hint");
      footer.append(document.createTextNode("run id：" + payload.run_id + " · "));
      const link = el("a", "url", "下载原始记录");
      link.href = "/api/runs/" + encodeURIComponent(payload.run_id);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      footer.append(link);
      box.append(footer);
    }
  }

  /* ----------------------------------------------------------- receipts */
  function receiptKey() {
    const answer = state.answer || {};
    const slots = (state.plan && state.plan.slots) || {};
    return {
      model: slots.model || answer.model || "",
      material: (slots.materials || []).join("/") || slots.material || answer.material || "",
      symptom: (slots.symptom_ids || []).join(",") || answer.symptom || "",
    };
  }

  async function loadReceipts() {
    if (!state.answer) return;
    const params = new URLSearchParams(receiptKey());
    try {
      const res = await fetch("/api/receipts?" + params.toString(), { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) return;
      state.receipts = data.receipts || [];
      renderReceiptSummaries();
    } catch (err) {
      /* 回执是增强项，失败不挡主流程 */
    }
  }

  function renderReceiptSummaries() {
    const byStep = new Map(state.receipts.map((row) => [row.step_title, row]));
    $$(".receipt").forEach((box) => {
      const summary = box.querySelector(".receipt-summary");
      if (!summary) return;
      const row = byStep.get(box.dataset.step);
      if (!row) {
        summary.textContent = "还没有同机型/同材料的回执。";
        return;
      }
      if (!row.visible) {
        summary.textContent = "已有回执，但不足 3 条，暂不显示汇总。";
        return;
      }
      summary.textContent = "同机型同材料 " + row.total + " 人复现：" + row.fixed + " 成功 · " + row.not_fixed + " 没解决；最近 " + (row.last_at || "") + "。";
    });
  }

  async function submitReceipt(stepTitle, outcome, button) {
    const answer = state.answer;
    if (!answer) return;
    button.disabled = true;
    try {
      const res = await fetch("/api/receipts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: answer.run_id,
          step_title: stepTitle,
          ...receiptKey(),
          outcome: outcome,
          note: "",
          client_id: state.clientId,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || "记录失败");
      toast(outcome === "fixed" ? "已记录：这条对你有效。" : outcome === "not_fixed" ? "已记录：这条没解决。" : "已记录：还没试。");
      await loadReceipts();
    } catch (err) {
      toast("回执记录失败：" + err.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  /* --------------------------------------------------------------- tabs */
  function switchTab(name) {
    $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
    $$(".pane").forEach((pane) => pane.classList.toggle("active", pane.id === "pane-" + name));
  }

  /* --------------------------------------------------------------- ask */
  async function ask() {
    const text = question.value.trim();
    if (!text) {
      toast("先写一句你遇到的情况，不用写标准问题。");
      question.focus();
      return;
    }
    if (state.busy) return;
    state.busy = true;
    askBtn.disabled = true;
    askBtn.innerHTML = "<span>正在编译并检索…</span><small>先补缺口，再检索；通常 3–8 秒</small>";
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || "请求失败");
      state.answer = data;
      state.plan = data.plan;
      renderAnswer(data);
      renderEvidence(data);
      renderPlanTab(data.plan);
      renderTrace(data);
      switchTab("answer");
      loadReceipts();
      toast(data.replayed ? "这是离线回放结果，不是实时检索。" : "诊断完成。", data.replayed ? "warn" : "ok");
    } catch (err) {
      toast("诊断失败：" + err.message, "error");
    } finally {
      state.busy = false;
      askBtn.disabled = false;
      askBtn.innerHTML = askHTML;
    }
  }

  /* --------------------------------------------------------------- init */
  question.addEventListener("input", () => {
    count.textContent = question.value.length + " / 1200";
    clearTimeout(state.timer);
    state.timer = setTimeout(compilePreview, 280);
  });

  question.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      ask();
    }
  });

  askBtn.addEventListener("click", ask);

  $$(".example").forEach((button) => {
    button.addEventListener("click", () => {
      question.value = button.dataset.q || "";
      count.textContent = question.value.length + " / 1200";
      question.focus();
      compilePreview();
    });
  });

  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  $("#guideBtn").addEventListener("click", () => {
    const guide = $("#guide");
    guide.open = true;
    guide.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  $("#exampleBtn").addEventListener("click", () => {
    const first = $(".example");
    if (first) first.click();
  });

  const preset = new URLSearchParams(location.search).get("q");
  if (preset) {
    question.value = preset;
    count.textContent = preset.length + " / 1200";
    compilePreview();
  } else {
    resetPreview();
  }

  checkHealth();
})();
