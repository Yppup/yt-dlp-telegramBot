# yt-dlp-telegramBot 🤖

No command line required, making yt-dlp usable anytime, anywhere.

基于 Pyrogram 和 yt-dlp 开发的 Telegram 媒体下载机器人。
无需掌握任何命令行知识，只需向机器人发送链接，即可随时随地将最高画质的流媒体视频直接转存至 Telegram。

## ✨ 核心特性 (Features)

- **原生 MTProto 协议**：基于 Pyrogram 框架开发，彻底突破 HTTP Bot API 的 50MB 上传限制，支持最高 2GB 的大文件直传。
- **实时进度反馈**：拥有顺滑的 UI 体验，提供精确的**下载与上传双向实时进度条**。
- **模块化架构**：核心交互逻辑与下载模块完全解耦，当前内置 X (Twitter) 平台支持，开发者可自行地横向扩展 YouTube、Instagram 等其他平台。
- **统一配置管理**：使用 YAML 文件统一管理密钥与系统路径，避免代码层面的硬编码，安全性高。
- **按需选择格式**：提供“高兼容压缩视频”与“无损原画质文件”两种接收选项，满足不同场景需求。

## 🛠️ 环境依赖 (Prerequisites)

在开始部署之前，请确保你的服务器已安装以下基础环境：
- **Python 3.8+**
- **FFmpeg**：`yt-dlp` 合并超清音视频流的必备系统级依赖。
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - CentOS/RHEL: `sudo yum install ffmpeg`
- **Telegram 开发者密钥**：前往 [my.telegram.org](https://my.telegram.org/) 获取 `API_ID` 和 `API_HASH`。
- **Bot Token**：向 Telegram 中的 [@BotFather](https://t.me/BotFather) 申请并获取。

## 🚀 部署指南 (Installation & Setup)

### 1. 获取代码

```bash
git clone https://github.com/Yppup/yt-dlp-telegramBot.git
cd yt-dlp-telegramBot
```

### 2. 安装系统级依赖

推荐将FFmpeg作为系统全局依赖安装，避免环境冲突：

```bash
# 安装 FFmpeg
apt update
apt install ffmpeg
```

### 3. 配置 Python 虚拟环境

为了隔离环境并符合现代 Linux 系统的 PEP 668 规范，我们仅在虚拟环境中安装其余依赖
：
```bash
python3 -m venv bot_env
source bot_env/bin/activate
pip install pyrogram tgcrypto pyyaml yt-dlp
```
*(注：`tgcrypto` 是 Pyrogram 推荐的底层加密库，可大幅提升上传/下载速度。)*

### 4. 修改配置文件
编辑项目根目录下的 `config.yaml` 文件，填入你的专属配置：

```yaml
TELEGRAM:
  API_ID: 1234567 # 替换为你的 API ID (纯数字)
  API_HASH: "你的API_HASH"
  BOT_TOKEN: "你的BOT_TOKEN"

SYSTEM:
  WORK_DIR: "YOUR_WORK_DIR" # 机器人的绝对工作路径
  X_COOKIE_FILE: "YOUR_X_COOKIE_FILE.txt" # X (Twitter) 的 Cookie 文件名
```

### 5. 准备 Cookie 文件 (可选但推荐)
为了能够正常下载部分限制级（NSFW）或需要登录才能查看的内容，请通过浏览器插件（如 Get cookies.txt LOCALLY）导出目标平台的 Cookie，并命名为 `YOUR_X_COOKIE_FILE.txt`（与配置一致），放置在工作目录中。

### 6. 启动机器人
测试运行：
```bash
python main.py
```
如果终端输出 `Main Pyrogram Bot is starting...`，即可前往 Telegram 向你的机器人发送推文链接进行测试。

---

## ⚙️ 守护进程配置 (Systemd Daemon) - 推荐

为了让机器人能在后台稳定运行并在崩溃后自动重启，建议使用 systemd 进行管理。

1. 创建服务文件：`nano /etc/systemd/system/bot.service`
2. 填入以下配置（注意修改路径匹配你的实际环境）：
```ini
[Unit]
Description=Telegram yt-dlp Bot Service
After=network.target

[Service]
User=root
WorkingDirectory=/your/work/dir
ExecStart=/your/work/dir/bot_env/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
3. 启动并设置开机自启：
```bash
systemctl daemon-reload
systemctl enable bot
systemctl start bot
```

## 📄 开源协议 (License)
本项目基于 [MIT License](LICENSE) 协议开源。

