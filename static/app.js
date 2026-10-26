const urlInput = document.querySelector("#video-url");
const cookieCheckbox = document.querySelector("#use-browser-cookies");
const chromeProfilePath = document.querySelector("#chrome-profile-path");
const profileButton = document.querySelector("#profile-button");
const downloadButton = document.querySelector("#download-button");
const folderButton = document.querySelector("#folder-button");
const openFolderButton = document.querySelector("#open-folder-button");
const cancelButton = document.querySelector("#cancel-button");
const updateButton = document.querySelector("#update-button");
const environmentDetail = document.querySelector("#environment-detail");
const folderPath = document.querySelector(".location-path");
const progressArea = document.querySelector("#progress-area");
const progressFill = document.querySelector("#progress-fill");
const statusLabel = document.querySelector("#status-label");
const percentLabel = document.querySelector("#percent-label");
const detailLabel = document.querySelector("#detail-label");
const videoSummary = document.querySelector("#video-summary");
const videoTitle = document.querySelector("#video-title");
const videoDuration = document.querySelector("#video-duration");
const formatOptions = document.querySelector("#format-options");
const resolutionRow = document.querySelector("#resolution-row");
const resolutionSelect = document.querySelector("#resolution-select");
const mp3Note = document.querySelector("#mp3-note");
const toast = document.querySelector("#toast");
const historyArea = document.querySelector("#history-area");
const historyList = document.querySelector("#history-list");
let pollTimer;
let lookupTimer;
let toastTimer;
let currentLookup = "";
let videoInfo = null;
let selectedMode = "video";
let lastUpdateMessage = "";

