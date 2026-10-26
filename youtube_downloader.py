"""Run the local browser interface for the YouTube downloader."""

from __future__ import annotations

import os
import json
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import threading
import webbrowser
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "settings.json"
HISTORY_PATH = ROOT / "history.json"
try:
    _saved_settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    _saved_settings = {}
DOWNLOAD_DIR = Path(
    _saved_settings.get("download_dir")
    or os.environ.get("YOUTUBE_DOWNLOAD_DIR", str(Path.home() / "Downloads"))
).expanduser()


class ChromeProfilePermissionError(RuntimeError):
    pass


def chrome_profile_has_cookies(profile: Path) -> bool:
    try:
        with os.scandir(profile) as entries:
            names = {entry.name for entry in entries}
    except PermissionError as exc:
        raise ChromeProfilePermissionError(
            "macOS 阻止本机程序读取 Chrome 配置目录。要自动使用 Cookie，请在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”授权启动程序的 Terminal，然后重新打开 start.command。该权限也可访问其他受保护文件，不只 Chrome Cookie。"
        ) from exc
    if "Cookies" in names:
        return True
    if "Network" in names:
        network_dir = profile / "Network"
        try:
            with os.scandir(network_dir) as entries:
                return any(entry.name == "Cookies" for entry in entries)
        except PermissionError as exc:
            raise ChromeProfilePermissionError(
                "macOS 阻止本机程序读取 Chrome Cookie 目录。要自动使用 Cookie，请在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”授权启动程序的 Terminal，然后重新打开 start.command。该权限也可访问其他受保护文件，不只 Chrome Cookie。"
            ) from exc
    return False


