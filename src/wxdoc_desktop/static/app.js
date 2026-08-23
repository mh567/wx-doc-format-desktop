const state = {
  token: "",
  files: [],
  running: false,
  changingDirectory: false,
  resultDirectory: "",
  notice: "",
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
const resultDirectory = document.querySelector("#resultDirectory");
const openDirectoryButton = document.querySelector("#openDirectoryButton");
const changeDirectoryButton = document.querySelector("#changeDirectoryButton");
const actionNote = document.querySelector("#actionNote");

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
  if (item.status === "review") return `已完成，需要复核 ${item.result.warning_count} 项`;
  if (item.status === "failed") return item.error || "转换失败";
  return "等待处理";
}

function render() {
  queueHeader.hidden = state.files.length === 0;
  const waiting = state.files.filter(item => item.status === "waiting").length;
  const processing = state.files.filter(item => item.status === "processing").length;
  const completed = state.files.filter(item => item.status === "completed").length;
  const review = state.files.filter(item => item.status === "review").length;
  const failed = state.files.filter(item => item.status === "failed").length;
  queueSummary.textContent = state.files.length
    ? `待处理 ${waiting} · 处理中 ${processing} · 已完成 ${completed} · 需复核 ${review} · 失败 ${failed}`
    : "";
  const actionable = waiting + failed;
  convertButton.disabled = state.running || !state.token || actionable === 0;
  shutdownButton.disabled = state.running;
  openDirectoryButton.disabled = !state.token;
  changeDirectoryButton.disabled = state.running || state.changingDirectory || !state.token;
  convertButton.querySelector("span").textContent = state.running
    ? "正在转换"
    : failed && !waiting ? `重试 ${failed} 个文件` : `转换 ${actionable} 个待处理文件`;
  resultDirectory.textContent = state.resultDirectory || "正在读取位置";
  actionNote.textContent = state.notice;
  queue.innerHTML = "";
  state.files.forEach((item, index) => {
    const row = document.createElement("li");
    row.className = "queue-item";
    row.classList.add(`is-${item.status}`);
    row.style.setProperty("--index", index);
    const extension = item.file.name.split(".").pop().toUpperCase();
    const actions = item.result ? `
      <div class="result-actions">
        <button type="button" data-action="open-document">打开文件</button>
        <button type="button" data-action="reveal">打开文件夹</button>
        <button type="button" data-action="open-report">查看审计</button>
      </div>` : "";
    row.innerHTML = `
      <div class="file-icon">${extension}</div>
      <div class="file-meta"><strong></strong><span>${formatSize(item.file.size)}</span></div>
      <div class="result-meta"><div class="job-status ${item.status}">${statusLabel(item)}</div>${actions}</div>`;
    row.querySelector("strong").textContent = item.file.name;
    row.querySelectorAll("[data-action]").forEach(button => {
      button.addEventListener("click", () => runResultAction(item, button.dataset.action));
    });
    queue.appendChild(row);
  });
}

async function runResultAction(item, action) {
  state.notice = "";
  render();
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(item.result.job)}/${action}`, {
      method: "POST",
      headers: { "X-WX-Token": state.token }
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.message || "无法打开目标");
  } catch (error) {
    state.notice = error.message;
    render();
  }
}

async function openResultDirectory() {
  state.notice = "";
  render();
  try {
    const response = await fetch("/api/result-directory/open", {
      method: "POST",
      headers: { "X-WX-Token": state.token }
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.message || "无法打开结果目录");
  } catch (error) {
    state.notice = error.message;
    render();
  }
}

async function changeResultDirectory() {
  if (state.running || state.changingDirectory) return;
  state.changingDirectory = true;
  state.notice = "";
  render();
  try {
    const response = await fetch("/api/result-directory/select", {
      method: "POST",
      headers: { "X-WX-Token": state.token }
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.message || "未更改结果目录");
    if (!payload.canceled) state.resultDirectory = payload.result_directory;
  } catch (error) {
    state.notice = error.message;
  }
  state.changingDirectory = false;
  render();
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

async function connect() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const payload = await response.json();
    state.token = payload.token;
    connectionStatus.textContent = "本地服务已就绪";
    connectionStatus.className = "connection ready";
    const env = payload.environment;
    state.resultDirectory = payload.result_directory;
    document.querySelector("#versionText").textContent = `应用 ${env.application_version}  ·  规则 ${env.engine_version}`;
    await heartbeat();
    state.heartbeatTimer = window.setInterval(heartbeat, 15000);
  } catch (error) {
    connectionStatus.textContent = "本地服务连接失败";
    connectionStatus.className = "connection error";
  }
  render();
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
openDirectoryButton.addEventListener("click", openResultDirectory);
changeDirectoryButton.addEventListener("click", changeResultDirectory);
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

connect();
