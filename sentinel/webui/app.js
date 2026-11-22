"use strict";

const state = {
  report: null,
  status: null,
  history: [],
  filter: "all",
  query: "",
  historyFilter: "all",
  selectedHistory: null,
  control: null,
  actionBusy: false,
  busy: false,
  docs: {},
};

const STATUS = {
  pass: { label: "通过", order: 2 },
  warn: { label: "警告", order: 1 },
  fail: { label: "失败", order: 0 },
  error: { label: "异常", order: 0 },
};

const VIEW_TITLES = {
  overview: "环境概览",
  audit: "审计",
  history: "历史",
  actions: "操作",
  console: "诊断",
  snapshots: "快照",
  profiles: "配置包",
  tutorial: "教程",
  guide: "指南",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value == null || value === "" ? "—" : String(value);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = String(text);
  return node;
}

function formatTime(value) {
  if (!value) return "尚未检测";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: { Accept: "application/json", ...(options.headers || {}) },
    ...options,
  });
  let data = null;
  try {
    data = await response.json();
  } catch (_error) {
    data = null;
  }
  if (!response.ok) {
    const message = data && data.error ? data.error : `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function showLoading(title, detail) {
  $("#loading-title").textContent = title;
  $("#loading-detail").textContent = detail;
  $("#loading").classList.remove("hidden");
}

function hideLoading() {
  $("#loading").classList.add("hidden");
}

let toastTimer = null;
function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.remove("hidden");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), 4200);
}

/* Navigation ---------------------------------------------------------- */
function showView(name, updateHash = true) {
  if (!VIEW_TITLES[name]) name = "overview";
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  setText("page-title", VIEW_TITLES[name]);
  if (updateHash) history.replaceState(null, "", `#${name}`);
  if (name === "tutorial") loadDocs("tutorial");
  if (name === "guide") loadDocs("guide");
  if (name === "snapshots") loadSnapshots();
  if (name === "profiles") loadProfiles();
  if (name === "console") loadConsole();
  if (name === "history") loadHistory();
  if (name === "actions") loadControl();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setupNavigation() {
  $$(".nav-item").forEach((item) => {
    item.addEventListener("click", () => showView(item.dataset.view));
  });
  $$("[data-view-link]").forEach((item) => {
    item.addEventListener("click", () => showView(item.dataset.viewLink));
  });
  const initial = (location.hash || "#overview").replace("#", "");
  showView(initial, false);
}

/* Status --------------------------------------------------------------- */
async function loadStatus() {
  try {
    const status = await fetchJSON("/api/status");
    state.status = status;
    const platformNames = { windows: "Windows", macos: "macOS", linux: "Linux" };
    setText("platform-chip", platformNames[status.platform] || status.platform || "unknown");
    setText("admin-chip", status.admin ? "管理员权限" : "普通权限");
    setText("app-version", `v${status.version || "1.0.0"}`);
    setText("desktop-path", status.desktop_exe || "尚未构建，请先运行 build_desktop_exe.bat");
    setText("console-lock", status.country_lock ? "已开启" : "未开启");
    setText("console-lock-target", status.country_lock ? (status.expected_country || "未填写目标国家") : "可选功能");
    setText(
      "mode-chip",
      status.control_enabled ? "本地控制 · 需确认" : "只读预览"
    );
    const modeChip = $("#mode-chip");
    if (modeChip) modeChip.classList.toggle("chip-preview", Boolean(status.control_enabled));
    const banner = $("#latch-banner");
    banner.classList.toggle("hidden", !status.killswitch_latched);
  } catch (error) {
    toast(`状态读取失败：${error.message}`, true);
  }
}

/* Theme ---------------------------------------------------------------- */
function applyTheme(theme) {
  const normalized = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = normalized;
  document.documentElement.style.colorScheme = normalized;
  setText("theme-toggle", normalized === "dark" ? "浅色模式" : "深色模式");
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  const next = current === "light" ? "dark" : "light";
  try {
    window.localStorage.setItem("sentinel-theme", next);
  } catch (_error) {
    // Private mode or blocked storage: still apply for this page.
  }
  applyTheme(next);
}


/* Audit ---------------------------------------------------------------- */
function riskLevel(score) {
  if (score == null) return { label: "等待检测", cls: "" };
  if (score >= 60) return { label: "高风险", cls: "fail" };
  if (score >= 35) return { label: "中风险", cls: "warn" };
  return { label: "低风险", cls: "pass" };
}

const prefersReducedMotion = () =>
  window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* Roll the score to its new value, then give one elastic tick. */
let scoreAnim = null;
function animateScore(node, target) {
  if (!node) return;
  if (scoreAnim) cancelAnimationFrame(scoreAnim);
  node.classList.remove("score-tick");
  const from = parseInt(node.textContent, 10);
  if (prefersReducedMotion() || !Number.isFinite(from) || from === target) {
    node.textContent = target;
    void node.offsetWidth;
    node.classList.add("score-tick");
    return;
  }
  const start = performance.now();
  const duration = 620;
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    node.textContent = Math.round(from + (target - from) * eased);
    if (t < 1) {
      scoreAnim = requestAnimationFrame(step);
    } else {
      scoreAnim = null;
      void node.offsetWidth;
      node.classList.add("score-tick");
    }
  };
  scoreAnim = requestAnimationFrame(step);
}

function setGauge(score) {
  const wrap = $(".gauge-wrap");
  const normalized = Math.max(0, Math.min(100, Number(score) || 0));
  const color = normalized >= 60 ? "var(--danger)" : normalized >= 35 ? "var(--warn)" : "var(--accent)";
  if (wrap) {
    wrap.style.background = `conic-gradient(${color} ${normalized * 3.6}deg, var(--panel-3) 0)`;
  }
  const scoreNode = document.getElementById("risk-score");
  if (score == null) setText("risk-score", "—");
  else animateScore(scoreNode, normalized);
}

