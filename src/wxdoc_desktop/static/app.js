const state = {
  token: "",
  files: [],
  running: false,
  view: "convert",
  reviewFile: null,
  reviewResult: null,
  reviewError: "",
  reviewRunning: false,
  clientId: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`,
  heartbeatTimer: null
};
const fileInput = document.querySelector("#fileInput");
const dropzone = document.querySelector("#dropzone");
const queue = document.querySelector("#queue");
const queueHeader = document.querySelector("#queueHeader");
const queueSummary = document.querySelector("#queueSummary");
const convertButton = document.querySelector("#convertButton");
const clearButton = document.querySelector("#clearButton");
const connectionStatus = document.querySelector("#connectionStatus");
const shutdownButton = document.querySelector("#shutdownButton");
const viewConvert = document.querySelector("#viewConvert");
const viewReview = document.querySelector("#viewReview");
const tabConvert = document.querySelector("#tabConvert");
const tabReview = document.querySelector("#tabReview");
const reviewInput = document.querySelector("#reviewInput");
const reviewDropzone = document.querySelector("#reviewDropzone");
const reviewSelection = document.querySelector("#reviewSelection");
const reviewError = document.querySelector("#reviewError");
const reviewButton = document.querySelector("#reviewButton");
const reviewResult = document.querySelector("#reviewResult");

const SEVERITY_ORDER = ["critical", "high", "medium", "low"];
const SEVERITY_LABELS = { critical: "严重", high: "高优先级", medium: "中优先级", low: "低优先级" };
const DIMENSION_ORDER = [
  ["format_conformance", "样式与元素格式"],
  ["heading_hierarchy", "大纲层级"],
  ["list_structure", "列表结构"],
  ["table_format", "表格"],
  ["toc_structure", "目录"],
  ["appendix_structure", "附录"],
  ["caption", "题注"],
  ["note_structure", "注"],
  ["numbering_page", "页码与编号"],
  ["ai_review", "AI 语义"]
];
const GRADE_COLORS = { "优": "#267257", "良": "#2f8a6a", "中": "#b2912f", "及格": "#bf6b2c", "差": "#a14338" };

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function addFiles(fileList) {
  const accepted = [...fileList].filter(file => /\.(docx|md)$/i.test(file.name));
  for (const file of accepted) {
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    if (!state.files.some(item => item.key === key)) {
      state.files.push({ key, file, status: "waiting", result: null, error: "" });
    }
  }
  render();
}

function statusLabel(item) {
  if (item.status === "processing") return "正在整理";
  if (item.status === "completed") return "已完成";
  if (item.status === "review") return `建议复核 ${item.result.warning_count} 项`;
  if (item.status === "failed") return item.error || "转换失败";
  return "等待处理";
}

function render() {
  queueHeader.hidden = state.files.length === 0;
  queueSummary.textContent = state.files.length ? `已选择 ${state.files.length} 个文件` : "";
  convertButton.disabled = state.running || !state.token || !state.files.some(item => item.status === "waiting" || item.status === "failed");
  shutdownButton.disabled = state.running || state.reviewRunning;
  convertButton.querySelector("span").textContent = state.running ? "正在转换" : "开始转换";
  queue.innerHTML = "";
  state.files.forEach((item, index) => {
    const row = document.createElement("li");
    row.className = "queue-item";
    row.style.setProperty("--index", index);
    const extension = item.file.name.split(".").pop().toUpperCase();
    const downloads = item.result ? `
      <div class="download-group">
        <a href="${item.result.downloads.document}">下载文档</a>
        <a href="${item.result.downloads.report}">查看报告</a>
      </div>` : "";
    row.innerHTML = `
      <div class="file-icon">${extension}</div>
      <div class="file-meta"><strong></strong><span>${formatSize(item.file.size)}</span></div>
      <div><div class="job-status ${item.status}">${statusLabel(item)}</div>${downloads}</div>`;
    row.querySelector("strong").textContent = item.file.name;
    queue.appendChild(row);
  });
}

async function convertAll() {
  state.running = true;
  render();
  for (const item of state.files) {
    if (!['waiting', 'failed'].includes(item.status)) continue;
    item.status = "processing";
    item.error = "";
    render();
    try {
      const response = await fetch("/api/convert", {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-WX-Token": state.token,
          "X-WX-Filename": encodeURIComponent(item.file.name)
        },
        body: item.file
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.message || "转换失败");
      item.result = payload;
      item.status = payload.status;
    } catch (error) {
      item.status = "failed";
      item.error = error.message;
    }
    render();
  }
  state.running = false;
  render();
}

function setView(name) {
  state.view = name;
  const review = name === "review";
  viewConvert.hidden = review;
  viewReview.hidden = !review;
  tabConvert.setAttribute("aria-selected", review ? "false" : "true");
  tabReview.setAttribute("aria-selected", review ? "true" : "false");
  renderReview();
}

function setReviewFile(file) {
  if (!file) return;
  if (!/\.docx$/i.test(file.name)) {
    state.reviewFile = null;
    state.reviewError = "审查仅支持 .docx 文件。";
  } else {
    state.reviewFile = file;
    state.reviewError = "";
    state.reviewResult = null;
  }
  renderReview();
}

async function runReview() {
  if (!state.reviewFile || state.reviewRunning) return;
  state.reviewRunning = true;
  state.reviewError = "";
  renderReview();
  render();
  try {
    const response = await fetch("/api/review", {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-WX-Token": state.token,
        "X-WX-Filename": encodeURIComponent(state.reviewFile.name)
      },
      body: state.reviewFile
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.message || "审查失败");
    state.reviewResult = payload;
  } catch (error) {
    state.reviewError = error.message;
  }
  state.reviewRunning = false;
  renderReview();
  render();
}

function gradeColor(grade, score) {
  if (GRADE_COLORS[grade]) return GRADE_COLORS[grade];
  if (score >= 90) return GRADE_COLORS["优"];
  if (score >= 80) return GRADE_COLORS["良"];
  if (score >= 70) return GRADE_COLORS["中"];
  if (score >= 60) return GRADE_COLORS["及格"];
  return GRADE_COLORS["差"];
}

function makeElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function buildScoreHero(result, color) {
  const radius = 78;
  const circumference = 2 * Math.PI * radius;
  const hero = makeElement("div", "score-hero");
  hero.style.setProperty("--score-color", color);
  const wrap = makeElement("div", "score-ring-wrap");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "score-ring");
  svg.setAttribute("viewBox", "0 0 176 176");
  const track = document.createElementNS(svg.namespaceURI, "circle");
  track.setAttribute("class", "score-ring-track");
  track.setAttribute("cx", "88");
  track.setAttribute("cy", "88");
  track.setAttribute("r", String(radius));
  const value = document.createElementNS(svg.namespaceURI, "circle");
  value.setAttribute("class", "score-ring-value");
  value.setAttribute("cx", "88");
  value.setAttribute("cy", "88");
  value.setAttribute("r", String(radius));
  const ratio = Math.max(0, Math.min(100, Number(result.score) || 0)) / 100;
  value.setAttribute("stroke-dasharray", `${circumference * ratio} ${circumference}`);
  svg.append(track, value);
  const center = makeElement("div", "score-center");
  const scoreValue = makeElement("span", "score-value", `${Number(result.score).toFixed(1)}`);
  scoreValue.appendChild(makeElement("small", "", "分"));
  center.append(scoreValue, makeElement("span", "score-grade"));
  const grade = center.querySelector(".score-grade");
  grade.append(document.createTextNode("等级 "));
  grade.appendChild(makeElement("b", "", result.grade || "未评级"));
  wrap.append(svg, center);
  hero.appendChild(wrap);
  const scored = DIMENSION_ORDER.filter(([key]) => key in (result.dimension_scores || {})).length;
  hero.appendChild(makeElement("p", "score-caption", `${result.filename || ""} · 按 ${scored} 个维度加权评分`));
  return hero;
}

function buildIssueSummary(summary) {
  const row = makeElement("div", "issue-summary");
  for (const level of SEVERITY_ORDER) {
    const chip = makeElement("span", "", `${SEVERITY_LABELS[level]} `);
    chip.appendChild(makeElement("b", "", String(summary[level] ?? 0)));
    row.appendChild(chip);
  }
  return row;
}

function buildDimensions(dimensionScores) {
  const list = makeElement("div", "dimension-list");
  for (const [key, label] of DIMENSION_ORDER) {
    if (!(key in dimensionScores)) continue;
    const score = Number(dimensionScores[key]) || 0;
    const row = makeElement("div", "dimension-row");
    row.appendChild(makeElement("span", "dimension-name", label));
    const track = makeElement("div", "dimension-track");
    const bar = makeElement("div", "dimension-bar");
    bar.style.width = `${Math.max(0, Math.min(100, score))}%`;
    track.appendChild(bar);
    row.appendChild(track);
    row.appendChild(makeElement("span", "dimension-score", score.toFixed(0)));
    list.appendChild(row);
  }
  return list;
}

function buildIssues(issues) {
  const list = makeElement("div", "issue-list");
  for (const issue of issues) {
    const level = SEVERITY_ORDER.includes(issue.level) ? issue.level : "low";
    const card = makeElement("div", `issue ${level}`);
    card.appendChild(makeElement("div", "issue-title", issue.title || issue.code || "未命名问题"));
    const meta = [SEVERITY_LABELS[level]];
    if (issue.location) meta.push(issue.location);
    card.appendChild(makeElement("div", "issue-meta", meta.join(" · ")));
    if (issue.suggestion) card.appendChild(makeElement("div", "issue-suggestion", issue.suggestion));
    list.appendChild(card);
  }
  return list;
}

function renderReviewResult() {
  const result = state.reviewResult;
  reviewResult.innerHTML = "";
  if (!result) {
    reviewResult.hidden = true;
    return;
  }
  reviewResult.hidden = false;
  const color = gradeColor(result.grade, Number(result.score) || 0);
  reviewResult.appendChild(buildScoreHero(result, color));

  if (Number(result.summary?.total_issues) > 0) {
    reviewResult.appendChild(buildIssueSummary(result.summary || {}));
  }

  const dimensions = result.dimension_scores || {};
  if (Object.keys(dimensions).length) {
    reviewResult.appendChild(makeElement("h2", "review-block-title", "分项得分"));
    reviewResult.appendChild(buildDimensions(dimensions));
  }

  const issues = Array.isArray(result.issues) ? result.issues : [];
  reviewResult.appendChild(makeElement("h2", "review-block-title", "问题清单"));
  if (issues.length) {
    reviewResult.appendChild(buildIssues(issues));
  } else {
    reviewResult.appendChild(makeElement("p", "review-empty", "未发现问题。"));
  }

  if (Array.isArray(result.compliant_items) && result.compliant_items.length) {
    reviewResult.appendChild(makeElement("h2", "review-block-title", "合规项摘要"));
    const list = makeElement("ul", "compliant-list");
    for (const item of result.compliant_items) list.appendChild(makeElement("li", "", item));
    reviewResult.appendChild(list);
  }

  if (Array.isArray(result.risk_warnings) && result.risk_warnings.length) {
    reviewResult.appendChild(makeElement("h2", "review-block-title", "风险提示"));
    const notes = makeElement("div", "risk-notes");
    for (const warning of result.risk_warnings) notes.appendChild(makeElement("div", "risk-note", warning));
    reviewResult.appendChild(notes);
  }

  const downloads = result.downloads || {};
  if (downloads.details) {
    const links = makeElement("div", "review-downloads");
    for (const [kind, label] of [["details", "下载报告 JSON"], ["markdown", "下载整改报告 Markdown"], ["report", "下载整改报告 HTML"]]) {
      if (!downloads[kind]) continue;
      const link = makeElement("a", "", label);
      link.href = downloads[kind];
      links.appendChild(link);
    }
    reviewResult.appendChild(links);
  }
}

function renderReview() {
  reviewSelection.hidden = !state.reviewFile;
  reviewSelection.textContent = state.reviewFile ? state.reviewFile.name : "";
  reviewError.hidden = !state.reviewError;
  reviewError.textContent = state.reviewError;
  reviewButton.disabled = state.reviewRunning || !state.token || !state.reviewFile;
  reviewButton.querySelector("span").textContent = state.reviewRunning ? "正在审查" : "开始审查";
  renderReviewResult();
}

async function connect() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const payload = await response.json();
    state.token = payload.token;
    connectionStatus.textContent = "本地服务已就绪";
    connectionStatus.className = "connection ready";
    const env = payload.environment;
    document.querySelector("#versionText").textContent = `应用 ${env.application_version}  ·  规则 ${env.engine_version}`;
    await heartbeat();
    state.heartbeatTimer = window.setInterval(heartbeat, 15000);
  } catch (error) {
    connectionStatus.textContent = "本地服务连接失败";
    connectionStatus.className = "connection error";
  }
  render();
  renderReview();
}

async function heartbeat() {
  if (!state.token) return;
  try {
    await fetch("/api/heartbeat", {
      method: "POST",
      cache: "no-store",
      headers: { "X-WX-Token": state.token, "X-Magic-Client": state.clientId }
    });
  } catch (error) {}
}

fileInput.addEventListener("change", event => addFiles(event.target.files));
dropzone.addEventListener("dragover", event => { event.preventDefault(); dropzone.classList.add("dragging"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragging"));
dropzone.addEventListener("drop", event => {
  event.preventDefault();
  dropzone.classList.remove("dragging");
  addFiles(event.dataTransfer.files);
});
clearButton.addEventListener("click", () => { if (!state.running) { state.files = []; fileInput.value = ""; render(); } });
convertButton.addEventListener("click", convertAll);
tabConvert.addEventListener("click", () => setView("convert"));
tabReview.addEventListener("click", () => setView("review"));
reviewInput.addEventListener("change", event => setReviewFile(event.target.files && event.target.files[0]));
reviewDropzone.addEventListener("dragover", event => { event.preventDefault(); reviewDropzone.classList.add("dragging"); });
reviewDropzone.addEventListener("dragleave", () => reviewDropzone.classList.remove("dragging"));
reviewDropzone.addEventListener("drop", event => {
  event.preventDefault();
  reviewDropzone.classList.remove("dragging");
  setReviewFile(event.dataTransfer.files && event.dataTransfer.files[0]);
});
reviewButton.addEventListener("click", runReview);
shutdownButton.addEventListener("click", async () => {
  if (state.heartbeatTimer) window.clearInterval(state.heartbeatTimer);
  shutdownButton.disabled = true;
  shutdownButton.textContent = "正在退出";
  try {
    const response = await fetch("/api/shutdown", { method: "POST", headers: { "X-WX-Token": state.token } });
    if (!response.ok) throw new Error("busy");
  } catch (error) {
    shutdownButton.disabled = false;
    shutdownButton.textContent = "退出程序";
    state.heartbeatTimer = window.setInterval(heartbeat, 15000);
    return;
  }
  document.body.innerHTML = '<main class="closed"><h1>程序已退出</h1><p>现在可以关闭这个页面。</p></main>';
});

setView(state.view);
connect();