function notify(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3600);
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = Math.floor(seconds % 60);
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}` : `${minutes}:${String(remaining).padStart(2, "0")}`;
}

function isYouTubeUrl(value) {
  try {
    const host = new URL(value).hostname.toLowerCase();
    return host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com");
  } catch (_error) {
    return false;
  }
}

async function loadVideoInfo(rawUrl) {
  const url = rawUrl.trim();
  clearTimeout(lookupTimer);
  if (!url) {
    currentLookup = "";
    videoInfo = null;
    videoSummary.hidden = true;
    formatOptions.hidden = true;
    downloadButton.disabled = true;
    return;
  }
  if (!isYouTubeUrl(url)) return;

  const useBrowserCookies = cookieCheckbox.checked;
  let profileKey = useBrowserCookies ? chromeProfilePath.dataset.profilePath : "";
  const lookupKey = `${url}|${useBrowserCookies ? `cookies:${profileKey}` : "no-cookies"}`;
  currentLookup = lookupKey;
  videoInfo = null;
  downloadButton.disabled = true;
  videoSummary.hidden = false;
  videoTitle.textContent = "正在读取视频信息…";
  videoDuration.textContent = "";
  formatOptions.hidden = true;
  try {
    const response = await fetch("/api/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, use_browser_cookies: useBrowserCookies }),
    });
    const result = await response.json();
    if (currentLookup !== lookupKey) return;
    if (!response.ok) throw new Error(result.error || "无法读取视频信息");
    if (useBrowserCookies && result.chrome_profile) {
      profileKey = result.chrome_profile;
      chromeProfilePath.dataset.profilePath = profileKey;
      chromeProfilePath.textContent = `自动检测：${profileKey}`;
    }
    videoInfo = { ...result, url, useBrowserCookies, profileKey };
    videoTitle.textContent = result.title;
    videoDuration.textContent = formatDuration(result.duration);
    resolutionSelect.replaceChildren();
    for (const resolution of result.resolutions) {
      const option = document.createElement("option");
      option.value = resolution.height;
      option.textContent = resolution.label;
      resolutionSelect.append(option);
    }
    if (result.resolutions.length) {
      resolutionSelect.value = String(result.resolutions.at(-1).height);
    }
    resolutionRow.hidden = selectedMode !== "video" || !result.resolutions.length;
    mp3Note.hidden = selectedMode !== "mp3";
    formatOptions.hidden = false;
    downloadButton.disabled = false;
  } catch (error) {
    if (currentLookup !== lookupKey) return;
    videoInfo = null;
    videoSummary.hidden = true;
    formatOptions.hidden = true;
    downloadButton.disabled = true;
    notify(error.message);
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    const job = await response.json();
    progressArea.hidden = job.status === "ready";
    downloadButton.disabled = job.active || job.updating || !videoInfo;
    downloadButton.querySelector("span").textContent = job.active ? "正在处理…" : "开始下载";
    cancelButton.hidden = !job.active;
    cancelButton.disabled = job.cancel_requested;
    cancelButton.textContent = job.cancel_requested ? "正在取消…" : "取消下载";
    progressFill.style.width = `${job.percent || 0}%`;
    percentLabel.textContent = `${job.percent || 0}%`;
    statusLabel.textContent = job.message || "等待开始";
    detailLabel.textContent = job.speed || (job.filename ? `已保存：${job.filename}` : "");
    if (job.status === "done") progressFill.style.width = "100%";
    progressFill.style.background = job.status === "error" ? "#c96b5b" : "";
    const ffmpegLabel = job.environment?.ffmpeg ? "FFmpeg 已就绪" : "缺少 FFmpeg：MP3 转换和高清合并不可用（macOS 可运行 brew install ffmpeg）";
    environmentDetail.textContent = `yt-dlp ${job.environment?.yt_dlp || "未知"} · ${ffmpegLabel}`;
    updateButton.disabled = job.updating || job.active;
    updateButton.textContent = job.updating ? "更新中…" : "更新 yt-dlp";
    if (job.update_message && job.update_message !== lastUpdateMessage) {
      lastUpdateMessage = job.update_message;
      if (job.update_message !== "正在检查并安装 yt-dlp 更新…") notify(job.update_message);
    }
    renderHistory(job.history || []);
    if ((job.active || job.updating) && !pollTimer) pollTimer = setInterval(refreshStatus, 900);
    if (!job.active && !job.updating) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  } catch (_error) {
    notify("无法连接到本地下载服务，请确认程序仍在运行。");
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function renderHistory(entries) {
  historyList.replaceChildren();
  historyArea.hidden = entries.length === 0;
  for (const entry of entries) {
    const row = document.createElement("article");
    row.className = "history-entry";
    const copy = document.createElement("div");
    copy.className = "history-copy";
    const title = document.createElement("strong");
    title.textContent = entry.title || "YouTube 视频";
    const meta = document.createElement("span");
    meta.textContent = `${entry.mode === "mp3" ? "MP3" : "视频"} · ${entry.created_at || ""} · ${entry.status === "done" ? entry.filename : entry.message || "未完成"}`;
    copy.append(title, meta);
    row.append(copy);
    if (entry.status === "done" && entry.path) {
      const open = document.createElement("button");
      open.type = "button";
      open.className = "history-action";
      open.textContent = "显示文件";
      open.addEventListener("click", () => openDownloadedFile(entry.path));
      row.append(open);
    }
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "history-action secondary";
    retry.textContent = "重新解析";
    retry.addEventListener("click", () => {
      urlInput.value = entry.url || "";
      urlInput.focus();
      loadVideoInfo(urlInput.value);
    });
    row.append(retry);
    historyList.append(row);
  }
}

async function openDownloadedFile(path) {
  try {
    const response = await fetch("/api/open-file", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "无法显示文件");
  } catch (error) { notify(error.message); }
}

downloadButton.addEventListener("click", async () => {
  const url = urlInput.value.trim();
  const profileKey = cookieCheckbox.checked ? chromeProfilePath.dataset.profilePath : "";
  if (!videoInfo || videoInfo.url !== url || videoInfo.useBrowserCookies !== cookieCheckbox.checked || videoInfo.profileKey !== profileKey) {
    notify("请先输入链接并等待视频信息读取完成。");
    return;
  }
  if (selectedMode === "video" && !videoInfo.resolutions.length) {
    notify("这个视频没有可读取的视频画质，请选择 MP3 音频。 ");
    return;
  }
  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        mode: selectedMode,
        height: Number(resolutionSelect.value || 1080),
        use_browser_cookies: cookieCheckbox.checked,
        title: videoInfo.title,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "无法开始下载");
    progressArea.hidden = false;
    progressFill.style.background = "";
    downloadButton.disabled = true;
    downloadButton.querySelector("span").textContent = "正在处理…";
    pollTimer = setInterval(refreshStatus, 800);
    await refreshStatus();
  } catch (error) {
    notify(error.message);
  }
});

cancelButton.addEventListener("click", async () => {
  cancelButton.disabled = true;
  try {
    const response = await fetch("/api/cancel", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "无法取消下载");
    cancelButton.textContent = "正在取消…";
  } catch (error) { notify(error.message); cancelButton.disabled = false; }
});

updateButton.addEventListener("click", async () => {
  updateButton.disabled = true;
  try {
    const response = await fetch("/api/update-yt-dlp", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "无法更新 yt-dlp");
    lastUpdateMessage = "";
    notify("已开始更新 yt-dlp，请稍候…");
    if (!pollTimer) pollTimer = setInterval(refreshStatus, 1000);
    await refreshStatus();
  } catch (error) { notify(error.message); updateButton.disabled = false; }
});

document.querySelector("#clear-history-button").addEventListener("click", async () => {
  try {
    const response = await fetch("/api/clear-history", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "无法清除记录");
    renderHistory([]);
  } catch (error) { notify(error.message); }
});

openFolderButton.addEventListener("click", async () => {
  try {
    const response = await fetch("/api/open-folder", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "无法打开保存位置");
  } catch (error) { notify(error.message); }
});

document.querySelectorAll(".format-choice").forEach((button) => {
  button.addEventListener("click", () => {
    selectedMode = button.dataset.mode;
    document.querySelectorAll(".format-choice").forEach((choice) => {
      const selected = choice === button;
      choice.classList.toggle("selected", selected);
      choice.setAttribute("aria-pressed", String(selected));
    });
    resolutionRow.hidden = selectedMode !== "video" || !videoInfo?.resolutions.length;
    mp3Note.hidden = selectedMode !== "mp3";
  });
});

urlInput.addEventListener("input", () => {
  clearTimeout(lookupTimer);
  const url = urlInput.value.trim();
  currentLookup = "";
  if (!url) {
    loadVideoInfo("");
    return;
  }
  videoInfo = null;
  formatOptions.hidden = true;
  downloadButton.disabled = true;
  if (isYouTubeUrl(url)) {
    videoSummary.hidden = false;
    videoTitle.textContent = "正在读取视频信息…";
    videoDuration.textContent = "";
    lookupTimer = setTimeout(() => loadVideoInfo(url), 650);
  } else {
    videoSummary.hidden = true;
  }
});

urlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadVideoInfo(urlInput.value);
});

cookieCheckbox.addEventListener("change", () => {
  const url = urlInput.value.trim();
  if (isYouTubeUrl(url)) loadVideoInfo(url);
});

profileButton.addEventListener("click", async () => {
  profileButton.disabled = true;
  profileButton.textContent = "选择中…";
  try {
    const response = await fetch("/api/chrome-profile", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "无法设置 Chrome 配置");
    if (result.ok) {
      chromeProfilePath.dataset.profilePath = result.path;
      chromeProfilePath.textContent = result.path;
      const url = urlInput.value.trim();
      if (cookieCheckbox.checked && isYouTubeUrl(url)) await loadVideoInfo(url);
    }
  } catch (error) {
    notify(error.message);
  } finally {
    profileButton.disabled = false;
    profileButton.textContent = "选择 Chrome 配置";
  }
});

document.querySelector("#paste-button").addEventListener("click", async () => {
  try {
    urlInput.value = await navigator.clipboard.readText();
    urlInput.focus();
    await loadVideoInfo(urlInput.value);
  } catch (_error) {
    notify("无法读取剪贴板，请直接粘贴链接。");
    urlInput.focus();
  }
});

folderButton.addEventListener("click", async () => {
  folderButton.disabled = true;
  folderButton.textContent = "选择中…";
  try {
    const response = await fetch("/api/folder", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "无法更改保存位置");
    if (result.ok) folderPath.textContent = result.path;
  } catch (error) {
    notify(error.message);
  } finally {
    folderButton.disabled = false;
    folderButton.textContent = "更改";
  }
});

refreshStatus();
