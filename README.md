# ClipDrop

ClipDrop 是一个在 macOS 本机运行的 YouTube 视频下载器。打开网页界面，粘贴视频链接，即可查看视频信息、选择可用画质，并保存为视频或 MP3 音频。

下载服务只监听 `127.0.0.1`，不会把下载任务或 Chrome 登录信息发送到本项目的服务器。程序使用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 解析视频；YouTube 的访问规则和解析方式可能变化，因此某些视频仍可能无法读取或下载。

## 功能

- 自动读取 YouTube 视频标题、时长和该视频实际提供的分辨率，最高显示至 2160p。
- 下载视频，或提取并转换为 MP3。
- 显示下载进度、速度和当前处理状态；下载过程中可取消。
- 选择本机保存目录，在 Finder 中打开保存位置或显示已下载文件。
- 保留最近 20 条下载记录，可重新解析链接或清除记录。
- 首次启动时自动创建项目专属 Python 虚拟环境并安装 yt-dlp。
- 页面可检查 FFmpeg 状态，并提供 yt-dlp 更新入口。
- 可选使用本机 Chrome Cookie 处理 YouTube 登录验证。默认关闭；不会自动上传 Cookie。

## 系统要求

- macOS
- Python 3.9 或更新版本
- 网络连接（首次启动时安装 Python 依赖、读取视频信息和下载内容需要联网）
- FFmpeg（使用 MP3 转换和合并高清视频/音频时需要）

可通过 Homebrew 安装 FFmpeg：

```bash
brew install ffmpeg
```

## 快速开始

### 方法一：双击启动

双击项目目录中的 `start.command`。首次启动会自动创建 `.venv` 并安装 `requirements.txt` 中的依赖，然后打开浏览器访问本地页面。

如果 macOS 未允许打开脚本，可在终端进入项目目录后运行：

```bash
chmod +x start.command
./start.command
```

### 方法二：终端启动

```bash
python3 youtube_downloader.py
```

程序会自动准备项目本地环境并打开 `http://127.0.0.1:8765/`。关闭启动程序的终端或按 `Ctrl+C` 可停止服务。

## 使用方法

1. 启动程序，在网页中粘贴 YouTube 视频链接，或点击“粘贴”。
2. 等待读取视频信息，然后选择“视频”或“MP3 音频”。
3. 下载视频时，从实际可用的清晰度中选择目标画质。
4. 如需修改保存位置，点击“更改”；点击“打开”可直接打开下载目录。
5. 点击“开始下载”查看进度。下载中的任务可点击“取消下载”。
6. 完成后可在“下载记录”中查看记录、重新解析链接，或在 Finder 中显示文件。

默认下载目录为 `~/Downloads`。选择的下载目录和 Chrome 配置会保存在项目目录中的 `settings.json`；最近下载记录保存在 `history.json`。这两个本地文件已加入 `.gitignore`，不会随普通 Git 提交上传。

## YouTube 登录验证与 Cookie

Cookie 选项默认关闭。公开视频可先尝试不使用 Cookie 读取。如果 YouTube 要求登录验证，可以先在桌面版 Chrome 登录 YouTube，再手动启用“使用 Chrome Cookie 用于 YouTube 验证”。如果程序没有找到配置，可点击“选择 Chrome 配置”，选择包含 `Network/Cookies` 或 `Cookies` 文件的 `Default` / `Profile` 文件夹。

macOS 可能会阻止终端程序访问 Chrome 配置。系统隐私权限只能由用户自行授予；也可以保持 Cookie 关闭，尝试访问公开内容。Cookie 不应分享、提交到 GitHub 或发送给他人。启用 Cookie 也不能保证所有视频都能访问。

## 故障排查

- **MP3 转换或高清视频合并失败**：确认 FFmpeg 已安装，并且重启程序后网页显示“FFmpeg 已就绪”。
- **提示 YouTube 要求登录验证**：在 Chrome 登录 YouTube 后，按上文手动启用 Cookie；若仍失败，稍后重试或尝试不使用 Cookie。
- **读取不到 Chrome Cookie**：关闭 Chrome 后重试，或在 macOS 隐私设置中为启动程序的终端授予相应文件访问权限。授权会扩大终端可访问的本机文件范围，请按需决定。
- **清晰度或下载格式不可用**：程序只能显示 YouTube 当前为该视频提供且 yt-dlp 能读取的格式；视频解析失败时可在页面点击“更新 yt-dlp”，更新完成后重启程序。
- **请求过多或网络超时**：检查网络并稍后再试，避免连续重复请求。

## 支持范围

当前网页只接受 YouTube 视频链接。yt-dlp 支持许多网站，但本项目的链接校验、界面和 Cookie 流程目前针对 YouTube；其他平台的链接不会被接受。

## 使用提醒

请只下载你有权保存的内容，并遵守 YouTube 服务条款、当地法律和内容版权规定。登录 Cookie 属于敏感信息；不要将 Cookie 数据库或导出的 Cookie 文件加入仓库。

## 许可证

本项目以 MIT License 开源，详见 [LICENSE](LICENSE)。
