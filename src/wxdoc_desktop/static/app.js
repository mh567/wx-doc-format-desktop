const state = { token: "", files: [], running: false };
const fileInput = document.querySelector("#fileInput");
const dropzone = document.querySelector("#dropzone");
const queue = document.querySelector("#queue");
const queueHeader = document.querySelector("#queueHeader");
const queueSummary = document.querySelector("#queueSummary");
const convertButton = document.querySelector("#convertButton");
const clearButton = document.querySelector("#clearButton");
const connectionStatus = document.querySelector("#connectionStatus");
const shutdownButton = document.querySelector("#shutdownButton");

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function addFiles(fileList) {
  const accepted = [...fileList].filter(file => /\.(docx|md|markdown)$/i.test(file.name));
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

async function connect() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const payload = await response.json();
    state.token = payload.token;
    connectionStatus.textContent = "本地服务已就绪";
    connectionStatus.className = "connection ready";
    const env = payload.environment;
    document.querySelector("#versionText").textContent = `应用 ${env.application_version}  ·  规则 ${env.engine_version}`;
  } catch (error) {
    connectionStatus.textContent = "本地服务连接失败";
    connectionStatus.className = "connection error";
  }
  render();
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
shutdownButton.addEventListener("click", async () => {
  shutdownButton.disabled = true;
  shutdownButton.textContent = "正在退出";
  try { await fetch("/api/shutdown", { method: "POST", headers: { "X-WX-Token": state.token } }); } catch (error) {}
  document.body.innerHTML = '<main class="closed"><h1>程序已退出</h1><p>现在可以关闭这个页面。</p></main>';
});

connect();
