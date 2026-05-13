<div align="center">

# VlogTrans

**YouTube Vlog 自动汉化工具**

从频道监控到字幕烧录的全流程自动化

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Whisper](https://img.shields.io/badge/Whisper-medium.en-green.svg)](https://github.com/openai/whisper)
[![Ollama](https://img.shields.io/badge/Ollama-Qwen2.5-purple.svg)](https://ollama.com)

</div>

---

## ✨ 特性

- 🎬 **全流程自动化** — 频道监控 → 1080p 下载 → 语音转写 → 翻译 → 字幕烧录
- 🔍 **两阶段架构** — Prepare（准备）+ Burn（烧录），支持中间审查与编辑
- 🤖 **本地大模型翻译** — 基于 Ollama + Qwen2.5，无需 API Key，数据不出本机
- 🎯 **VAD 时间修正** — Silero VAD 修正 Whisper 时间戳偏移，解决 BGM 段字幕提前问题
- 🧹 **幻觉去重** — 自动检测并删除 Whisper 重复幻觉段
- 📝 **翻译审查** — 中英对照 review.txt，编辑后自动回写缓存
- 📡 **多频道支持** — 同时监控多个 YouTube 频道，自动去重
- 🔗 **单视频处理** — `--video` 参数直接处理任意视频 URL

---

## 🏗️ 架构

```mermaid
flowchart LR
    A[YouTube 频道] -->|yt-dlp| B[视频下载<br/>1080p MP4]
    B -->|Whisper| C[语音转写<br/>英文 SRT]
    C -->|Silero VAD| D[时间戳修正]
    D -->|前缀去重| E[幻觉段清除]
    E -->|Ollama Qwen2.5| F[批量翻译<br/>英→中]
    F --> G[review.txt<br/>中英对照]
    G -->|用户审查/编辑| H[回写缓存]
    H -->|FFmpeg| I[字幕烧录<br/>输出视频]

    style A fill:#ff4444,color:#fff
    style I fill:#44bb44,color:#fff
    style G fill:#ffaa00,color:#fff
```

---

## 🛠️ 技术栈

| 类别 | 技术 | 用途 |
|------|------|------|
| 语言 | Python 3.10+ | 主程序 |
| 语音转写 | [OpenAI Whisper](https://github.com/openai/whisper) | 英文语音识别 |
| 翻译引擎 | [Ollama](https://ollama.com) + Qwen2.5 | 本地大模型翻译 |
| 视频下载 | [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube 视频下载 |
| 语音检测 | [Silero VAD](https://github.com/snakers4/silero-vad) | 语音活动检测，修正时间戳 |
| 字幕烧录 | [FFmpeg](https://ffmpeg.org) | ASS 字幕渲染 + 视频编码 |
| 配置管理 | python-dotenv | 环境变量加载 |

---

## 📦 安装

### 前置依赖

1. **Python 3.10+**
2. **FFmpeg** — [下载地址](https://www.gyan.dev/ffmpeg/builds/)
3. **Ollama** — [下载地址](https://ollama.com/download)
4. **yt-dlp** — `pip install yt-dlp` 或 [下载 exe](https://github.com/yt-dlp/yt-dlp/releases)

### 步骤

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/VlogTrans.git
cd VlogTrans

# 2. 创建虚拟环境
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
pip install torch torchaudio silero-vad

# 4. 安装 Ollama 翻译模型
ollama pull qwen2.5

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的配置

# 6. 准备 YouTube Cookies（下载 1080p 必须）
# 在浏览器隐私窗口中登录 YouTube
# 访问 https://www.youtube.com/robots.txt
# 使用浏览器插件导出 cookies 为 Netscape 格式
# 保存为 www.youtube.com_cookies.txt
```

---

## ⚙️ 配置

编辑 `.env` 文件进行配置：

| 配置项 | 必填 | 说明 | 示例 |
|--------|:----:|------|------|
| `YOUTUBE_CHANNEL_URLS` | ✅ | 监控的频道 URL（逗号分隔） | `https://youtube.com/@sydneyserena,https://youtube.com/@leahhalton` |
| `FFMPEG_PATH` | ✅ | FFmpeg 可执行文件路径 | `D:\ffmpeg\bin\ffmpeg.exe` |
| `YT_DLP_PATH` | ✅ | yt-dlp 路径 | `D:\yt-dlp.exe` |
| `DEESEEK_MODEL` | ✅ | Ollama 翻译模型 | `qwen2.5` |
| `WHISPER_MODEL` | ✅ | Whisper 模型 | `medium.en` |
| `YOUTUBE_COOKIES_PATH` | ✅ | Cookies 文件路径 | `www.youtube.com_cookies.txt` |
| `OLLAMA_HOST` | | Ollama 服务地址 | `http://127.0.0.1:11434` |
| `OLLAMA_DISABLE_PROXY` | | 禁用 Ollama 代理 | `true` |
| `HTTP_PROXY` | | HTTP 代理 | `http://127.0.0.1:7897` |
| `HTTPS_PROXY` | | HTTPS 代理 | `http://127.0.0.1:7897` |

---

## 🚀 使用

### 基本流程

```bash
# Step 1: 准备阶段 — 下载视频 + 转写 + 翻译
python main.py --prepare

# Step 2: 审查翻译 — 编辑 data/cache/<video_id>/review.txt
#          修改中文翻译行（5空格缩进的行）

# Step 3: 烧录阶段 — 生成字幕 + 烧录到视频
python main.py --burn
```

### CLI 参数

| 参数 | 说明 |
|------|------|
| `--prepare` | 准备阶段：下载视频 → Whisper 转写 → VAD 修正 → 幻觉去重 → 翻译 → 生成 review.txt |
| `--burn` | 烧录阶段：回写 review.txt 修改 → 生成 SRT → FFmpeg 烧录字幕 |
| `--all` | 一键运行：prepare + burn，跳过审查 |
| `--video URL` | 处理单个视频 URL |

### 示例

```bash
# 监控频道，自动处理最新视频
python main.py --prepare

# 处理单个视频
python main.py --video https://youtu.be/dQw4w9WgXcQ

# 一键完成（跳过审查）
python main.py --all

# 审查后烧录
python main.py --burn
```

---

## 📂 项目结构

```
VlogTrans/
├── main.py                          # 主入口，CLI 参数解析与流程编排
├── config.py                        # 配置加载（.env → Settings）
├── .env.example                     # 配置模板
├── requirements.txt                 # Python 依赖
├── modules/
│   ├── radar/
│   │   └── radar.py                 # YouTube 频道监控与视频下载
│   ├── translator/
│   │   ├── translator.py            # 翻译调度（批量翻译）
│   │   └── backends/
│   │       └── ollama_backend.py    # Ollama API 调用与重试
│   ├── merger/
│   │   └── merger.py                # FFmpeg 字幕烧录
│   ├── audit/
│   │   └── audit.py                 # 审计模块
│   └── storage.py                   # 视频处理状态持久化
├── data/                            # 运行时数据（gitignore）
│   ├── videos/                      # 下载的原始视频
│   ├── subtitles/                   # 生成的 SRT 字幕
│   ├── cache/                       # 缓存（segments / translated / meta）
│   └── output/                      # 烧录后的输出视频
└── tests/                           # 单元测试
```

---

## 🔄 工作流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant P as Prepare
    participant R as Review
    participant B as Burn

    U->>P: python main.py --prepare
    P->>P: 下载 1080p 视频
    P->>P: Whisper 转写 + VAD 修正 + 幻觉去重
    P->>P: Qwen2.5 批量翻译
    P->>R: 生成 review.txt（中英对照）
    
    U->>R: 手动编辑 review.txt
    Note over R: 修改5空格缩进的中文行
    
    U->>B: python main.py --burn
    B->>B: 检测 review.txt 修改 → 回写 translated.json
    B->>B: 生成双语 SRT
    B->>B: FFmpeg 烧录字幕
    B->>U: 输出带中文字幕的视频
```

### 缓存机制

| 缓存文件 | 内容 | 失效条件 |
|----------|------|----------|
| `meta.json` | 视频标题 | 手动删除 |
| `segments.json` | Whisper 转写结果 | `WHISPER_MODEL` 变更 |
| `translated.json` | 翻译结果 | `DEESEEK_MODEL` 或 `batch_size` 变更 |
| `review.txt` | 中英对照审查文件 | 手动编辑 |

---

## ⚠️ 已知限制

| 限制 | 说明 |
|------|------|
| 翻译串位 | Whisper 按时间切片分段，长句可能被拆开导致翻译串位，需手动审查 |
| Cookies 有效期 | YouTube cookies 几小时后过期，需从隐私窗口重新导出 |
| CPU 转写较慢 | medium.en 模型在 CPU 上约 20 分钟/15 分钟视频，建议使用 GPU |
| 仅支持英文 | 当前仅支持英文转写 + 中译，其他语言需调整 Whisper 模型和翻译 prompt |

---

## 📄 License

MIT License
