/* Governed Work — read-only local operations viewer.
 *
 * Vanilla, offline, no external requests. All stored data is rendered through
 * createElement/textContent only: `*_raw` payload strings are never parsed
 * (only the top-level response envelope is), and string-encoded integers
 * (seq, versions, revisions, cursors) reach the DOM as exact text — never
 * through Number(). Stale responses are dropped by refresh/detail epochs, so
 * an older payload can never overwrite a newer view or another work's detail.
 */
"use strict";

(function () {
  var I18N = {
    en: {
      "brand.subtitle": "Operations Viewer",
      "meta.inventory": "Durable tables",
      "list.heading": "Works",
      "action.refresh": "Refresh", "action.pause": "Pause polling",
      "action.resume": "Resume polling", "action.retry": "Try again",
      "action.loadMore": "Load more events", "action.reload": "Reload",
      "filter.search": "Search by id or owner", "filter.allStatuses": "All statuses",
      "tile.openWorks": "Open works",
      "tile.openWorks.desc": "Works not yet closed",
      "tile.closedSucceeded": "Closed · succeeded",
      "tile.closedSucceeded.desc": "Closed works with a succeeded outcome",
      "tile.closedCancelled": "Closed · cancelled",
      "tile.closedCancelled.desc": "Closed works with a cancelled outcome",
      "tile.uncertainOps": "Uncertain operations",
      "tile.uncertainOps.desc": "Dispatched or outcome-unknown operations",
      "tile.pendingEvidence": "Pending evidence",
      "tile.pendingEvidence.desc": "Evidence awaiting verification",
      "list.loading": "Loading works…", "list.empty": "This store holds no works.",
      "list.noMatch": "No works match the current filter.",
      "list.showing": "Showing {shown} of {total} works",
      "list.capped": " (first 200 loaded)",
      "meta.schema": "schema {version}",
      "meta.sampledAt": "Sampling time {time} — observation, not business-event time",
      "meta.pollPaused": "polling paused",
      "banner.disconnected": "Disconnected from the local UI server. The viewer keeps retrying; check the ui process.",
      "detail.placeholder": "Select a work to inspect its durable history.",
      "detail.placeholderHint": "Use ↑/↓ to move through the list, Enter to select, or pick a card below.",
      "detail.guideTitle": "Works in this store — click to inspect",
      "detail.loading": "Loading work…",
      "detail.gone": "This work is no longer present in the store.",
      "detail.error": "Could not load this work.",
      "tab.overview": "Overview", "tab.requirements": "Requirements",
      "tab.evidence": "Evidence", "tab.operations": "Operations",
      "tab.decisions": "Decisions", "tab.events": "Events",
      "tab.documents": "Documents",
      "sec.lifecycle": "Lifecycle & ownership",
      "sec.contract": "Contract & revisions",
      "kpi.requirements": "{satisfied}/{total} satisfied",
      "kpi.requirementsSub": "Current contract obligations",
      "kpi.evidence": "{verified}/{total} verified",
      "kpi.evidenceSub": "Recorded proof items",
      "kpi.operations": "{total} operation(s)",
      "kpi.operationsSub": "Latest: {latest}",
      "kpi.decisions": "{total} receipt(s)",
      "kpi.decisionsSub": "{accepted} accepted · {rejected} rejected",
      "demo.label": "Demo scenario",
      "demo.wait-1.short": "Durable wait on E05 approval · pending verification",
      "demo.wait-1.long": "Submitted approval evidence is pending verification; the work waits durably on E05 and preserves the earlier rejected proposal decision.",
      "demo.uncertain-1.short": "Committed external effect · lookup unavailable",
      "demo.uncertain-1.long": "External OA committed the application before the response was lost; unavailable authority lookup escalated to needs_attention while retaining the external effect.",
      "demo.transfer-1.short": "Ownership handover to delegate · intent readmitted",
      "demo.transfer-1.long": "Ownership transferred from agent to delegate, invalidating the prior prepared intent; delegate readmitted the same logical operation and confirmed submission.",
      "demo.succeed-1.short": "Verified evidence & confirmed effect · closed succeeded",
      "demo.succeed-1.long": "All policy requirements were satisfied with verified evidence and confirmed OA acceptance, closing the work as succeeded.",
      "demo.cancel-1.short": "Reconciled effect acknowledged · closed cancelled",
      "demo.cancel-1.long": "Uncertain submission was reconciled to a confirmed external effect first; cancellation explicitly acknowledges the retained external effect rather than reversing it.",
      "f.status": "Status", "f.stateVersion": "State version", "f.owner": "Owner",
      "f.noOwner": "legacy work — no owner recorded", "f.outcome": "Outcome",
      "f.policy": "Contract policy", "f.policyRevision": "Contract revision",
      "f.goal": "Goal", "f.planRevision": "Plan revision",
      "f.documentRevision": "Document revision", "f.documentDigest": "Document digest",
      "f.waits": "Waits", "f.noWaits": "No waits registered.",
      "f.waitId": "wait", "f.waitRequirement": "requirement", "f.waitOwner": "owner",
      "f.waitStatus": "status", "f.waitDeadline": "deadline (epoch)",
      "f.cancellation": "Cancellation", "f.cancellationNone": "No cancellation recorded.",
      "f.requestedBy": "requested by", "f.reason": "reason",
      "cancel.banner": "Cancellation requested by {actor}: {reason}",
      "cancel.ack": "Closed cancelled — the acknowledged external effect is retained, not reversed:",
      "cancel.ackNone": "Closed cancelled — no external effect had been confirmed.",
      "revoke.title": "Revoked evidence on a closed work",
      "revoke.body": "The historical closure and its outcome stay exactly as recorded — this correction does not reopen or rewrite them. The revoked evidence only changes its current status: it no longer counts as valid proof for current requirements.",
      "revoke.cited": "The completion record cites {count} now-revoked evidence id(s):",
      "revoke.records": "Stored records:",
      "req.note": "These are the CURRENT contract requirements. Persisted command decisions (Decisions tab) may carry older blockers recorded at their time.",
      "req.id": "requirement", "req.rule": "rule", "req.subject": "subject",
      "req.applicability": "applicability", "req.fulfillment": "fulfillment",
      "req.explanation": "explanation", "req.none": "No requirements recorded.",
      "evd.note": "Status is the stored record status of this evidence, not an independent source-authentication claim.",
      "evd.source": "source", "evd.eventId": "source event", "evd.kind": "kind",
      "evd.status": "status", "evd.data": "data (exact stored text)",
      "evd.none": "No evidence recorded for this work.",
      "ops.capability": "capability", "ops.actor": "actor", "ops.status": "status",
      "ops.dispatchState": "dispatch state", "ops.reason": "reason",
      "ops.externalId": "external id", "ops.businessKey": "business key",
      "ops.digest": "document digest", "ops.planRevision": "plan revision",
      "ops.contractRevision": "contract revision", "ops.attempts": "attempts",
      "ops.attemptsNone": "no attempts", "ops.document": "operation document (exact stored text)",
      "ops.none": "No operations recorded for this work.",
      "dec.note": "Persisted command receipts are admissions of decisions, not external effects. Their blockers were true at decision time and are separate from current requirements.",
      "dec.actor": "actor", "dec.command": "command", "dec.decision": "decision",
      "dec.code": "code", "dec.version": "state version", "dec.blockers": "blockers",
      "dec.receipt": "receipt (exact stored text)", "dec.none": "No persisted command receipts for this work.",
      "evt.seq": "seq", "evt.version": "version", "evt.type": "type",
      "evt.body": "body (exact stored text)", "evt.none": "No events recorded for this work.",
      "doc.note": "Exact stored JSON text, rendered as text; integers beyond the JavaScript safe range are preserved exactly.",
      "doc.document": "Document (exact stored text)", "doc.plan": "Plan (exact stored text)",
      "doc.completion": "Completion / closure record (exact stored text)",
      "doc.absent": "not recorded",
      "footer.keys": "↑/↓ list · Enter select · ←/→ tabs · / search",
      "footer.readonly": "Read-only local viewer over durable records. Loopback binding is convenience, not authentication."
    },
    zh: {
      "brand.subtitle": "本地只读运维视图",
      "meta.inventory": "持久化表记录数",
      "list.heading": "工作列表",
      "action.refresh": "刷新", "action.pause": "暂停轮询",
      "action.resume": "恢复轮询", "action.retry": "重试",
      "action.loadMore": "加载更多事件", "action.reload": "重新加载",
      "filter.search": "按编号或负责人搜索", "filter.allStatuses": "全部状态",
      "tile.openWorks": "进行中的工作",
      "tile.openWorks.desc": "尚未关闭的工作",
      "tile.closedSucceeded": "已关闭 · 成功",
      "tile.closedSucceeded.desc": "结果为成功并已关闭的工作",
      "tile.closedCancelled": "已关闭 · 已取消",
      "tile.closedCancelled.desc": "结果为取消并已关闭的工作",
      "tile.uncertainOps": "不确定的操作",
      "tile.uncertainOps.desc": "已派出或结果未知的操作",
      "tile.pendingEvidence": "待验证证据",
      "tile.pendingEvidence.desc": "等待验证的证据",
      "list.loading": "正在加载工作…", "list.empty": "此存储中还没有工作。",
      "list.noMatch": "没有符合当前筛选条件的工作。",
      "list.showing": "共 {total} 项工作中的 {shown} 项",
      "list.capped": "（已加载前 200 项）",
      "meta.schema": "schema {version}",
      "meta.sampledAt": "采样时间 {time} —— 观察时间，不是业务事件时间",
      "meta.pollPaused": "轮询已暂停",
      "banner.disconnected": "与本地 UI 服务的连接已断开。页面会持续重试，请检查 ui 进程。",
      "detail.placeholder": "选择一项工作以查看其持久历史。",
      "detail.placeholderHint": "用 ↑/↓ 在列表中移动，回车键选中，或直接点击下方卡片。",
      "detail.guideTitle": "当前存储中的工作速览 —— 点击即可查看",
      "detail.loading": "正在加载工作…",
      "detail.gone": "此工作已不在存储中。",
      "detail.error": "无法加载此工作。",
      "tab.overview": "概览", "tab.requirements": "要求",
      "tab.evidence": "证据", "tab.operations": "操作",
      "tab.decisions": "决策", "tab.events": "事件",
      "tab.documents": "文档",
      "sec.lifecycle": "生命周期与归属",
      "sec.contract": "契约与版本绑定",
      "kpi.requirements": "{satisfied}/{total} 已满足",
      "kpi.requirementsSub": "当前契约义务项",
      "kpi.evidence": "{verified}/{total} 已验证",
      "kpi.evidenceSub": "已记录证明材料",
      "kpi.operations": "{total} 项外部操作",
      "kpi.operationsSub": "最新状态：{latest}",
      "kpi.decisions": "{total} 条命令回执",
      "kpi.decisionsSub": "{accepted} 接纳 · {rejected} 拒绝",
      "demo.label": "演示场景说明",
      "demo.wait-1.short": "等待 E05 特别审批 · 证据待核验",
      "demo.wait-1.long": "财务已提交审批证据但尚未完成核验；工作在 E05 规则上保持持久等待，且保留了此前被拒绝的提议决策回执。",
      "demo.uncertain-1.short": "外部效果已提交 · 权威查询不可用",
      "demo.uncertain-1.long": "外部 OA 已受理但在返回响应前超时，且后续权威查询暂不可用，升级为 needs_attention（外部系统中的真实申请被完整保留）。",
      "demo.transfer-1.short": "负责人移交 delegate · 原意图重入成功",
      "demo.transfer-1.long": "所有权从 agent 移交至 delegate 后原准备意图失效；新负责人重新提议同一逻辑操作并完成外部确认。",
      "demo.succeed-1.short": "证据核验齐备 · 正常验收关闭",
      "demo.succeed-1.long": "所有策略要求均由已核验证据满足，外部 OA 受理确认完成，工作以 succeeded 结果正式关闭。",
      "demo.cancel-1.short": "对账确认外部效果后取消 · 保留真实效果",
      "demo.cancel-1.long": "结果未知的提交先经对账确认为已生效，随后执行取消闭环——显式确认并保留外部已生效记录，绝不伪造撤销。",
      "f.status": "状态", "f.stateVersion": "状态版本", "f.owner": "负责人",
      "f.noOwner": "历史工作 —— 未记录负责人", "f.outcome": "结果",
      "f.policy": "契约策略", "f.policyRevision": "契约版本号",
      "f.goal": "目标", "f.planRevision": "计划版本号",
      "f.documentRevision": "文档版本号", "f.documentDigest": "文档摘要",
      "f.waits": "等待", "f.noWaits": "未注册任何等待。",
      "f.waitId": "等待", "f.waitRequirement": "关联要求", "f.waitOwner": "负责人",
      "f.waitStatus": "状态", "f.waitDeadline": "截止时间（epoch）",
      "f.cancellation": "取消", "f.cancellationNone": "未记录取消。",
      "f.requestedBy": "申请人", "f.reason": "原因",
      "cancel.banner": "{actor} 申请取消：{reason}",
      "cancel.ack": "已关闭并取消 —— 已确认的外部效果被如实记录保留，并未被撤销：",
      "cancel.ackNone": "已关闭并取消 —— 没有已确认的外部效果。",
      "revoke.title": "已关闭工作上的被撤销证据",
      "revoke.body": "历史关闭及其结果保持原记录不变 —— 本次更正不会重新打开或改写它们。被撤销的证据仅改变其当前状态：不再作为当前要求的有效证明。",
      "revoke.cited": "完成记录引用了 {count} 个现已撤销的证据编号：",
      "revoke.records": "存储记录：",
      "req.note": "这里是当前契约的要求。决策页中的历史决策可能带有其决策当时记录的旧阻碍项。",
      "req.id": "要求", "req.rule": "规则", "req.subject": "主体",
      "req.applicability": "适用性", "req.fulfillment": "满足情况",
      "req.explanation": "说明", "req.none": "未记录任何要求。",
      "evd.note": "状态是该证据记录的存储状态，不是独立的来源认证声明。",
      "evd.source": "来源", "evd.eventId": "来源事件", "evd.kind": "类型",
      "evd.status": "状态", "evd.data": "数据（存储原文）",
      "evd.none": "此工作未记录证据。",
      "ops.capability": "能力", "ops.actor": "执行者", "ops.status": "状态",
      "ops.dispatchState": "派出状态", "ops.reason": "原因",
      "ops.externalId": "外部编号", "ops.businessKey": "业务键",
      "ops.digest": "文档摘要", "ops.planRevision": "计划版本号",
      "ops.contractRevision": "契约版本号", "ops.attempts": "尝试",
      "ops.attemptsNone": "无尝试", "ops.document": "操作文档（存储原文）",
      "ops.none": "此工作未记录操作。",
      "dec.note": "持久化的命令回执是对决策的确认，不是外部效果。其阻碍项在决策当时为真，与当前要求相互独立。",
      "dec.actor": "执行者", "dec.command": "命令", "dec.decision": "决策",
      "dec.code": "代码", "dec.version": "状态版本", "dec.blockers": "阻碍项",
      "dec.receipt": "回执（存储原文）", "dec.none": "此工作没有持久化的命令回执。",
      "evt.seq": "序号", "evt.version": "版本", "evt.type": "类型",
      "evt.body": "内容（存储原文）", "evt.none": "此工作未记录事件。",
      "doc.note": "按原文渲染的存储 JSON 文本；超出 JavaScript 安全范围的整数被精确保留。",
      "doc.document": "文档（存储原文）", "doc.plan": "计划（存储原文）",
      "doc.completion": "完成 / 关闭记录（存储原文）",
      "doc.absent": "未记录",
      "footer.keys": "↑/↓ 列表 · 回车选中 · ←/→ 切换页签 · / 搜索",
      "footer.readonly": "面向持久记录的只读本地查看器。环回绑定是便利性设计，不是认证。"
    }
  };

  var DEMO_SCENARIO_IDS = {
    "wait-1": true,
    "uncertain-1": true,
    "transfer-1": true,
    "succeed-1": true,
    "cancel-1": true
  };

  var POLL_INTERVAL_MS = 5000;
  var WORKS_PAGE_LIMIT = 200;
  var EVENTS_PAGE_LIMIT = 50;
  var TABS = ["overview", "requirements", "evidence", "operations",
              "decisions", "events", "documents"];

  var state = {
    lang: (navigator.language || "en").toLowerCase().indexOf("zh") === 0 ? "zh" : "en",
    paused: false,
    pollTimer: null,
    refreshEpoch: 0,
    detailEpoch: 0,
    summary: null,
    works: [],
    total: 0,
    selectedId: null,
    detail: null,
    detailForId: null,
    detailJson: "",
    worksJson: "",
    listError: false,
    activeTab: "overview",
    filterText: "",
    filterStatus: "",
    events: { loadedFor: null, after: "0", hasMore: false, rows: [] },
    loadedOnce: false
  };

  function t(key, params) {
    var text = (I18N[state.lang] && I18N[state.lang][key]) || I18N.en[key] || key;
    if (params) {
      Object.keys(params).forEach(function (name) {
        text = text.split("{" + name + "}").join(String(params[name]));
      });
    }
    return text;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function textOrDash(value) {
    return (value === undefined || value === null || value === "") ? "—" : String(value);
  }

  function chipClass(prefix, value) {
    return "chip " + prefix + String(value === undefined || value === null
      ? "" : value).replace(/[^A-Za-z0-9_-]/g, "");
  }

  function demoShort(workId) {
    return DEMO_SCENARIO_IDS[workId] ? t("demo." + workId + ".short") : "";
  }

  function demoLong(workId) {
    return DEMO_SCENARIO_IDS[workId] ? t("demo." + workId + ".long") : "";
  }

  function ApiError(code, message) {
    this.code = code; this.message = message;
  }
  ApiError.prototype = Object.create(Error.prototype);

  function fetchJSON(path) {
    return fetch(path, { headers: { "Accept": "application/json" } })
      .then(function (response) {
        if (!response.ok) {
          return response.json().catch(function () { return null; })
            .then(function (body) {
              var detail = body && body.error ? body.error : null;
              throw new ApiError(detail ? detail.code : "HTTP_" + response.status,
                                 detail ? detail.message : ("HTTP " + response.status));
            });
        }
        /* Parses the top-level response envelope only; *_raw fields inside it
           stay strings and are never re-parsed anywhere in this app. */
        return response.json();
      });
  }

  /* ---------- i18n ---------- */

  function applyI18n() {
    document.documentElement.lang = state.lang;
    var nodes = document.querySelectorAll("[data-i18n]");
    Array.prototype.forEach.call(nodes, function (node) {
      node.textContent = t(node.getAttribute("data-i18n"));
    });
    var inputs = document.querySelectorAll("[data-i18n-placeholder]");
    Array.prototype.forEach.call(inputs, function (node) {
      node.placeholder = t(node.getAttribute("data-i18n-placeholder"));
    });
    document.getElementById("lang-toggle").textContent = state.lang === "en" ? "中文" : "EN";
    document.getElementById("poll-toggle").textContent =
      t(state.paused ? "action.resume" : "action.pause");
    renderAll();
  }

  /* ---------- summary tiles and counts ---------- */

  function tile(labelKey, descKey, value) {
    var tileNode = el("div", "tile");
    tileNode.appendChild(el("div", "tile-value", value));
    tileNode.appendChild(el("div", "tile-label", t(labelKey)));
    tileNode.appendChild(el("p", "tile-desc", t(descKey)));
    return tileNode;
  }

  function renderTiles() {
    var box = document.getElementById("tiles");
    while (box.firstChild) { box.removeChild(box.firstChild); }
    var summary = state.summary;
    if (!summary) { return; }
    var statuses = summary.work_statuses || {};
    var outcomes = summary.closed_outcomes || {};
    var operations = summary.operation_statuses || {};
    var evidence = summary.evidence_statuses || {};
    var total = Number(summary.counts && summary.counts.works !== undefined
      ? summary.counts.works : 0) || 0;
    var closed = Number(statuses.closed || 0);
    var open = total - closed;
    box.appendChild(tile("tile.openWorks", "tile.openWorks.desc", String(open)));
    box.appendChild(tile("tile.closedSucceeded", "tile.closedSucceeded.desc",
                         String(outcomes.succeeded || 0)));
    box.appendChild(tile("tile.closedCancelled", "tile.closedCancelled.desc",
                         String(outcomes.cancelled || 0)));
    box.appendChild(tile("tile.uncertainOps", "tile.uncertainOps.desc",
                         String((operations.dispatched || 0) + (operations.outcome_unknown || 0))));
    box.appendChild(tile("tile.pendingEvidence", "tile.pendingEvidence.desc",
                         String(evidence.pending_verification || 0)));
  }

  function renderCounts() {
    var box = document.getElementById("counts");
    while (box.firstChild) { box.removeChild(box.firstChild); }
    var counts = state.summary && state.summary.counts;
    if (!counts) { return; }
    Object.keys(counts).sort().forEach(function (key) {
      box.appendChild(el("span", "count-chip", key + ": " + counts[key]));
    });
  }

  function renderStoreMeta() {
    var summary = state.summary;
    document.getElementById("store-source").textContent =
      summary ? textOrDash(summary.source) : "";
    document.getElementById("store-source").title =
      summary ? String(summary.source || "") : "";
    document.getElementById("store-schema").textContent = summary
      ? t("meta.schema", { version: textOrDash(summary.schema_version) }) : "";
    document.getElementById("sampled-at").textContent = summary
      ? t("meta.sampledAt", { time: new Date().toLocaleTimeString() }) : "";
  }

  /* ---------- work list & placeholder scenario guide ---------- */

  function visibleWorks() {
    var needle = state.filterText.trim().toLowerCase();
    return state.works.filter(function (work) {
      if (state.filterStatus && work.status !== state.filterStatus) { return false; }
      if (!needle) { return true; }
      var owner = work.owner === undefined || work.owner === null ? "" : String(work.owner);
      return (String(work.id).toLowerCase().indexOf(needle) !== -1
              || owner.toLowerCase().indexOf(needle) !== -1);
    });
  }

  function renderPlaceholderGuide() {
    var guide = document.getElementById("placeholder-guide");
    if (!guide) { return; }
    while (guide.firstChild) { guide.removeChild(guide.firstChild); }
    if (!state.works.length) { return; }
    guide.appendChild(el("p", "guide-heading", t("detail.guideTitle")));
    var grid = el("div", "guide-grid");
    state.works.slice(0, 6).forEach(function (work) {
      var card = document.createElement("button");
      card.type = "button";
      card.className = "guide-card";
      var head = el("div", "guide-card-head");
      head.appendChild(el("span", "work-id", work.id));
      head.appendChild(el("span", chipClass("chip-st-", work.status), work.status));
      card.appendChild(head);
      var descText = demoShort(work.id);
      if (descText) {
        card.appendChild(el("p", "guide-card-desc", descText));
      }
      var owner = work.owner === undefined || work.owner === null
        ? t("f.noOwner") : work.owner;
      card.appendChild(el("span", "guide-card-meta",
        owner + (work.outcome ? " · " + work.outcome : "") + " · v" + work.state_version));
      card.addEventListener("click", function () { selectWork(work.id); });
      grid.appendChild(card);
    });
    guide.appendChild(grid);
  }

  function renderList() {
    renderFilterOptions();
    renderListItems();
    renderPlaceholderGuide();
  }

  function renderListItems() {
    var box = document.getElementById("work-list");
    var statusLine = document.getElementById("list-status");
    /* Remember list focus across the rebuild so a poll refresh never
       interrupts keyboard navigation. */
    var focusId = document.activeElement && document.activeElement.dataset
      && document.activeElement.dataset.workId;
    while (box.firstChild) { box.removeChild(box.firstChild); }
    if (!state.loadedOnce) {
      statusLine.textContent = state.listError
        ? t("detail.error") : t("list.loading");
      return;
    }
    var shown = visibleWorks();
    if (!state.works.length) {
      statusLine.textContent = state.listError
        ? t("detail.error") : t("list.empty");
      return;
    }
    shown.forEach(function (work) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "work-item";
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", work.id === state.selectedId ? "true" : "false");
      item.dataset.workId = work.id;
      var row = el("div", "row");
      row.appendChild(el("span", "work-id", work.id));
      row.appendChild(el("span", chipClass("chip-st-", work.status), work.status));
      item.appendChild(row);
      var scenario = demoShort(work.id);
      if (scenario) {
        item.appendChild(el("div", "work-scenario", scenario));
      }
      var sub = el("div", "work-sub");
      var owner = work.owner === undefined || work.owner === null
        ? t("f.noOwner") : work.owner;
      sub.textContent = owner + (work.outcome ? " · " + work.outcome : "")
        + " · v" + work.state_version;
      item.appendChild(sub);
      item.addEventListener("click", function () { selectWork(work.id); });
      box.appendChild(item);
    });
    var text = t("list.showing", { shown: shown.length, total: state.total });
    if (state.total > state.works.length) { text += t("list.capped"); }
    statusLine.textContent = state.works.length && !shown.length
      ? t("list.noMatch") : text;
    if (focusId) {
      Array.prototype.forEach.call(
        box.querySelectorAll(".work-item"), function (item) {
          if (item.dataset.workId === focusId) { item.focus(); }
        });
    }
  }

  function renderFilterOptions() {
    var select = document.getElementById("status-filter");
    /* Never rebuild the dropdown while the user is interacting with it. */
    if (document.activeElement === select) { return; }
    var current = state.filterStatus;
    while (select.firstChild) { select.removeChild(select.firstChild); }
    var statuses = {};
    state.works.forEach(function (work) { statuses[work.status] = true; });
    var summaryStatuses = (state.summary && state.summary.work_statuses) || {};
    Object.keys(summaryStatuses).forEach(function (name) {
      statuses[name] = true;
    });
    var all = el("option", "", t("filter.allStatuses"));
    all.value = "";
    select.appendChild(all);
    Object.keys(statuses).sort().forEach(function (name) {
      var option = el("option", "", name + " (" + (summaryStatuses[name] || "–") + ")");
      option.value = name;
      select.appendChild(option);
    });
    select.value = current;
    if (select.value !== current) { select.value = ""; state.filterStatus = ""; }
  }

  /* ---------- detail ---------- */

  function detailRegion(name) {
    return document.getElementById("detail-" + name);
  }

  function showDetailRegion(name) {
    ["placeholder", "loading", "error", "body"].forEach(function (region) {
      detailRegion(region).classList.toggle("hidden", region !== name);
    });
  }

  function selectWork(workId) {
    state.selectedId = workId;
    state.activeTab = "overview";
    resetEvents(workId);
    Array.prototype.forEach.call(
      document.querySelectorAll("#work-list .work-item"), function (item) {
        item.setAttribute("aria-selected", item.dataset.workId === workId ? "true" : "false");
      });
    loadDetail();
  }

  function resetEvents(workId) {
    state.events = { loadedFor: null, after: "0", hasMore: false,
                     rows: [], error: false, json: "" };
  }

  function loadDetail() {
    var workId = state.selectedId;
    if (!workId) { return; }
    var token = ++state.detailEpoch;
    if (state.detailForId !== workId) { showDetailRegion("loading"); }
    fetchJSON("/api/work?id=" + encodeURIComponent(workId))
      .then(function (payload) {
        if (token !== state.detailEpoch || state.selectedId !== workId) { return; }
        var serialized = JSON.stringify(payload);
        if (state.detailForId !== workId || serialized !== state.detailJson) {
          state.detail = payload;
          state.detailJson = serialized;
          state.detailForId = workId;
          renderDetail();
        }
        /* A poll refreshes the open event timeline only while it still fits
           in one page; a paginated reading position is left untouched. */
        if (state.activeTab === "events" && state.events.loadedFor === workId
            && !state.events.hasMore && !state.events.error) {
          loadEvents(true);
        }
        clearDisconnected();
      })
      .catch(function (error) {
        if (token !== state.detailEpoch || state.selectedId !== workId) { return; }
        state.detail = null;
        state.detailForId = null;
        state.detailJson = "";
        if (error instanceof ApiError && error.code === "UNKNOWN_WORK") {
          detailRegion("error-text").textContent = t("detail.gone");
        } else if (!(error instanceof ApiError)) {
          markDisconnected();
          detailRegion("error-text").textContent = t("detail.error");
        } else {
          detailRegion("error-text").textContent =
            t("detail.error") + " (" + error.code + ")";
        }
        showDetailRegion("error");
      });
  }

  function fieldList(pairs) {
    var list = el("dl", "fields");
    pairs.forEach(function (pair) {
      list.appendChild(el("dt", "", pair[0]));
      var dd = el("dd");
      if (pair[2] === "mono") { dd.className = "mono"; }
      dd.textContent = pair[1];
      list.appendChild(dd);
    });
    return list;
  }

  function rawBlock(title, rawText) {
    var block = el("details", "raw-block");
    block.appendChild(el("summary", "", title));
    var pre = el("pre", "raw");
    pre.textContent = rawText;   /* exact stored text, never parsed */
    block.appendChild(pre);
    return block;
  }

  function dataTable(headers, rows) {
    var wrap = el("div", "table-wrap");
    var table = el("table", "data");
    var headRow = el("tr");
    headers.forEach(function (header) { headRow.appendChild(el("th", "", header)); });
    var thead = el("thead"); thead.appendChild(headRow); table.appendChild(thead);
    var tbody = el("tbody");
    rows.forEach(function (row) {
      var tr = el("tr");
      row.forEach(function (cell) {
        var td = el("td");
        if (cell && cell.chip) {
          td.appendChild(el("span", chipClass(cell.chipPrefix || "chip-st-", cell.chip),
                            cell.text));
        } else if (cell && cell.mono) {
          td.appendChild(el("span", "mono", cell.text));
        } else {
          td.textContent = cell === undefined || cell === null ? "—" : String(cell);
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function kpiButton(tabId, label, valueText, subText) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "kpi-card";
    btn.appendChild(el("span", "kpi-label", label));
    btn.appendChild(el("span", "kpi-val", valueText));
    btn.appendChild(el("span", "kpi-sub", subText));
    btn.addEventListener("click", function () { activateTab(tabId); });
    return btn;
  }

  function renderOverviewKpis(payload) {
    var work = payload.work;
    var reqs = (work && work.requirements) || [];
    var satisfied = reqs.filter(function (r) {
      return r.fulfillment === "satisfied";
    }).length;
    var evd = payload.evidence || [];
    var verified = evd.filter(function (e) {
      return e.status === "verified";
    }).length;
    var ops = payload.operations || [];
    var latestOp = ops.length ? textOrDash(ops[ops.length - 1].status) : "—";
    var cmds = payload.commands || [];
    var accepted = cmds.filter(function (c) {
      return c.decision === "accepted";
    }).length;
    var rejected = cmds.filter(function (c) {
      return c.decision === "rejected";
    }).length;

    var strip = el("div", "overview-kpis");
    strip.appendChild(kpiButton(
      "requirements",
      t("tab.requirements"),
      t("kpi.requirements", { satisfied: satisfied, total: reqs.length }),
      t("kpi.requirementsSub")
    ));
    strip.appendChild(kpiButton(
      "evidence",
      t("tab.evidence"),
      t("kpi.evidence", { verified: verified, total: evd.length }),
      t("kpi.evidenceSub")
    ));
    strip.appendChild(kpiButton(
      "operations",
      t("tab.operations"),
      t("kpi.operations", { total: ops.length }),
      t("kpi.operationsSub", { latest: latestOp })
    ));
    strip.appendChild(kpiButton(
      "decisions",
      t("tab.decisions"),
      t("kpi.decisions", { total: cmds.length }),
      t("kpi.decisionsSub", { accepted: accepted, rejected: rejected })
    ));
    return strip;
  }

  function renderOverview(work, payload) {
    var panel = el("div");
    if (payload) {
      panel.appendChild(renderOverviewKpis(payload));
    }
    var contract = work.contract;
    var grid = el("div", "overview-grid");

    var lifeCard = el("div", "overview-section-card");
    lifeCard.appendChild(el("h3", "", t("sec.lifecycle")));
    lifeCard.appendChild(fieldList([
      [t("f.status"), textOrDash(work.status)],
      [t("f.stateVersion"), textOrDash(work.state_version)],
      [t("f.owner"), work.owner === undefined || work.owner === null
        ? t("f.noOwner") : work.owner],
      [t("f.outcome"), textOrDash(work.outcome)]
    ]));
    grid.appendChild(lifeCard);

    var contractCard = el("div", "overview-section-card");
    contractCard.appendChild(el("h3", "", t("sec.contract")));
    contractCard.appendChild(fieldList([
      [t("f.policy"), contract
        ? contract.policy_id + " " + contract.policy_version : "—"],
      [t("f.policyRevision"), contract ? textOrDash(contract.revision) : "—"],
      [t("f.goal"), contract ? textOrDash(contract.goal) : "—"],
      [t("f.planRevision"), textOrDash(work.plan_revision)],
      [t("f.documentRevision"), textOrDash(work.document_revision)],
      [t("f.documentDigest"), textOrDash(work.document_digest), "mono"]
    ]));
    grid.appendChild(contractCard);

    panel.appendChild(grid);

    panel.appendChild(el("h3", "", t("f.waits")));
    if (work.waits && work.waits.length) {
      panel.appendChild(dataTable(
        [t("f.waitId"), t("f.waitRequirement"), t("f.waitOwner"),
         t("f.waitStatus"), t("f.waitDeadline")],
        work.waits.map(function (wait) {
          return [ { mono: true, text: wait.id }, wait.requirement_id, wait.owner,
                   { chip: wait.status, text: wait.status },
                   { mono: true, text: textOrDash(wait.deadline) } ];
        })));
    } else {
      panel.appendChild(el("p", "note", t("f.noWaits")));
    }
    panel.appendChild(el("h3", "", t("f.cancellation")));
    if (work.cancellation) {
      panel.appendChild(el("p", "note", t("f.requestedBy") + ": "
        + work.cancellation.requested_by + " · " + t("f.reason") + ": "
        + work.cancellation.reason));
    } else {
      panel.appendChild(el("p", "note", t("f.cancellationNone")));
    }
    return panel;
  }

  /* The closure record itself is only available as exact stored text
     (completion_raw, Documents tab; never parsed here). The retained-effect
     note below is derived from the STRUCTURED operations fields the API
     provides: a cancelled closure acknowledges exactly the operations whose
     outcome is confirmed_succeeded with an external effect. */
  function renderCancellationBanner(work, operations) {
    if (!work.cancellation && work.outcome !== "cancelled") { return null; }
    var banner = el("div", "cancel-banner");
    if (work.cancellation) {
      banner.appendChild(el("div", "",
        t("cancel.banner", { actor: work.cancellation.requested_by,
                             reason: work.cancellation.reason })));
    }
    if (work.outcome === "cancelled") {
      var confirmed = (operations || []).filter(function (operation) {
        return operation.status === "confirmed_succeeded"
          && operation.external_id !== undefined && operation.external_id !== null;
      });
      var ack = el("div", "cancel-ack", confirmed.length
        ? t("cancel.ack") : t("cancel.ackNone"));
      confirmed.forEach(function (operation) {
        ack.appendChild(el("div", "mono", operation.id + " → "
          + operation.external_id));
      });
      banner.appendChild(ack);
    }
    return banner;
  }

  /* D37 closed-work correction notice. Derived ONLY from the structured
     revoked_evidence / completion_revoked_evidence_ids DTO fields; the exact
     completion text stays in completion_raw (Documents tab) and is never
     parsed here. Shown for closed works only; the citation count appears
     only when the API actually derived cited revoked ids — cancellation
     completions acknowledge operations and never fabricate citations. */
  function renderRevokedNotice(payload) {
    var work = payload.work;
    var revoked = payload.revoked_evidence;
    if (!work || work.status !== "closed"
        || !Array.isArray(revoked) || !revoked.length) {
      return null;
    }
    var box = el("div", "revoked-notice");
    box.appendChild(el("div", "revoked-notice-title", t("revoke.title")));
    box.appendChild(el("div", "revoked-notice-body", t("revoke.body")));
    var cited = payload.completion_revoked_evidence_ids;
    if (Array.isArray(cited) && cited.length) {
      var line = el("div", "revoked-notice-cited",
                    t("revoke.cited", { count: cited.length }));
      cited.forEach(function (id) {
        line.appendChild(el("div", "mono", String(id)));
      });
      box.appendChild(line);
    }
    var actions = el("div", "revoked-notice-actions");
    actions.appendChild(el("span", "revoked-notice-hint", t("revoke.records")));
    ["evidence", "events"].forEach(function (tabId) {
      var button = el("button", "revoked-notice-link", t("tab." + tabId));
      button.type = "button";
      button.addEventListener("click", function () { activateTab(tabId); });
      actions.appendChild(button);
    });
    box.appendChild(actions);
    return box;
  }

  function renderScenarioBanner(work) {
    var text = demoLong(work.id);
    if (!text) { return null; }
    var box = el("div", "scenario-banner");
    var label = el("strong", "", t("demo.label") + ": ");
    box.appendChild(label);
    box.appendChild(document.createTextNode(text));
    return box;
  }

  function renderRequirements(work) {
    var panel = el("div");
    panel.appendChild(el("p", "note", t("req.note")));
    if (!work.requirements || !work.requirements.length) {
      panel.appendChild(el("p", "note", t("req.none")));
      return panel;
    }
    panel.appendChild(dataTable(
      [t("req.id"), t("req.rule"), t("req.subject"), t("req.applicability"),
       t("req.fulfillment"), t("req.explanation")],
      work.requirements.map(function (requirement) {
        return [ { mono: true, text: requirement.id }, requirement.rule_id,
                 requirement.subject,
                 { chip: requirement.applicability, text: requirement.applicability },
                 { chip: requirement.fulfillment, text: requirement.fulfillment },
                 requirement.explanation ];
      })));
    return panel;
  }

  function renderEvidence(evidence) {
    var panel = el("div");
    panel.appendChild(el("p", "note", t("evd.note")));
    if (!evidence || !evidence.length) {
      panel.appendChild(el("p", "note", t("evd.none")));
      return panel;
    }
    var stack = el("div", "stack");
    evidence.forEach(function (item) {
      var card = el("div", "card");
      var head = el("div", "card-head");
      head.appendChild(el("span", "mono", item.source));
      head.appendChild(el("span", "", item.kind));
      head.appendChild(el("span", chipClass("chip-st-", item.status), item.status));
      card.appendChild(head);
      var body = el("div", "card-body", t("evd.eventId") + ": " + item.event_id);
      card.appendChild(body);
      if (item.data_raw !== undefined && item.data_raw !== null) {
        card.appendChild(rawBlock(t("evd.data"), item.data_raw));
      }
      stack.appendChild(card);
    });
    panel.appendChild(stack);
    return panel;
  }

  function renderOperations(operations) {
    var panel = el("div");
    if (!operations || !operations.length) {
      panel.appendChild(el("p", "note", t("ops.none")));
      return panel;
    }
    var stack = el("div", "stack");
    operations.forEach(function (operation) {
      var card = el("div", "card");
      var head = el("div", "card-head");
      head.appendChild(el("span", "mono", operation.capability));
      head.appendChild(el("span", chipClass("chip-st-", operation.status), operation.status));
      head.appendChild(el("span", chipClass("chip-st-", operation.dispatch_state),
                          operation.dispatch_state));
      card.appendChild(head);
      var attempts = (operation.attempts || []).map(function (attempt) {
        return attempt.id + ": " + attempt.status;
      }).join(", ");
      card.appendChild(fieldList([
        [t("ops.actor"), textOrDash(operation.actor)],
        [t("ops.reason"), textOrDash(operation.reason)],
        [t("ops.externalId"), textOrDash(operation.external_id)],
        [t("ops.businessKey"), textOrDash(operation.business_key), "mono"],
        [t("ops.digest"), textOrDash(operation.document_digest), "mono"],
        [t("ops.planRevision"), textOrDash(operation.plan_revision)],
        [t("ops.contractRevision"), textOrDash(operation.contract_revision)],
        [t("ops.attempts"), attempts || t("ops.attemptsNone"), "mono"]
      ]));
      if (operation.document_raw !== undefined && operation.document_raw !== null) {
        card.appendChild(rawBlock(t("ops.document"), operation.document_raw));
      }
      stack.appendChild(card);
    });
    panel.appendChild(stack);
    return panel;
  }

  function renderCommands(commands) {
    var panel = el("div");
    panel.appendChild(el("p", "note", t("dec.note")));
    if (!commands || !commands.length) {
      panel.appendChild(el("p", "note", t("dec.none")));
      return panel;
    }
    var stack = el("div", "stack");
    commands.forEach(function (command) {
      var card = el("div", "card");
      var head = el("div", "card-head");
      head.appendChild(el("span", "mono", command.actor + " · " + command.id));
      head.appendChild(el("span", chipClass("chip-decision-", command.decision),
                          command.decision));
      if (command.code) {
        head.appendChild(el("span", chipClass("chip-st-", command.code), command.code));
      }
      card.appendChild(head);
      var version = command.result_state_version !== undefined
        && command.result_state_version !== null
        ? command.result_state_version : command.observed_state_version;
      card.appendChild(fieldList([[t("dec.version"), textOrDash(version)]]));
      if (command.blockers_raw !== undefined && command.blockers_raw !== null) {
        card.appendChild(rawBlock(t("dec.blockers"), command.blockers_raw));
      }
      if (command.receipt_raw !== undefined && command.receipt_raw !== null) {
        card.appendChild(rawBlock(t("dec.receipt"), command.receipt_raw));
      }
      stack.appendChild(card);
    });
    panel.appendChild(stack);
    return panel;
  }

  function renderEventsPanel() {
    var panel = el("div");
    var workId = state.selectedId;
    if (state.events.loadedFor !== workId) {
      if (state.events.error) {
        panel.appendChild(el("p", "note", t("detail.error")));
        var retry = el("button", "load-more", t("action.retry"));
        retry.type = "button";
        retry.addEventListener("click", function () { loadEvents(true); });
        panel.appendChild(retry);
        return panel;
      }
      panel.appendChild(el("p", "note", t("detail.loading")));
      loadEvents(false);
      return panel;
    }
    if (state.events.error) {
      panel.appendChild(el("p", "note", t("detail.error")));
      var retryAfterError = el("button", "load-more", t("action.retry"));
      retryAfterError.type = "button";
      retryAfterError.addEventListener("click", function () { loadEvents(true); });
      panel.appendChild(retryAfterError);
      return panel;
    }
    if (!state.events.rows.length) {
      panel.appendChild(el("p", "note", t("evt.none")));
      return panel;
    }
    var stack = el("div", "stack");
    state.events.rows.forEach(function (event) {
      var card = el("div", "card");
      var head = el("div", "card-head");
      head.appendChild(el("span", "mono", t("evt.seq") + " " + event.seq
        + " · " + t("evt.version") + " " + event.version));
      head.appendChild(el("span", chipClass("chip-st-", "evt"), event.type));
      card.appendChild(head);
      card.appendChild(rawBlock(t("evt.body"), event.body_raw));
      stack.appendChild(card);
    });
    panel.appendChild(stack);
    if (state.events.hasMore) {
      var more = el("button", "load-more", t("action.loadMore"));
      more.type = "button";
      more.addEventListener("click", function () { loadEvents(false, true); });
      panel.appendChild(more);
    }
    return panel;
  }

  function loadEvents(reset, append) {
    var workId = state.selectedId;
    if (!workId) { return; }
    var token = ++state.detailEpoch;
    var after = reset || !append ? "0" : state.events.after;
    fetchJSON("/api/events?work_id=" + encodeURIComponent(workId)
              + "&after=" + encodeURIComponent(after)
              + "&limit=" + EVENTS_PAGE_LIMIT)
      .then(function (payload) {
        if (token !== state.detailEpoch || state.selectedId !== workId) { return; }
        var serialized = JSON.stringify(payload);
        var replacing = reset || !append;
        /* An unchanged first page must not re-render the open detail view
           (and so must not steal focus) on every poll. */
        if (replacing && state.events.loadedFor === workId && !state.events.error
            && serialized === state.events.json) {
          state.events.after = payload.next_after !== undefined
            && payload.next_after !== null ? String(payload.next_after) : "0";
          state.events.hasMore = !!payload.has_more;
          return;
        }
        state.events.loadedFor = workId;
        state.events.error = false;
        state.events.json = serialized;
        state.events.rows = replacing ? payload.events || []
          : state.events.rows.concat(payload.events || []);
        state.events.after = payload.next_after !== undefined
          && payload.next_after !== null ? String(payload.next_after) : "0";
        state.events.hasMore = !!payload.has_more;
        renderDetail();
        clearDisconnected();
      })
      .catch(function (error) {
        if (token !== state.detailEpoch || state.selectedId !== workId) { return; }
        state.events.loadedFor = workId;
        state.events.error = true;
        if (!(error instanceof ApiError)) { markDisconnected(); }
        renderDetail();
      });
  }

  function renderDocuments(work) {
    var panel = el("div");
    panel.appendChild(el("p", "note", t("doc.note")));
    panel.appendChild(rawBlock(t("doc.document"), textOrDash(work.document_raw)));
    panel.appendChild(rawBlock(t("doc.plan"), textOrDash(work.plan_raw)));
    panel.appendChild(rawBlock(t("doc.completion"),
      work.completion_raw === undefined || work.completion_raw === null
        ? t("doc.absent") : work.completion_raw));
    return panel;
  }

  function renderDetail() {
    var payload = state.detail;
    if (!payload || !state.selectedId) { return; }
    var work = payload.work;
    var body = detailRegion("body");
    while (body.firstChild) { body.removeChild(body.firstChild); }

    var head = el("div", "detail-head");
    var headMain = el("div", "detail-head-main");
    headMain.appendChild(el("h2", "detail-title", work.id));
    headMain.appendChild(el("span", chipClass("chip-st-", work.status), work.status));
    if (work.outcome) {
      headMain.appendChild(el("span", chipClass("chip-st-", work.outcome), work.outcome));
    }
    var owner = work.owner === undefined || work.owner === null
      ? t("f.noOwner") : work.owner;
    headMain.appendChild(el("span", "detail-sub", t("f.owner") + ": " + owner
      + " · " + t("f.stateVersion") + ": " + textOrDash(work.state_version)));
    head.appendChild(headMain);
    body.appendChild(head);

    var banner = renderCancellationBanner(work, payload.operations);
    if (banner) { body.appendChild(banner); }

    var revokedNotice = renderRevokedNotice(payload);
    if (revokedNotice) { body.appendChild(revokedNotice); }

    var scenarioBanner = renderScenarioBanner(work);
    if (scenarioBanner) { body.appendChild(scenarioBanner); }

    var tablist = el("div", "tabs");
    tablist.setAttribute("role", "tablist");
    TABS.forEach(function (tabId) {
      var tab = el("button", "tab", t("tab." + tabId));
      tab.type = "button";
      tab.setAttribute("role", "tab");
      tab.dataset.tab = tabId;
      var active = tabId === state.activeTab;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
      tab.addEventListener("click", function () { activateTab(tabId); });
      tablist.appendChild(tab);
    });
    tablist.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") { return; }
      event.preventDefault();
      var index = TABS.indexOf(state.activeTab);
      index = (index + (event.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
      activateTab(TABS[index]);
      /* activateTab rebuilt the detail body, so the tablist in this closure
         is detached. Focus the newly selected tab in the LIVE document, or
         activeElement falls back to body. */
      var tabButton = document.querySelector(
        '#detail-body .tabs [data-tab="' + TABS[index] + '"]');
      if (tabButton) { tabButton.focus(); }
    });
    body.appendChild(tablist);

    var panel = el("div", "tabpanel");
    panel.setAttribute("role", "tabpanel");
    if (state.activeTab === "overview") { panel.appendChild(renderOverview(work, payload)); }
    else if (state.activeTab === "requirements") { panel.appendChild(renderRequirements(work)); }
    else if (state.activeTab === "evidence") { panel.appendChild(renderEvidence(payload.evidence)); }
    else if (state.activeTab === "operations") { panel.appendChild(renderOperations(payload.operations)); }
    else if (state.activeTab === "decisions") { panel.appendChild(renderCommands(payload.commands)); }
    else if (state.activeTab === "events") { panel.appendChild(renderEventsPanel()); }
    else if (state.activeTab === "documents") { panel.appendChild(renderDocuments(work)); }
    body.appendChild(panel);
    showDetailRegion("body");
  }

  function activateTab(tabId) {
    state.activeTab = tabId;
    renderDetail();  /* the events panel loads itself on first render */
  }

  /* ---------- connection state ---------- */

  function markDisconnected(error) {
    var banner = document.getElementById("connection-banner");
    banner.textContent = error instanceof ApiError
      ? t("detail.error") + " (" + error.code + ")"
      : t("banner.disconnected");
    banner.classList.remove("hidden");
  }

  function clearDisconnected() {
    document.getElementById("connection-banner").classList.add("hidden");
  }

  /* ---------- refresh cycle ---------- */

  function refresh() {
    var token = ++state.refreshEpoch;
    fetchJSON("/api/summary")
      .then(function (summary) {
        if (token !== state.refreshEpoch) { return; }
        state.summary = summary;
        renderStoreMeta(); renderTiles(); renderCounts(); renderFilterOptions();
        clearDisconnected();
      })
      .catch(function (error) {
        if (token !== state.refreshEpoch) { return; }
        markDisconnected(error);
      });
    fetchJSON("/api/works?limit=" + WORKS_PAGE_LIMIT + "&offset=0")
      .then(function (payload) {
        if (token !== state.refreshEpoch) { return; }
        var serialized = JSON.stringify(payload);
        state.listError = false;
        /* The very first render must already see loadedOnce: rendering
           before the flag flips shows the loading state forever on a stable
           payload (the unchanged-JSON guard below then skips re-renders). */
        state.loadedOnce = true;
        if (serialized !== state.worksJson) {
          state.works = payload.works || [];
          state.total = Number(payload.total || 0);
          state.worksJson = serialized;
          renderListItems();  /* skipped when unchanged, to keep list focus */
          renderFilterOptions();
          renderPlaceholderGuide();
        }
        clearDisconnected();
      })
      .catch(function (error) {
        if (token !== state.refreshEpoch) { return; }
        state.listError = true;
        renderListItems();
        markDisconnected(error);
      });
    if (state.selectedId) { loadDetail(); }
  }

  function setPaused(paused) {
    state.paused = paused;
    document.getElementById("poll-toggle").textContent =
      t(paused ? "action.resume" : "action.pause");
    document.getElementById("poll-toggle").classList.toggle("paused", paused);
    document.getElementById("poll-state").classList.toggle("hidden", !paused);
    document.getElementById("poll-state").textContent = t("meta.pollPaused");
  }

  /* ---------- wiring ---------- */

  function renderAll() {
    renderStoreMeta(); renderTiles(); renderCounts(); renderList();
    if (state.detail) { renderDetail(); }
  }

  function wire() {
    document.getElementById("lang-toggle").addEventListener("click", function () {
      state.lang = state.lang === "en" ? "zh" : "en";
      applyI18n();
      setPaused(state.paused);
    });
    document.getElementById("refresh").addEventListener("click", function () {
      refresh();
    });
    document.getElementById("poll-toggle").addEventListener("click", function () {
      setPaused(!state.paused);
    });
    document.getElementById("detail-retry").addEventListener("click", function () {
      loadDetail();
    });
    document.getElementById("work-search").addEventListener("input", function (event) {
      state.filterText = event.target.value;
      renderList();
    });
    document.getElementById("status-filter").addEventListener("change", function (event) {
      state.filterStatus = event.target.value;
      renderList();
    });
    var list = document.getElementById("work-list");
    list.addEventListener("keydown", function (event) {
      var items = Array.prototype.slice.call(list.querySelectorAll(".work-item"));
      if (!items.length) { return; }
      var index = items.indexOf(document.activeElement);
      if (event.key === "ArrowDown" || event.key === "ArrowUp"
          || event.key === "Home" || event.key === "End") {
        event.preventDefault();
        var next = 0;
        if (event.key === "ArrowDown") { next = index < 0 ? 0 : Math.min(index + 1, items.length - 1); }
        if (event.key === "ArrowUp") { next = index < 0 ? items.length - 1 : Math.max(index - 1, 0); }
        if (event.key === "Home") { next = 0; }
        if (event.key === "End") { next = items.length - 1; }
        items[next].focus();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) { return; }
      var tag = (document.activeElement && document.activeElement.tagName || "").toLowerCase();
      if (tag === "input" || tag === "select" || tag === "textarea") { return; }
      event.preventDefault();
      document.getElementById("work-search").focus();
    });
    state.pollTimer = window.setInterval(function () {
      if (!state.paused) { refresh(); }
    }, POLL_INTERVAL_MS);
  }

  applyI18n();
  wire();
  refresh();
})();