function renderReport(report) {
  state.report = report;
  const score = report.risk_score;
  setGauge(score);
  const level = riskLevel(score);
  const riskBadge = $("#risk-level");
  riskBadge.textContent = level.label;
  riskBadge.className = `badge ${level.cls}`;

  const counts = report.status_counts || {};
  setText("count-pass", counts.pass || 0);
  setText("count-warn", counts.warn || 0);
  setText("count-fail", counts.fail || 0);
  setText("count-error", counts.error || 0);
  // Status rails: width tracks each state's share of the checks.
  const total = (counts.pass || 0) + (counts.warn || 0) + (counts.fail || 0) + (counts.error || 0);
  [["pass", "cp"], ["warn", "cw"], ["fail", "cf"], ["error", "ce"]].forEach(([key, cls]) => {
    const node = document.getElementById(`count-${key}`);
    const metric = node && node.closest(".metric");
    if (!metric) return;
    metric.classList.remove("cp", "cw", "cf", "ce");
    metric.classList.add(cls);
    metric.style.setProperty("--pct", total ? `${((counts[key] || 0) / total) * 100}%` : "0%");
  });
  setText("audit-time", `最近检测：${formatTime(report.finished_at)}`);

  const gate = report.gate || {};
  const gateBox = $("#gate-box");
  gateBox.classList.toggle("allowed", Boolean(gate.allowed));
  gateBox.classList.toggle("blocked", !gate.allowed);
  setText("gate-title", gate.allowed ? "安全启动门禁：允许" : "安全启动门禁：禁止");
  setText("gate-reason", (gate.reasons && gate.reasons.length) ? gate.reasons.slice(0, 3).join("；") : "风险分低于 60，且没有阻断级失败。");

  const egress = report.egress || {};
  setText("egress-source", egress.source || "—");
  setText("egress-ip", egress.ip || "—");
  setText("egress-country", egress.country_code || "—");
  setText("egress-org", egress.org || egress.asn || "—");
  setText("egress-type", egress.ip_type || "—");
  setText("egress-timezone", egress.timezone || "—");
  const a1 = (report.checks || []).find((check) => check.id === "A1");
  setText("system-timezone", a1 && a1.raw ? (a1.raw.iana || a1.raw.native_id || "—") : "—");

  renderTopFindings(report);
  renderAuditTable();
  renderRiskBreakdown(report);
  renderStabilityInsights();
  const totalChecks = (report.checks || []).length;
  setText("top-findings-link", `查看全部 ${totalChecks} 项 →`);
  if (state.selectedHistory) selectHistory(state.selectedHistory, { scroll: false });
}

function renderTopFindings(report) {
  const container = $("#top-findings");
  container.replaceChildren();
  const checks = (report.checks || []).slice().sort((a, b) => (STATUS[a.status]?.order ?? 3) - (STATUS[b.status]?.order ?? 3));
  const important = checks.filter((check) => check.status === "fail" || check.status === "error" || check.status === "warn").slice(0, 6);
  if (!important.length) {
    container.appendChild(el("div", "empty-state", "没有失败或警告项。"));
    return;
  }
  important.forEach((check) => {
    const row = el("div", "finding");
    row.setAttribute("role", "button");
    row.tabIndex = 0;
    row.append(el("span", "finding-id", check.id));
    row.append(el("span", `finding-status ${check.status}`, STATUS[check.status]?.label || check.status));
    const text = el("div");
    text.append(el("div", "finding-title", check.title));
    text.append(el("div", "finding-summary", check.summary));
    row.append(text);
    const open = () => {
      showView("audit");
      window.setTimeout(() => showDetail(check), 80);
    };
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") open();
    });
    container.append(row);
  });
}

function renderAuditTable() {
  const body = $("#audit-table");
  body.replaceChildren();
  if (!state.report) {
    const row = el("tr");
    const cell = el("td", "empty-cell", "还没有审计结果。点击“重新检测”开始。");
    cell.colSpan = 5;
    row.append(cell);
    body.append(row);
    return;
  }
  const checks = (state.report.checks || []).slice().sort((a, b) => {
    const orderDiff = (STATUS[a.status]?.order ?? 3) - (STATUS[b.status]?.order ?? 3);
    if (orderDiff !== 0) return orderDiff;
    return String(a.id).localeCompare(String(b.id), "numeric");
  });
  const query = state.query.trim().toLowerCase();
  const visible = checks.filter((check) => {
    const statusMatch = state.filter === "all" || check.status === state.filter;
    if (!statusMatch) return false;
    if (!query) return true;
    return [check.id, check.title, check.summary, check.explanation]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
  });
  if (!visible.length) {
    const row = el("tr");
    const cell = el("td", "empty-cell", "当前筛选下没有项目。");
    cell.colSpan = 5;
    row.append(cell);
    body.append(row);
    return;
  }
  visible.forEach((check) => {
    const row = el("tr", "audit-row");
    row.append(el("td", "id-cell", check.id));
    const statusCell = el("td");
    statusCell.append(el("span", `status-pill ${check.status}`, STATUS[check.status]?.label || check.status));
    row.append(statusCell);
    row.append(el("td", "", check.weight));
    row.append(el("td", "", check.blocking ? "是" : "否"));
    const summary = el("td", "summary-cell");
    summary.append(document.createTextNode(check.title));
    summary.append(el("small", "", check.summary));
    row.append(summary);
    row.addEventListener("click", () => showDetail(check));
    body.append(row);
  });
}