def discover_chrome_profile() -> str:
    """Find a local Chrome profile by checking profile directory names, never cookie contents."""
    roots = [
        Path.home() / "Library/Application Support/Google/Chrome",
        Path.home() / "Library/Application Support/Google/Chrome Beta",
        Path.home() / "Library/Application Support/Google/Chrome Canary",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        try:
            state = json.loads((root / "Local State").read_text(encoding="utf-8"))
            last_used = state.get("profile", {}).get("last_used")
        except (OSError, json.JSONDecodeError):
            last_used = None
        try:
            profile_dirs = [path for path in root.iterdir() if path.is_dir() and (path.name == "Default" or path.name.startswith("Profile "))]
        except PermissionError as exc:
            raise ChromeProfilePermissionError(
                "macOS 阻止本机程序读取 Chrome 配置目录。要自动使用 Cookie，请在“系统设置 → 隐私与安全性 → 完全磁盘访问权限”授权启动程序的 Terminal，然后重新打开 start.command。该权限也可访问其他受保护文件，不只 Chrome Cookie。"
            ) from exc
        candidates = [root / name for name in ([last_used] if last_used else [])]
        candidates += [path for path in profile_dirs if path not in candidates]
        seen: set[Path] = set()
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.is_dir() and chrome_profile_has_cookies(candidate):
                return str(candidate)
    return ""


CHROME_PROFILE_ACCESS_ERROR = ""
try:
    CHROME_PROFILE_PATH = str(_saved_settings.get("chrome_profile_path") or "") or discover_chrome_profile()
except ChromeProfilePermissionError as exc:
    CHROME_PROFILE_PATH = ""
    CHROME_PROFILE_ACCESS_ERROR = str(exc)
CHROME_PROFILE_IS_SAVED = bool(_saved_settings.get("chrome_profile_path"))
VENV_DIR = ROOT / ".venv"
LOCK = threading.Lock()
try:
    HISTORY: list[dict[str, Any]] = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    if not isinstance(HISTORY, list):
        HISTORY = []
except (OSError, json.JSONDecodeError):
    HISTORY = []
HISTORY = HISTORY[:20]
CANCEL_EVENT = threading.Event()
UPDATING = False
UPDATE_MESSAGE = ""
JOB: dict[str, Any] = {
    "active": False,
    "status": "ready",
    "message": "等待开始",
    "percent": 0,
    "speed": "",
    "filename": "",
    "mode": "video",
    "cancel_requested": False,
    "title": "",
    "url": "",
}


class DownloadCancelled(Exception):
    """Raised by the yt-dlp progress hook after a cancellation request."""


def save_history_entry(entry: dict[str, Any]) -> None:
    with LOCK:
        HISTORY.insert(0, entry)
        del HISTORY[20:]
        temporary = HISTORY_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(HISTORY, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(HISTORY_PATH)


def validated_youtube_url(value: str) -> str:
    url = value.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    if parsed.scheme not in {"http", "https"} or not allowed:
        raise ValueError("请输入有效的 YouTube 视频链接。")
    return url


def readable_error(error: Exception) -> str:
    message = str(error)
    lower_message = message.lower()
    if "Sign in to confirm you’re not a bot" in message or "Sign in to confirm you're not a bot" in message:
        return "YouTube 要求登录验证。请确认 Chrome 已登录 YouTube，再勾选“使用 Chrome 的 YouTube 登录状态”后重试。"
    if "could not copy" in lower_message and "cookie" in lower_message:
        return "无法读取 Chrome Cookie。请关闭 Chrome 后重试，并确认 Chrome 已登录 YouTube。"
    if "could not find chrome cookies database" in lower_message:
        return "没有找到 Chrome Cookie 数据库。请先在桌面版 Chrome 登录 YouTube，或用“选择 Chrome 配置”选择 Default/Profile 文件夹。"
    if "ffmpeg" in lower_message and ("not found" in lower_message or "not installed" in lower_message or "postprocessing" in lower_message):
        return "缺少 FFmpeg，无法合并高清音视频或转换 MP3。macOS 可在终端运行：brew install ffmpeg；安装后重新启动本程序。"
    if "http error 429" in lower_message or "too many requests" in lower_message:
        return "YouTube 暂时限制了请求。请稍后再试；频繁重试可能延长限制时间。"
    if "private video" in lower_message or "members-only" in lower_message or "login required" in lower_message:
        return "该视频需要登录或有访问限制。请确认你有权访问，并在桌面 Chrome 登录后启用 Cookie。"
    if "unsupported url" in lower_message or "not a valid url" in lower_message:
        return "链接无法识别，请确认这是可访问的 YouTube 视频链接。"
    if "unable to download" in lower_message or "network is unreachable" in lower_message or "timed out" in lower_message:
        return "网络连接失败或超时。请检查网络后重试；未完成的临时文件可能会在下次下载时续传。"
    if len(message) > 700:
        message = message[:700] + "…"
    return message


def browser_cookie_options() -> dict[str, Any]:
    global CHROME_PROFILE_PATH, CHROME_PROFILE_ACCESS_ERROR
    if not CHROME_PROFILE_IS_SAVED:
        try:
            CHROME_PROFILE_PATH = discover_chrome_profile()
            CHROME_PROFILE_ACCESS_ERROR = ""
        except ChromeProfilePermissionError as exc:
            CHROME_PROFILE_ACCESS_ERROR = str(exc)
            raise RuntimeError(str(exc)) from exc
    if not CHROME_PROFILE_PATH:
        if CHROME_PROFILE_ACCESS_ERROR:
            raise RuntimeError(CHROME_PROFILE_ACCESS_ERROR)
        raise RuntimeError("未检测到 Chrome Cookie 数据库。请先在桌面版 Chrome 登录 YouTube，然后重试；也可手动选择 Chrome 配置。")
    try:
        if not chrome_profile_has_cookies(Path(CHROME_PROFILE_PATH)):
            raise RuntimeError("所选 Chrome 配置目录中没有 Cookie 数据库。请登录桌面版 Chrome 后重试。")
    except ChromeProfilePermissionError as exc:
        CHROME_PROFILE_ACCESS_ERROR = str(exc)
        raise RuntimeError(str(exc)) from exc
    if CHROME_PROFILE_PATH:
        return {"cookiesfrombrowser": ("chrome", CHROME_PROFILE_PATH)}
    return {"cookiesfrombrowser": ("chrome",)}


def ensure_runtime() -> None:
    """Create a project-local environment and install Python requirements on first launch."""
    venv_python = VENV_DIR / "bin" / "python"
    if not venv_python.exists():
        print("首次启动：正在创建本地 Python 环境…", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    inside_venv = Path(sys.prefix).resolve() == VENV_DIR.resolve()
    dependency_ready = subprocess.run(
        [str(venv_python), "-c", "import yt_dlp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if not dependency_ready:
        print("正在自动安装下载依赖（需要联网，首次运行可能需要一点时间）…", flush=True)
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(ROOT / "requirements.txt")],
            check=True,
        )

    if not inside_venv:
        os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])


class RequestHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/":
            page = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
            page = page.replace("{{ download_dir }}", html.escape(str(DOWNLOAD_DIR)))
            if CHROME_PROFILE_ACCESS_ERROR:
                profile_label = "macOS 限制了 Chrome 配置读取"
            elif CHROME_PROFILE_PATH:
                profile_label = f"已{'选择' if CHROME_PROFILE_IS_SAVED else '自动检测'}：{CHROME_PROFILE_PATH}"
            else:
                profile_label = "未检测到 Chrome 配置；可先登录 Chrome 或手动选择"
            page = page.replace("{{ chrome_profile }}", html.escape(profile_label))
            page = page.replace("{{ chrome_profile_path }}", html.escape(CHROME_PROFILE_PATH))
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path == "/api/status":
            with LOCK:
                result = dict(JOB)
                result["history"] = list(HISTORY)
                result["updating"] = UPDATING
                result["update_message"] = UPDATE_MESSAGE
            result["environment"] = {
                "yt_dlp": getattr(getattr(yt_dlp, "version", None), "__version__", "未知") if yt_dlp else "未就绪",
                "ffmpeg": shutil.which("ffmpeg") is not None,
            }
            self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return
        relative = unquote(self.path.split("?", 1)[0]).lstrip("/")
        asset = (ROOT / relative).resolve()
        static_root = (ROOT / "static").resolve()
        if asset.is_relative_to(static_root) and asset.is_file():
            content_type = "text/css; charset=utf-8" if asset.suffix == ".css" else "text/javascript; charset=utf-8"
            self._send(200, asset.read_bytes(), content_type)
            return
        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if self.path == "/api/folder":
            self._choose_folder()
            return
        if self.path == "/api/chrome-profile":
            self._choose_chrome_profile()
            return
        if self.path == "/api/cancel":
            with LOCK:
                if not JOB["active"]:
                    self._json(409, {"error": "当前没有正在运行的下载任务。"})
                    return
                if JOB["status"] == "processing":
                    self._json(409, {"error": "文件正在合并或转换，当前阶段无法取消，请等待完成。"})
                    return
                JOB["cancel_requested"] = True
                JOB["message"] = "正在取消…"
                CANCEL_EVENT.set()
            self._json(200, {"ok": True})
            return
        if self.path == "/api/update-yt-dlp":
            global UPDATING, UPDATE_MESSAGE
            with LOCK:
                if JOB["active"]:
                    self._json(409, {"error": "下载进行中，完成后再更新 yt-dlp。"})
                    return
                if UPDATING:
                    self._json(409, {"error": "yt-dlp 正在更新，请稍候。"})
                    return
                UPDATING = True
                UPDATE_MESSAGE = "正在检查并安装 yt-dlp 更新…"
            threading.Thread(target=update_ytdlp, daemon=True).start()
            self._json(200, {"ok": True})
            return
        if self.path == "/api/clear-history":
            with LOCK:
                HISTORY.clear()
                try:
                    HISTORY_PATH.write_text("[]", encoding="utf-8")
                except OSError as exc:
                    self._json(500, {"error": f"无法清除记录：{exc}"})
                    return
            self._json(200, {"ok": True})
            return
        if self.path == "/api/open-file":
            self._open_file()
            return
        if self.path == "/api/open-folder":
            self._open_folder()
            return
        if self.path not in {"/api/info", "/api/download"}:
            self._send(404, b'{"error":"Not found"}', "application/json; charset=utf-8")
            return
        length = min(int(self.headers.get("Content-Length", "0")), 100_000)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "无法读取链接内容。"})
            return
        if yt_dlp is None:
            self._json(400, {"error": "下载环境尚未启动，请双击 start.command。"})
            return
        try:
            url = validated_youtube_url(data.get("url") or "")
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return

        if self.path == "/api/info":
            try:
                info_options = {"quiet": True, "no_warnings": True, "skip_download": True}
                use_browser_cookies = bool(data.get("use_browser_cookies"))
                if use_browser_cookies:
                    info_options.update(browser_cookie_options())
                with yt_dlp.YoutubeDL(info_options) as downloader:
                    info = downloader.extract_info(url, download=False)
                heights = sorted({
                    int(fmt["height"])
                    for fmt in info.get("formats", [])
                    if fmt.get("height") and fmt.get("vcodec") not in {None, "none"} and int(fmt["height"]) <= 2160
                })
                labels = {
                    1440: "2K · 1440p",
                    2160: "4K · 2160p",
                }
                resolutions = [{"height": height, "label": labels.get(height, f"{height}p")} for height in heights]
                self._json(200, {
                    "title": info.get("title") or "YouTube 视频",
                    "duration": info.get("duration"),
                    "resolutions": resolutions,
                    "has_audio": any(fmt.get("acodec") not in {None, "none"} for fmt in info.get("formats", [])),
                    "chrome_profile": CHROME_PROFILE_PATH if use_browser_cookies else "",
                })
            except Exception as exc:
                self._json(400, {"error": f"无法读取视频信息：{readable_error(exc)}"})
            return

        mode = data.get("mode", "video")
        if mode not in {"video", "mp3"}:
            self._json(400, {"error": "请选择视频或 MP3 音频格式。"})
            return
        try:
            height = int(data.get("height", 1080))
        except (ValueError, TypeError):
            self._json(400, {"error": "清晰度选项无效。"})
            return
        if height < 1 or height > 2160:
            self._json(400, {"error": "清晰度选项无效。"})
            return
        with LOCK:
            if UPDATING:
                self._json(409, {"error": "yt-dlp 正在更新，请完成后再开始下载。"})
                return
            if JOB["active"]:
                self._json(409, {"error": "当前已有下载任务，请等待完成。"})
                return
            CANCEL_EVENT.clear()
            JOB.update(active=True, status="downloading", message="正在连接视频…", percent=0, speed="", filename="", mode=mode, cancel_requested=False, title=str(data.get("title") or "YouTube 视频"), url=url)
        use_browser_cookies = bool(data.get("use_browser_cookies"))
        threading.Thread(target=download_video, args=(url, mode, height, use_browser_cookies), daemon=True).start()
        self._json(200, {"ok": True})

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _choose_folder(self) -> None:
        global DOWNLOAD_DIR
        with LOCK:
            if JOB["active"]:
                self._json(409, {"error": "下载进行中，完成后再更改保存位置。"})
                return
        if sys.platform != "darwin":
            self._json(400, {"error": "系统文件夹选择器目前仅在 macOS 上配置。"})
            return
        script = 'POSIX path of (choose folder with prompt "选择下载保存文件夹")'
        try:
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._json(500, {"error": f"无法打开文件夹选择器：{exc}"})
            return
        if result.returncode != 0:
            if "User canceled" in result.stderr or "-128" in result.stderr:
                self._json(200, {"cancelled": True})
            else:
                self._json(500, {"error": "打开系统文件夹选择器失败。"})
            return
        selected = Path(result.stdout.strip()).expanduser()
        if not selected.is_dir():
            self._json(400, {"error": "所选位置不是有效文件夹。"})
            return
        DOWNLOAD_DIR = selected
        settings = {"download_dir": str(DOWNLOAD_DIR)}
        if CHROME_PROFILE_IS_SAVED:
            settings["chrome_profile_path"] = CHROME_PROFILE_PATH
        SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        self._json(200, {"ok": True, "path": str(DOWNLOAD_DIR)})

    def _open_file(self) -> None:
        try:
            data = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 100_000)) or b"{}")
            target = Path(str(data.get("path") or "")).expanduser().resolve()
            download_root = DOWNLOAD_DIR.resolve()
            if not target.is_relative_to(download_root) or not target.is_file():
                self._json(400, {"error": "找不到这个下载文件。"})
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform.startswith("win"):
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(target.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._json(200, {"ok": True})
        except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(500, {"error": f"无法打开文件位置：{exc}"})

    def _open_folder(self) -> None:
        try:
            DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(DOWNLOAD_DIR)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform.startswith("win"):
                os.startfile(str(DOWNLOAD_DIR))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(DOWNLOAD_DIR)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._json(200, {"ok": True})
        except OSError as exc:
            self._json(500, {"error": f"无法打开保存位置：{exc}"})

    def _choose_chrome_profile(self) -> None:
        global CHROME_PROFILE_PATH, CHROME_PROFILE_IS_SAVED
        with LOCK:
            if JOB["active"]:
                self._json(409, {"error": "下载进行中，完成后再更改 Chrome 配置。"})
                return
        if sys.platform != "darwin":
            self._json(400, {"error": "Chrome 配置选择器目前仅在 macOS 上配置。"})
            return
        script = 'POSIX path of (choose folder with prompt "选择 Chrome 的 Default 或 Profile 文件夹")'
        try:
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._json(500, {"error": f"无法打开文件夹选择器：{exc}"})
            return
        if result.returncode != 0:
            if "User canceled" in result.stderr or "-128" in result.stderr:
                self._json(200, {"cancelled": True})
            else:
                self._json(500, {"error": "打开 Chrome 配置选择器失败。"})
            return
        selected = Path(result.stdout.strip()).expanduser()
        cookie_databases = (selected / "Network" / "Cookies", selected / "Cookies")
        if not selected.is_dir() or not any(path.is_file() for path in cookie_databases):
            self._json(400, {"error": "所选目录不是 Chrome 配置文件夹。请选择包含 Network/Cookies 或 Cookies 文件的 Default/Profile 文件夹。"})
            return
        CHROME_PROFILE_PATH = str(selected)
        CHROME_PROFILE_IS_SAVED = True
        settings = {"download_dir": str(DOWNLOAD_DIR), "chrome_profile_path": CHROME_PROFILE_PATH}
        SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        self._json(200, {"ok": True, "path": CHROME_PROFILE_PATH})

    def log_message(self, _format: str, *_args: Any) -> None:
        pass


def update_ytdlp() -> None:
    global UPDATING, UPDATE_MESSAGE
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if result.returncode == 0:
            message = "yt-dlp 已更新。请重启下载器后使用新版本。"
        else:
            detail = (result.stderr or result.stdout or "").strip()
            message = "更新失败，请检查网络后重试。" + (f"详情：{detail[-500:]}" if detail else "")
    except subprocess.TimeoutExpired:
        message = "更新超时，请检查网络后重试。"
    except OSError as exc:
        message = f"无法启动更新程序：{exc}"
    with LOCK:
        UPDATE_MESSAGE = message
        UPDATING = False


def download_video(url: str, mode: str, height: int, use_browser_cookies: bool) -> None:
    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        def progress_hook(data: dict[str, Any]) -> None:
            with LOCK:
                if CANCEL_EVENT.is_set():
                    raise DownloadCancelled("用户取消下载")
                if data.get("status") == "downloading":
                    total = data.get("total_bytes") or data.get("total_bytes_estimate")
                    downloaded = data.get("downloaded_bytes", 0)
                    percent = round(downloaded * 100 / total, 1) if total else 0
                    speed = data.get("speed")
                    speed_label = f"{speed / 1024 / 1024:.1f} MB/s" if speed else ""
                    JOB.update(status="downloading", message="正在下载", percent=percent, speed=speed_label)
                elif data.get("status") == "finished":
                    message = "正在提取音轨并转换为 MP3…" if mode == "mp3" else "下载完成，正在合并音视频…"
                    JOB.update(status="processing", message=message, percent=100)

        options = {
            "format": f"bestvideo[height<={height}]+bestaudio/best[height<={height}]" if mode == "video" else "bestaudio/best",
            "outtmpl": str(DOWNLOAD_DIR / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
        }
        if mode == "video":
            options["merge_output_format"] = "mp4"
        else:
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }]
        if use_browser_cookies:
            options.update(browser_cookie_options())
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
        filename = downloader.prepare_filename(info)
        if mode == "mp3":
            filename = str(Path(filename).with_suffix(".mp3"))
        elif filename.endswith(".webm") or filename.endswith(".mkv"):
            mp4_name = str(Path(filename).with_suffix(".mp4"))
            if Path(mp4_name).exists():
                filename = mp4_name
        entry = {
            "title": str(info.get("title") or JOB.get("title") or "YouTube 视频"),
            "url": url,
            "mode": mode,
            "status": "done",
            "message": "下载完成",
            "filename": Path(filename).name,
            "path": str(Path(filename).resolve()),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_history_entry(entry)
        with LOCK:
            done_message = "MP3 音频已保存" if mode == "mp3" else "视频已保存"
            JOB.update(active=False, status="done", message=done_message, percent=100, speed="", filename=Path(filename).name, path=str(Path(filename).resolve()), cancel_requested=False)
    except DownloadCancelled:
        with LOCK:
            title = str(JOB.get("title") or "YouTube 视频")
            JOB.update(active=False, status="cancelled", message="下载已取消。未完成的临时文件会保留，之后可续传。", speed="", cancel_requested=False)
        save_history_entry({"title": title, "url": url, "mode": mode, "status": "cancelled", "message": "下载已取消", "filename": "", "path": "", "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    except Exception as exc:
        message = readable_error(exc)
        with LOCK:
            title = str(JOB.get("title") or "YouTube 视频")
            JOB.update(active=False, status="error", message=message, speed="", cancel_requested=False)
        save_history_entry({"title": title, "url": url, "mode": mode, "status": "error", "message": message, "filename": "", "path": "", "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})


def main() -> None:
    global yt_dlp
    ensure_runtime()
    import yt_dlp as downloader_module
    yt_dlp = downloader_module

    url = "http://127.0.0.1:8765"
    threading.Timer(1, lambda: webbrowser.open(url)).start()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), RequestHandler)
    print(f"视频下载器已启动：{url}（按 Ctrl+C 停止）")
    server.serve_forever()


if __name__ == "__main__":
    main()