function showDetail(check) {
  const panel = $("#detail-panel");
  panel.classList.remove("hidden");
  setText("detail-id", `${check.id} · ${check.status_label || STATUS[check.status]?.label || ""}`);
  setText("detail-title", check.title);
  setText("detail-summary", check.summary);
  const evidence = (check.evidence || []).map((line) => `• ${line}`).join("\n");
  setText("detail-evidence", evidence || "（没有证据行）");
  setText("detail-raw", JSON.stringify(check.raw || {}, null, 2));
  setText("detail-explanation", check.explanation || "暂无通俗解释。");
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* Export / print ------------------------------------------------------- */
function downloadBlob(filename, text, mime = "application/json") {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function exportCurrentJSON() {
  if (!state.report) {
    toast("还没有审计结果，请先运行检测。", true);
    return;
  }
  const id = String(state.report.report_id || "current").replace(/[^A-Za-z0-9._-]/g, "-");
  downloadBlob(`sentinel-audit-${id}.json`, JSON.stringify(state.report, null, 2));
  toast("当前审计 JSON 已导出。");
}

function exportHistoryJSON() {
  if (!state.history.length) {
    toast("还没有历史记录。", true);
    return;
  }
  downloadBlob("sentinel-history.json", JSON.stringify({ history: state.history }, null, 2));
  toast("历史 JSON 已导出。");
}

function printReport() {
  if (!state.report) {
    toast("还没有审计结果，请先运行检测。", true);
    return;
  }
  if (!$("#view-audit").classList.contains("active")) showView("audit");
  window.setTimeout(() => window.print(), 120);
}

/* Risk breakdown ------------------------------------------------------- */
const RISK_GROUPS = [
  { label: "时区 / 时间", ids: ["A1", "A2", "A4", "A8", "A19"] },
  { label: "语言环境", ids: ["A3", "A9"] },
  { label: "网络出口", ids: ["A5", "A6", "A7", "A10", "A11", "A12", "A13", "A14", "A20"] },
  { label: "浏览器策略", ids: ["A16", "A17"] },
  { label: "Claude 客户端", ids: ["A18"] },
  { label: "字体 / 本地化", ids: ["A15"] },
];

function renderRiskBreakdown(report) {
  const container = $("#risk-breakdown");
  container.replaceChildren();
  if (!report) {
    container.append(el("div", "empty-state", "运行检测后显示分类贡献。"));
    setText("breakdown-total", "等待检测");
    return;
  }
  const byId = new Map((report.checks || []).map((check) => [check.id, check]));
  const groups = RISK_GROUPS.map((group) => {
    const checks = group.ids.map((id) => byId.get(id)).filter(Boolean);
    const failing = checks.filter((check) => check.status === "fail" || check.status === "error").length;
    const warning = checks.filter((check) => check.status === "warn").length;
    const contribution = checks
      .filter((check) => check.status !== "pass")
      .reduce((sum, check) => sum + (Number(check.weight) || 1), 0);
    return { ...group, checks, failing, warning, contribution };
  });
  const maxContribution = Math.max(1, ...groups.map((group) => group.contribution));
  const totalContribution = groups.reduce((sum, group) => sum + group.contribution, 0);
  groups.forEach((group) => {
    const item = el("div", "breakdown-item");
    const head = el("div", "breakdown-head");
    head.append(el("span", "", group.label));
    head.append(
      el(
        "strong",
        "",
        group.contribution
          ? `${group.failing} 失败 · ${group.warning} 警告 · 权重 ${group.contribution}`
          : "无失败/警告"
      )
    );
    item.append(head);
    const bar = el("div", "breakdown-bar");
    const fill = el("div", `breakdown-fill ${group.failing ? "fail" : group.warning ? "warn" : ""}`);
    fill.style.setProperty("--width", `${(group.contribution / maxContribution) * 100}%`);
    bar.append(fill);
    item.append(bar);
    container.append(item);
  });
  setText("breakdown-total", totalContribution ? `未通过权重 ${totalContribution}` : "全部通过");
}

/* Stability insights --------------------------------------------------- */
function countryChangeCount(entries) {
  let changes = 0;
  let previous = null;
  entries.forEach((entry) => {
    const country = String(entry.country || "").toUpperCase();
    if (!country) return;
    if (previous && country !== previous) changes += 1;
    previous = country;
  });
  return changes;
}

function renderStabilityInsights() {
  const container = $("#stability-insights");
  const label = $("#stability-label");
  const entries = (state.history || []).filter((item) => typeof item.risk_score === "number");
  container.replaceChildren();
  if (!entries.length) {
    label.textContent = "样本不足";
    label.className = "badge";
    container.append(el("div", "empty-state", "至少需要两次历史记录才能观察变化。"));
    return;
  }
  const blocked = entries.filter((entry) => entry.gate_allowed === false).length;
  const changes = countryChangeCount(entries);
  const average = Math.round(entries.reduce((sum, entry) => sum + Number(entry.risk_score), 0) / entries.length);
  const latest = entries[entries.length - 1].risk_score;
  const insufficient = entries.length < 2;
  label.textContent = insufficient ? "样本不足" : blocked > entries.length / 2 || changes > 0 ? "需要关注" : "相对稳定";
  label.className = `badge ${insufficient ? "" : blocked > entries.length / 2 || changes > 0 ? "warn" : "pass"}`;
  const items = [
    ["记录数", entries.length, "含仅本次会话记录"],
    ["门禁阻断", `${blocked} / ${entries.length}`, blocked ? "存在被门禁阻止的检测" : "没有阻断记录"],
    ["国家变化", `${changes} 次`, changes ? "历史出口发生切换" : "出口国家未变化"],
    ["平均风险", `${average}/100`, `最新 ${latest}/100`],
  ];
  items.forEach(([title, value, hint]) => {
    const card = el("div", "stability-item");
    card.append(el("span", "", title));
    card.append(el("strong", "", value));
    card.append(el("small", "", hint));
    container.append(card);
  });
}

/* History page --------------------------------------------------------- */
function historyStatus(entry) {
  return entry.gate_allowed ? "allowed" : "blocked";
}

function renderHistoryPage() {
  const body = $("#history-table");
  const allEntries = (state.history || []).filter((item) => typeof item.risk_score === "number");
  body.replaceChildren();

  const blocked = allEntries.filter((entry) => entry.gate_allowed === false).length;
  const countries = countryChangeCount(allEntries);
  const average = allEntries.length
    ? Math.round(allEntries.reduce((sum, entry) => sum + Number(entry.risk_score), 0) / allEntries.length)
    : null;
  setText("history-count", allEntries.length);
  setText("history-blocked", allEntries.length ? `${blocked} / ${allEntries.length}` : "—");
  setText("history-countries", allEntries.length ? `${countries} 次` : "—");
  setText("history-avg", average == null ? "—" : `${average}/100`);

  const visible = allEntries
    .filter((entry) => state.historyFilter === "all" || historyStatus(entry) === state.historyFilter)
    .slice()
    .reverse();
  if (!visible.length) {
    const row = el("tr");
    const cell = el("td", "empty-cell", allEntries.length ? "当前筛选下没有记录。" : "还没有历史。桌面版或 CLI 完整检测后会积累记录。");
    cell.colSpan = 7;
    row.append(cell);
    body.append(row);
    return;
  }
  visible.forEach((entry) => {
    const row = el("tr", "history-row");
    if (state.selectedHistory && state.selectedHistory.audit_id === entry.audit_id) row.classList.add("active");
    row.append(el("td", "", formatTime(entry.ts)));
    row.append(el("td", "id-cell", `${entry.risk_score}/100`));
    const gate = el("td");
    gate.append(el("span", `status-pill ${entry.gate_allowed ? "pass" : "fail"}`, entry.gate_allowed ? "允许" : "禁止"));
    row.append(gate);
    row.append(el("td", "", entry.country || "—"));
    row.append(el("td", "", (entry.failures || []).length));
    row.append(el("td", "", (entry.warnings || []).length));
    row.append(el("td", "", entry.session_only ? "本次会话" : "已保存"));
    row.addEventListener("click", () => selectHistory(entry));
    body.append(row);
  });
  if (state.selectedHistory) {
    const stillExists = allEntries.some((entry) => entry.audit_id === state.selectedHistory.audit_id);
    if (!stillExists) {
      state.selectedHistory = null;
      $("#history-diff").classList.add("hidden");
    }
  }
}

function statusLabel(status) {
  if (status === "missing") return "缺失";
  return STATUS[status]?.label || status || "—";
}

function renderDiffItem(container, kind, check, oldStatus, newStatus) {
  const item = el("div", `diff-item ${kind}`);
  item.append(el("span", "diff-id", check ? check.id : "?"));
  const text = el("div", "diff-text");
  text.append(document.createTextNode(check ? check.title : "历史检查项"));
  text.append(el("small", "", `${statusLabel(oldStatus)} → ${statusLabel(newStatus)}${check ? ` · ${check.summary}` : ""}`));
  item.append(text);
  container.append(item);
}

function selectHistory(entry, options = {}) {
  state.selectedHistory = entry;
  renderHistoryPage();
  const panel = $("#history-diff");
  panel.classList.remove("hidden");
  setText("history-diff-id", `HISTORY · ${entry.audit_id || "unknown"}`);
  setText("history-diff-title", `${formatTime(entry.ts)} · 风险 ${entry.risk_score}/100`);
  const current = state.report;
  const meta = $("#history-diff-meta");
  const note = $("#history-diff-note");
  meta.replaceChildren();
  const improved = $("#diff-improved");
  const regressed = $("#diff-regressed");
  improved.replaceChildren();
  regressed.replaceChildren();

  const oldStatuses = entry.check_statuses || {};
  if (!current) {
    meta.textContent = "还没有当前审计。请先运行检测，再回来看逐项变化。";
    improved.append(el("span", "subtle", "无"));
    regressed.append(el("span", "subtle", "无"));
    note.textContent = "";
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  const currentChecks = current.checks || [];
  const currentById = new Map(currentChecks.map((check) => [check.id, check]));
  if (!Object.keys(oldStatuses).length) {
    const failed = (entry.failures || []).join(", ") || "无";
    const warned = (entry.warnings || []).join(", ") || "无";
    meta.textContent = `该历史记录没有逐项状态。历史失败：${failed}；历史警告：${warned}。`;
    improved.append(el("span", "subtle", "无法逐项对比"));
    regressed.append(el("span", "subtle", "无法逐项对比"));
    note.textContent = "旧版本历史只保存摘要；新检测会记录 20 项状态，后续记录即可逐项对比。";
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  const improvedItems = [];
  const regressedItems = [];
  const allIds = new Set([...Object.keys(oldStatuses), ...currentById.keys()]);
  allIds.forEach((id) => {
    const check = currentById.get(id);
    const oldStatus = oldStatuses[id];
    const currentStatus = check ? check.status : null;
    if (!oldStatus && check) {
      regressedItems.push({ kind: "added", check, oldStatus: "missing", newStatus: currentStatus });
      return;
    }
    if (oldStatus && !check) {
      regressedItems.push({ kind: "regressed", check: { id, title: "检查项已不在当前报告", summary: "" }, oldStatus, newStatus: "missing" });
      return;
    }
    if (!oldStatus || !currentStatus) return;
    if (oldStatus !== "pass" && currentStatus === "pass") {
      improvedItems.push({ kind: "improved", check, oldStatus, newStatus: currentStatus });
    } else if (oldStatus === "pass" && currentStatus !== "pass") {
      regressedItems.push({ kind: "regressed", check, oldStatus, newStatus: currentStatus });
    } else if (oldStatus !== currentStatus) {
      regressedItems.push({ kind: "regressed", check, oldStatus, newStatus: currentStatus });
    }
  });

  improvedItems.forEach((item) => renderDiffItem(improved, item.kind, item.check, item.oldStatus, item.newStatus));
  regressedItems.forEach((item) => renderDiffItem(regressed, item.kind, item.check, item.oldStatus, item.newStatus));
  if (!improvedItems.length) improved.append(el("span", "subtle", "没有改善项。"));
  if (!regressedItems.length) regressed.append(el("span", "subtle", "没有恶化或新增项。"));
  meta.textContent = `历史风险 ${entry.risk_score}/100 → 当前 ${current.risk_score}/100；历史门禁${entry.gate_allowed ? "允许" : "禁止"}，当前${current.gate && current.gate.allowed ? "允许" : "禁止"}。`;
  note.textContent = "对比只反映两次本地采样之间的状态变化；采样波动、浏览器重启、代理切换都可能改变结果。";
  if (options.scroll !== false) panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadReport() {
  try {
    const data = await fetchJSON("/api/report");
    if (data.report) renderReport(data.report);
    return Boolean(data.report);
  } catch (error) {
    toast(`读取缓存审计失败：${error.message}`, true);
    return false;
  }
}

async function runAudit() {
  if (state.busy) return;
  state.busy = true;
  $("#run-audit").disabled = true;
  $("#audit-refresh").disabled = true;
  showLoading("正在采样真实环境…", "读取出口 IP、DNS、WebRTC、代理/TUN、时区、Node 与浏览器策略，通常需要几秒到几十秒。");
  try {
    const data = await fetchJSON("/api/audit", { method: "POST" });
    renderReport(data.report);
    await loadStatus();
    await loadHistory();
    await loadConsole();
    await loadControl();
    toast(`检测完成：风险分 ${data.report.risk_score}/100。`);
  } catch (error) {
    if (error.status === 409) {
      toast("已有一个检测正在进行，请稍后再试。", true);
    } else {
      toast(`检测失败：${error.message}`, true);
    }
  } finally {
    state.busy = false;
    $("#run-audit").disabled = false;
    $("#audit-refresh").disabled = false;
    hideLoading();
  }
}

/* Snapshots / profiles ------------------------------------------------- */
async function loadSnapshots() {
  try {
    const data = await fetchJSON("/api/snapshots");
    const body = $("#snapshot-table");
    body.replaceChildren();
    if (!data.snapshots || !data.snapshots.length) {
      const row = el("tr");
      const cell = el("td", "empty-cell", "还没有快照。桌面版执行对齐时会自动创建。");
      cell.colSpan = 4;
      row.append(cell);
      body.append(row);
      return;
    }
    data.snapshots.forEach((snapshot) => {
      const row = el("tr");
      row.append(el("td", "id-cell", snapshot.snapshot_id));
      row.append(el("td", "", formatTime(snapshot.created_at)));
      row.append(el("td", "", snapshot.label));
      row.append(el("td", "", (snapshot.modified_items || []).join(", ")));
      body.append(row);
    });
  } catch (error) {
    toast(`快照读取失败：${error.message}`, true);
  }
}

async function loadProfiles() {
  try {
    const data = await fetchJSON("/api/profiles");
    const body = $("#profile-table");
    body.replaceChildren();
    if (!data.profiles || !data.profiles.length) {
      const row = el("tr");
      const cell = el("td", "empty-cell", "还没有环境配置包。");
      cell.colSpan = 5;
      row.append(cell);
      body.append(row);
      return;
    }
    data.profiles.forEach((profile) => {
      const row = el("tr");
      row.append(el("td", "", profile.name || "未命名配置包"));
      row.append(el("td", "", profile.expected_exit_country || "—"));
      row.append(el("td", "", profile.timezone || "—"));
      row.append(el("td", "", profile.proxy_label || "—"));
      row.append(el("td", "", profile.is_current ? "当前" : ""));
      body.append(row);
    });
  } catch (error) {
    toast(`配置包读取失败：${error.message}`, true);
  }
}

/* History and console -------------------------------------------------- */
function renderTrend(history) {
  const entries = (history || []).filter((item) => typeof item.risk_score === "number").slice(-12);
  const line = $("#trend-line");
  const area = $("#trend-area");
  const svg = $("#trend-chart");
  svg.querySelectorAll(".trend-point").forEach((node) => node.remove());
  if (!entries.length) {
    line.setAttribute("points", "");
    area.setAttribute("d", "");
    setText("trend-label", "暂无历史");
    $("#trend-meta").replaceChildren(el("span", "", "运行桌面版检测后开始积累历史。"));
    return;
  }
  const width = 640;
  const height = 100;
  const padX = 18;
  const padY = 12;
  const points = entries.map((item, index) => {
    const x = entries.length === 1 ? width / 2 : padX + (index / (entries.length - 1)) * (width - padX * 2);
    const risk = Math.max(0, Math.min(100, Number(item.risk_score) || 0));
    const y = height - padY - (risk / 100) * (height - padY * 2);
    return { x, y, risk, item };
  });
  line.setAttribute("points", points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" "));
  area.setAttribute(
    "d",
    `M ${points[0].x.toFixed(1)} ${height - padY} ` +
      points.map((point) => `L ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ") +
      ` L ${points[points.length - 1].x.toFixed(1)} ${height - padY} Z`
  );
  points.forEach((point) => {
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", String(point.x));
    circle.setAttribute("cy", String(point.y));
    circle.setAttribute("r", "2.6");
    circle.setAttribute("class", "trend-point");
    svg.append(circle);
  });
  const latest = points[points.length - 1];
  const meta = $("#trend-meta");
  if (entries.length < 2) {
    // A single isolated point reads as a broken chart, not a trend.
    setText("trend-label", "样本不足");
    svg.classList.add("trend-empty");
    meta.replaceChildren(
      el("span", "", `仅有 1 次采样 · 最新 ${latest.risk}/100`),
      el("span", "", "运行桌面版检测后开始积累趋势")
    );
    return;
  }
  svg.classList.remove("trend-empty");
  setText("trend-label", `最近 ${entries.length} 次`);
  const scores = points.map((point) => point.risk);
  meta.replaceChildren(
    el("span", "", `最新 ${latest.risk}/100`),
    el("span", "", `最高 ${Math.max(...scores)} · 最低 ${Math.min(...scores)}`),
    el("span", "", formatTime(latest.item.ts))
  );
}

async function loadHistory() {
  try {
    const data = await fetchJSON("/api/history");
    state.history = data.history || [];
    renderTrend(state.history);
    renderHistoryPage();
    renderStabilityInsights();
    if (state.selectedHistory) {
      const refreshed = state.history.find((entry) => entry.audit_id === state.selectedHistory.audit_id);
      if (refreshed) state.selectedHistory = refreshed;
    } else if (state.report && $("#view-history").classList.contains("active") && state.history.length) {
      // Compare the most recent persisted audit with the current session,
      // rather than opening an empty history page.
      const preferred = state.history.slice().reverse().find((entry) => !entry.session_only) || state.history[state.history.length - 1];
      if (preferred) selectHistory(preferred, { scroll: false });
    }
  } catch (error) {
    toast(`历史读取失败：${error.message}`, true);
  }
}

function renderConsoleEvents(events) {
  const log = $("#console-log");
  log.replaceChildren();
  if (!events || !events.length) {
    log.append(el("div", "console-line muted-line", "等待第一次检测…"));
    return;
  }
  events.forEach((event) => {
    const line = el("div", "console-line");
    const ts = event.ts ? String(event.ts).slice(11, 19) : "--:--:--";
    line.append(el("span", "console-time", ts));
    line.append(el("span", `console-level ${event.level || "info"}`, String(event.level || "info").toUpperCase()));
    line.append(el("span", "console-message", event.message || ""));
    log.append(line);
  });
  log.scrollTop = log.scrollHeight;
}

function renderRecommendations(recommendations) {
  const target = $("#console-recommendations");
  target.replaceChildren();
  if (!recommendations || !recommendations.length) {
    target.append(el("div", "empty-state", "当前没有需要优先处理的建议。"));
    return;
  }
  recommendations.forEach((item, index) => {
    const card = el("div", "recommendation");
    const head = el("div", "rec-head");
    head.append(el("span", "rec-id", `${index + 1}. ${item.id || ""}`));
    head.append(el("span", `status-pill ${item.status || "warn"}`, item.priority === "must_fix" ? "优先处理" : "建议处理"));
    card.append(head);
    card.append(el("div", "rec-action", item.action || item.title || ""));
    if (item.summary) card.append(el("p", "rec-detail", item.summary));
    target.append(card);
  });
}

async function loadConsole() {
  try {
    const data = await fetchJSON("/api/console");
    const report = data.report;
    if (report) {
      setText("console-risk", `${report.risk_score}/100`);
      setText("console-gate", report.gate && report.gate.allowed ? "门禁允许" : "门禁禁止");
      setText("console-country", (report.egress && report.egress.country_code) || "—");
      setText("console-ip", (report.egress && report.egress.ip) || "—");
    } else {
      setText("console-risk", "—");
      setText("console-gate", "等待检测");
      setText("console-country", "—");
      setText("console-ip", "—");
    }
    setText("console-status", data.audit_running ? "running" : "idle");
    renderConsoleEvents(data.events || []);
    renderRecommendations(data.recommendations || []);
    state.consoleSummary = data.summary || "";
  } catch (error) {
    toast(`控制台读取失败：${error.message}`, true);
  }
}

async function copySummary() {
  const text = state.consoleSummary || "尚未生成诊断摘要，请先运行检测。";
  try {
    await navigator.clipboard.writeText(text);
    toast("诊断摘要已复制。");
  } catch (_error) {
    const helper = document.createElement("textarea");
    helper.value = text;
    document.body.append(helper);
    helper.select();
    try {
      document.execCommand("copy");
      toast("诊断摘要已复制。");
    } catch (_fallbackError) {
      toast("当前浏览器不允许写入剪贴板。", true);
    }
    helper.remove();
  }
}

/* Local control / one-click actions ----------------------------------- */
function controlTargetReady() {
  return Boolean(state.control && state.control.control_enabled && state.control.target);
}

function syncActionButtons() {
  const control = state.control;
  const enabled = Boolean(control && control.control_enabled);
  const idle = !state.busy && !state.actionBusy && !(control && (control.action_running || control.audit_running));
  const canAlign = enabled && idle && controlTargetReady();
  const snapshots = (control && control.snapshots) || [];
  const canRestore = enabled && idle && snapshots.length > 0;
  const undoId = control && control.last_alignment_snapshot_id;
  const target = control && control.target;

  const open = $("#open-align-dialog");
  if (open) open.disabled = !canAlign;
  const quick = $("#quick-browser");
  if (quick) quick.disabled = !canAlign;
  const hero = $("#hero-align");
  if (hero) hero.disabled = !canAlign;
  const undo = $("#undo-align");
  if (undo) {
    undo.disabled = !(canRestore && undoId);
    undo.dataset.snapshotId = undoId || "";
  }
  const latest = $("#restore-latest");
  if (latest) latest.disabled = !canRestore;
  const selected = $("#restore-selected");
  if (selected) selected.disabled = !(canRestore && $("#restore-select") && $("#restore-select").value);
  const restoreSelect = $("#restore-select");
  if (restoreSelect) restoreSelect.disabled = !canRestore;

  const readonlyBanner = $("#action-readonly-banner");
  if (readonlyBanner) readonlyBanner.classList.toggle("hidden", enabled);
  const noReport = $("#action-no-report");
  if (noReport) noReport.classList.toggle("hidden", !enabled || Boolean(target));
  setText("action-mode-badge", enabled ? "控制模式" : "只读模式");
  setText("action-admin-badge", !control ? "权限未知" : control.admin ? "管理员" : "普通权限");
}

function applyControl(control) {
  state.control = control || null;
  const target = control && control.target;
  setText("action-country", target ? target.country || "—" : "—");
  setText("action-timezone", target ? target.timezone || "—" : "—");
  setText("action-locale", target ? target.locale || "—" : "—");
  setText("action-accept", target ? target.accept_language || "—" : "—");
  setText(
    "mode-chip",
    control && control.control_enabled ? "本地控制 · 需确认" : "只读预览"
  );
  const modeChip = $("#mode-chip");
  if (modeChip) modeChip.classList.toggle("chip-preview", Boolean(control && control.control_enabled));

  const snapshots = (control && control.snapshots) || [];
  setText("restore-count", `${snapshots.length} 个快照`);
  const select = $("#restore-select");
  if (select) {
    const previous = select.value;
    select.replaceChildren();
    if (!snapshots.length) {
      select.append(new Option("暂无快照", ""));
    } else {
      snapshots.forEach((snapshot) => {
        select.append(
          new Option(
            `${formatTime(snapshot.created_at)} · ${snapshot.label || "未命名"} · ${String(snapshot.snapshot_id).slice(-8)}`,
            snapshot.snapshot_id
          )
        );
      });
      if (previous && snapshots.some((snapshot) => snapshot.snapshot_id === previous)) {
        select.value = previous;
      }
    }
  }
  const hint = $("#restore-hint");
  if (hint) {
    if (!control || !control.control_enabled) {
      hint.textContent = "当前为只读模式，还原已禁用。";
    } else if (!snapshots.length) {
      hint.textContent = "还没有快照；执行一次对齐会自动创建。";
    } else {
      hint.textContent = "快照会保留，不会因为还原而被删除。";
    }
  }
  syncActionButtons();
}

async function loadControl() {
  try {
    const control = await fetchJSON("/api/control");
    applyControl(control);
    return control;
  } catch (error) {
    toast(`控制状态读取失败：${error.message}`, true);
    return null;
  }
}

function renderTargetSummary(target) {
  const container = $("#align-target-summary");
  if (!container) return;
  container.replaceChildren();
  if (!target) {
    container.append(el("div", "", "没有可用的出口/时区目标，请先运行检测。"));
    return;
  }
  [
    ["目标国家/地区", target.country || "—"],
    ["目标时区", target.timezone || "—"],
    ["目标 locale", target.locale || "—"],
    ["Accept-Language", target.accept_language || "—"],
  ].forEach(([label, value]) => {
    const row = el("div");
    row.append(el("strong", "", `${label}：`));
    row.append(document.createTextNode(value));
    container.append(row);
  });
}

function closeAlignDialog() {
  const dialog = $("#align-dialog");
  if (dialog && dialog.open) dialog.close();
}

function openAlignDialog() {
  if (!state.control || !state.control.control_enabled) {
    toast("当前是只读模式，不能执行对齐。", true);
    return;
  }
  if (!state.control.target) {
    toast("没有可用的出口/时区目标，请先运行检测。", true);
    showView("audit");
    return;
  }
  if (state.busy || state.actionBusy || state.control.action_running || state.control.audit_running) {
    toast("当前有操作进行中，请稍后。", true);
    return;
  }
  const target = state.control.target;
  renderTargetSummary(target);
  $("#align-timezone").checked = Boolean(target.timezone_valid);
  $("#align-timezone").disabled = !target.timezone_valid;
  $("#align-language").checked = true;
  $("#align-browser").checked = true;
  $("#align-system-timezone").checked = Boolean(target.system_timezone_available);
  $("#align-system-timezone").disabled = !target.system_timezone_available;
  $("#align-system-row").classList.toggle("disabled", !target.system_timezone_available);
  $("#align-understood").checked = false;
  $("#align-error").classList.add("hidden");
  $("#align-submit").disabled = false;
  const dialog = $("#align-dialog");
  if (dialog && typeof dialog.showModal === "function") dialog.showModal();
}

function alignError(message) {
  const node = $("#align-error");
  node.textContent = message;
  node.classList.remove("hidden");
}

async function controlFetch(path, body) {
  const token = state.control && state.control.token;
  if (!token) throw new Error("控制 token 不可用");
  const response = await fetch(path, {
    method: "POST",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Sentinel-Token": token,
    },
    body: JSON.stringify(body),
  });
  let data = null;
  try {
    data = await response.json();
  } catch (_error) {
    data = null;
  }
  if (!response.ok) {
    const error = new Error((data && data.error) || `HTTP ${response.status}`);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function actionStatusBadge(status) {
  if (status === "verified" || status === "applied") return "pass";
  if (status === "failed") return "fail";
  if (status === "partial" || status === "skipped") return "warn";
  return "";
}

function actionStatusLabel(status) {
  return {
    applied: "已写入",
    verified: "已复检",
    partial: "部分",
    failed: "失败",
    skipped: "跳过",
  }[status] || status || "";
}

function renderActionItems(items) {
  const container = $("#action-items");
  container.replaceChildren();
  (items || []).forEach((item) => {
    const row = el("div", "action-item");
    row.append(el("span", "action-key", item.key || ""));
    row.append(el("span", `status-pill ${actionStatusBadge(item.status)}`, actionStatusLabel(item.status)));
    const detail = el("span", "action-detail");
    detail.append(el("strong", "", item.label || ""));
    if (item.detail) detail.append(document.createTextNode(` — ${item.detail}`));
    row.append(detail);
    container.append(row);
  });
}

function renderActionFailures(failures) {
  const container = $("#action-failures");
  container.replaceChildren();
  (failures || []).forEach((failure) => {
    if (typeof failure === "string") {
      container.append(el("div", "", failure));
      return;
    }
    const row = el("div");
    row.append(el("strong", "", `${failure.item || "未还原项"}：`));
    row.append(document.createTextNode(failure.detail || ""));
    container.append(row);
    if (failure.manual_command) {
      container.append(el("code", "manual-command", failure.manual_command));
    }
  });
}

function renderActionResult(kind, data) {
  const result = data.result || {};
  const panel = $("#action-result");
  panel.classList.remove("hidden");
  const isRestore = kind === "restore";
  const ok = isRestore ? Boolean(result.verified) : Boolean(result.ok);
  const partial = Boolean(result.partial);
  setText("action-result-title", isRestore ? "还原结果" : "对齐结果");
  const badge = $("#action-result-badge");
  badge.className = `badge ${ok ? "pass" : partial ? "warn" : "fail"}`;
  badge.textContent = ok ? "成功" : partial ? "部分完成" : "未完全成功";
  const meta = $("#action-result-meta");
  meta.replaceChildren();
  if (result.snapshot_id) {
    meta.append(el("div", "", `快照：${result.snapshot_id}`));
  }
  if (isRestore) {
    meta.append(el("div", "", `还原项：${(result.restored_items || []).join("、") || "无"}`));
    meta.append(el("div", "", `逐项验证：${result.verified ? "全部匹配" : "存在未匹配或未完成项"}`));
    renderActionItems(
      (result.restored_items || []).map((name, index) => ({
        key: `R${index + 1}`,
        label: name,
        status: "verified",
        detail: "",
      }))
    );
    renderActionFailures(result.failures || []);
  } else {
    meta.append(el("div", "", `总体状态：${result.ok ? "成功" : partial ? "部分完成" : "失败"}`));
    if (result.verification && result.verification.risk_score != null) {
      meta.append(el("div", "", `复检风险：${result.verification.risk_score}/100`));
    }
    renderActionItems(result.items || []);
    renderActionFailures(result.failures || []);
  }
  const undo = $("#action-undo-snapshot");
  if (!isRestore && result.snapshot_id) {
    undo.classList.remove("hidden");
    undo.dataset.snapshotId = result.snapshot_id;
  } else {
    undo.classList.add("hidden");
    undo.dataset.snapshotId = "";
  }
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function runAction(kind, path, body, title) {
  if (state.actionBusy) return;
  state.actionBusy = true;
  syncActionButtons();
  showLoading(title, "正在写入设置并复检；这可能需要几十秒，请不要关闭页面。");
  try {
    const data = await controlFetch(path, body);
    if (data.report) renderReport(data.report);
    await loadStatus();
    await loadHistory();
    await loadConsole();
    await loadSnapshots();
    await loadControl();
    renderActionResult(kind, data);
    toast(kind === "restore" ? "还原流程已完成。" : "对齐流程已完成。");
  } catch (error) {
    toast(`${kind === "restore" ? "还原" : "对齐"}失败：${error.message}`, true);
    if (error.status === 403) {
      await loadControl();
    }
  } finally {
    state.actionBusy = false;
    hideLoading();
    syncActionButtons();
  }
}

function submitAlign() {
  if (!state.control || !state.control.control_enabled) {
    alignError("当前是只读模式。");
    return;
  }
  if (!$("#align-understood").checked) {
    alignError("请先勾选“我理解会修改本机环境设置”。");
    return;
  }
  const body = {
    timezone: Boolean($("#align-timezone").checked),
    language: Boolean($("#align-language").checked),
    browser_policies: Boolean($("#align-browser").checked),
    confirm_system_timezone: Boolean($("#align-system-timezone").checked),
    confirm: true,
  };
  if (!body.timezone && !body.language && !body.browser_policies) {
    alignError("至少选择一个对齐项。");
    return;
  }
  if (body.confirm_system_timezone && !state.control.target.system_timezone_available) {
    alignError("当前环境不允许修改系统时区。");
    return;
  }
  closeAlignDialog();
  runAction("align", "/api/align", body, "正在创建快照并一键对齐…");
}

function quickBrowser() {
  if (!state.control || !state.control.target) {
    toast("请先运行检测。", true);
    return;
  }
  if (!window.confirm("仅写入 Chrome/Edge 的 Accept-Language 与 WebRTC 策略；会先创建快照。继续？")) {
    return;
  }
  runAction(
    "align",
    "/api/align",
    {
      timezone: false,
      language: false,
      browser_policies: true,
      confirm_system_timezone: false,
      confirm: true,
    },
    "正在写入浏览器策略…"
  );
}

function restoreSnapshot(snapshotId, label) {
  if (!snapshotId) {
    toast("没有可还原的快照。", true);
    return;
  }
  const message =
    `将逐项写回快照 ${snapshotId} 的原始值${label ? `（${label}）` : ""}。\n\n` +
    "原本不存在的环境变量会被删除，而不是设为空字符串。还原后会自动复检。继续？";
  if (!window.confirm(message)) return;
  runAction("restore", "/api/restore", { snapshot_id: snapshotId, confirm: true }, "正在还原快照并逐项验证…");
}

function undoLastAlign() {
  const id = state.control && state.control.last_alignment_snapshot_id;
  if (!id) {
    toast("没有可撤销的对齐快照。", true);
    return;
  }
  restoreSnapshot(id, "上次对齐前");
}

function restoreLatest() {
  const snapshot = state.control && state.control.latest_snapshot;
  if (!snapshot) {
    toast("没有可还原的快照。", true);
    return;
  }
  restoreSnapshot(snapshot.snapshot_id, snapshot.label);
}

function restoreSelected() {
  const select = $("#restore-select");
  if (!select || !select.value) {
    toast("请选择要还原的快照。", true);
    return;
  }
  const option = select.options[select.selectedIndex];
  restoreSnapshot(select.value, option ? option.textContent : "");
}

/* Markdown ------------------------------------------------------------- */
function escapeHTML(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function safeURL(url) {
  const value = String(url || "").trim();
  if (/^https?:\/\//i.test(value)) return value;
  if (value.startsWith("#") || value.startsWith("/") || value.startsWith("./") || value.startsWith("../")) return value;
  return null;
}

function inlineMarkdown(text) {
  let out = escapeHTML(text);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label, url) => {
    const safe = safeURL(url);
    if (!safe) return label;
    return `<a href="${escapeHTML(safe)}" target="_blank" rel="noreferrer">${label}</a>`;
  });
  return out;
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const html = [];
  let inCode = false;
  let inList = false;
  const closeList = () => {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  };
  for (const raw of lines) {
    if (raw.trim().startsWith("```")) {
      closeList();
      if (inCode) {
        html.push("</code></pre>");
      } else {
        html.push("<pre><code>");
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) {
      html.push(escapeHTML(raw) + "\n");
      continue;
    }
    const line = raw.trimEnd();
    if (!line.trim()) {
      closeList();
      html.push("");
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    if (line.trim().startsWith("> ")) {
      closeList();
      html.push(`<blockquote><p>${inlineMarkdown(line.trim().slice(2))}</p></blockquote>`);
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(line.replace(/^\s*[-*]\s+/, ""))}</li>`);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      closeList();
      html.push(`<p>${inlineMarkdown(line.trim())}</p>`);
      continue;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  if (inCode) html.push("</code></pre>");
  return html.join("\n");
}

async function loadDocs(name) {
  if (state.docs[name]) return;
  try {
    const data = await fetchJSON(`/api/docs?name=${encodeURIComponent(name)}`);
    state.docs[name] = data;
    const target = name === "tutorial" ? $("#tutorial-content") : $("#guide-content");
    target.innerHTML = renderMarkdown(data.markdown || "");
  } catch (error) {
    toast(`文档读取失败：${error.message}`, true);
  }
}

/* Wiring --------------------------------------------------------------- */
function wire() {
  $("#run-audit").addEventListener("click", runAudit);
  $("#audit-refresh").addEventListener("click", runAudit);
  $("#console-run").addEventListener("click", runAudit);
  $("#console-refresh").addEventListener("click", loadConsole);
  $("#theme-toggle").addEventListener("click", toggleTheme);
  $("#copy-summary").addEventListener("click", copySummary);
  $("#audit-export").addEventListener("click", exportCurrentJSON);
  $("#audit-print").addEventListener("click", printReport);
  $("#audit-search").addEventListener("input", (event) => {
    state.query = event.target.value || "";
    renderAuditTable();
  });
  $("#history-export").addEventListener("click", exportHistoryJSON);
  $("#history-refresh").addEventListener("click", loadHistory);
  $("#history-filter").addEventListener("change", (event) => {
    state.historyFilter = event.target.value;
    renderHistoryPage();
  });
  $("#history-diff-close").addEventListener("click", () => $("#history-diff").classList.add("hidden"));
  $("#refresh-status").addEventListener("click", async () => {
    await loadStatus();
    await loadSnapshots();
    await loadProfiles();
    await loadHistory();
    await loadConsole();
    toast("状态已刷新。");
  });
  $("#snapshots-refresh").addEventListener("click", loadSnapshots);
  $("#profiles-refresh").addEventListener("click", loadProfiles);
  $("#status-filter").addEventListener("change", (event) => {
    state.filter = event.target.value;
    renderAuditTable();
  });
  $("#detail-close").addEventListener("click", () => $("#detail-panel").classList.add("hidden"));

  $("#hero-align").addEventListener("click", () => {
    showView("actions");
    openAlignDialog();
  });
  $("#open-align-dialog").addEventListener("click", openAlignDialog);
  $("#quick-browser").addEventListener("click", quickBrowser);
  $("#undo-align").addEventListener("click", undoLastAlign);
  $("#restore-latest").addEventListener("click", restoreLatest);
  $("#restore-selected").addEventListener("click", restoreSelected);
  $("#restore-select").addEventListener("change", syncActionButtons);
  $("#action-undo-snapshot").addEventListener("click", (event) => {
    const id = event.currentTarget.dataset.snapshotId;
    if (id) restoreSnapshot(id, "本次对齐前");
  });
  $("#align-cancel").addEventListener("click", closeAlignDialog);
  $("#align-cancel-x").addEventListener("click", closeAlignDialog);
  $("#align-submit").addEventListener("click", submitAlign);
  $("#align-form").addEventListener("submit", (event) => event.preventDefault());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      $("#detail-panel").classList.add("hidden");
      $("#history-diff").classList.add("hidden");
      closeAlignDialog();
    }
  });
  window.addEventListener("hashchange", () => {
    const name = (location.hash || "#overview").replace("#", "");
    showView(name, false);
  });
}

async function init() {
  setupNavigation();
  wire();
  applyTheme(document.documentElement.dataset.theme || "dark");
  await loadStatus();
  await loadSnapshots();
  await loadProfiles();
  const hasReport = await loadReport();
  await loadHistory();
  await loadConsole();
  await loadControl();
  if (!hasReport) {
    await runAudit();
  }
  loadDocs("tutorial");
  loadDocs("guide");
}

document.addEventListener("DOMContentLoaded", () => {
  // Remove the first-entry flag after the stagger finishes, so later view
  // switches never replay it. Fall back to a timer in case init is slow.
  window.setTimeout(() => document.body.classList.remove("booting"), 900);
  init();
});
