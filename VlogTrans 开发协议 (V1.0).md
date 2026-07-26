# VlogTrans 开发协议 (V1.0)

> 适用版本：VlogTrans V2.0 | 制定日期：2026-07 | [V1.0 变更记录见底部](#版本历史)

## 1. 核心原则
- **模块自治**：modules 文件夹下的代码互不干扰。
- **配置隔离**：所有 API、路径、模型参数统一从 config.py 读取。
- **测试先行**：每完成一个子函数，必须生成对应的 pytest 或 unittest 脚本。

## 2. 编码契约
- **命名规范**：函数名必须清晰描述意图（如：fetch_youtube_metadata）。
- **异常处理**：禁止使用空的 `except:`，必须捕获特定错误并记录日志。
- **日志输出**：使用清晰的进度条（tqdm）和带颜色的日志（如：[SUCCESS] [ERROR]）。

## 3. 自动化流程规则
1. Radar — 检查并下载视频（记录 ID，支持多频道 + Cookie 回退链）
2. main.py — Faster-Whisper 转写（CTranslate2 加速）→ Silero VAD 时间戳修正 → 幻觉去重
3. Translator — DeepSeek API（主）→ Ollama（回退）双后端链，自动 failover
4. Merger — 生成双语 SRT → FFmpeg 硬件加速合成字幕（NVENC / AMF / libx264）
5. Audit — 完成后清理临时文件

## 4. 单元测试要求
- 每次修改后，运行 `python -m pytest tests/ -v` 确保全部通过。
- 必须包含 Mock 测试，模拟 API 掉线、限流、空返回等情况。
- **多后端测试**：翻译后端链使用 `monkeypatch` 隔离配置（`TRANSLATION_BACKENDS_ORDER`），不可依赖真实的 `.env`。
- 新增模块（radar / backends / merger）必须有对应测试文件。

---

## 5. 翻译后端链与 Fallback 机制
- `TRANSLATION_BACKENDS_ORDER` 定义后端优先级（逗号分隔，如 `deepseek,ollama`）。
- 链中第一个通过 `health_check()` 的后端成为主翻译线路。
- 翻译失败时自动切换到下一个后端，所有后端均失败则抛出 `RuntimeError`。
- 添加新后端只需：
  1. 在 `modules/translator/backends/` 下新建 `xxx_backend.py`
  2. 实现 `health_check()` 和 `translate(segments, batch_size)` 两个方法
  3. 在 `backends/__init__.py` 和 `translator.py` 的 `_BACKENDS` 字典中注册
- 当前可用后端：
  | 后端 | 类型 | 模型 | fallback 策略 |
  |------|------|------|---------------|
  | DeepSeekBackend | 云端 API | `deepseek-chat` | 限流/服务异常自动降级到 Ollama |
  | OllamaBackend | 本地 | `qwen2.5` | 最终兜底，本地不可用则整体失败 |

---

## 6. 缓存与审查机制
- **缓存层级**：
  | 文件 | 内容 | 失效条件 |
  |------|------|----------|
  | `meta.json` | 视频标题 | 手动删除 |
  | `segments.json` | 转写结果 | `WHISPER_MODEL` 变更 |
  | `translated.json` | 翻译结果 | 模型变更或 `batch_size` 变更 |
  | `review.txt` | 中英对照（人工审查用） | 手动编辑 |
- **审查流程**：`--prepare` 生成 `review.txt` → 用户编辑中文行（5 空格缩进）→ `--burn` 自动检测 `review.txt` 修改时间并回写缓存。
- **回写安全性**：`review.txt` 行数与 `translated.json` 不一致时拒绝回写，记录 WARNING。

---

## 7. Streamlit 可视化面板规范
- `app.py` 为独立入口，通过 `subprocess.Popen` 调用 `main.py`，不直接引用其内部函数。
- 面板四大模块（Tab）：
  | Tab | 功能 |
  |-----|------|
  | 概览 | 频道数、缓存/输出视频数、已处理 ID 统计 |
  | 配置检查 | 依赖状态（FFmpeg / yt-dlp / deno / Ollama / cookies / 代理）|
  | 任务运行 | 启动/停止 prepare / burn / 单视频处理，实时日志流 |
  | 翻译审查 | 选择缓存视频 → 嵌入播放 → DataFrame 编辑中英文 → 保存回写 |
- UI 辅助函数统一放在 `modules/ui_helpers.py`，不可在 `app.py` 中直接操作文件或环境变量。
- 频道配置编辑通过 `update_env_channel_urls()` 写回 `.env` 文件。

---

## 8. 配置管理补充
- HuggingFace 模型下载：通过 `HF_ENDPOINT` 设置镜像（国内用户建议 `https://hf-mirror.com`），代码中 `_setup_hf_env()` 负责注入环境变量并绕过代理。
- Cookie 回退链：Firefox 浏览器 cookies → 手动 cookies 文件 → 无 cookies。
- 代理：`HTTP_PROXY` / `HTTPS_PROXY` 同时作用于 yt-dlp 和 httpx，Ollama 本地请求通过 `OLLAMA_DISABLE_PROXY` 跳过代理。

---

## 9. Git 提交规范
- **Conventional Commits**：所有 commit message 遵循 `type(scope): description` 格式。
  | type | 用途 | 示例 |
  |------|------|------|
  | `feat` | 新功能 | `feat: add DeepSeek translation backend` |
  | `fix` | Bug 修复 | `fix: radar cookie fallback loop` |
  | `docs` | 文档变更 | `docs: update README for faster-whisper` |
  | `refactor` | 重构（不改变功能） | `refactor: extract cookie logic to method` |
  | `test` | 测试相关 | `test: add fallback chain mock tests` |
  | `chore` | 杂项（依赖/构建/工具） | `chore: update yt-dlp to latest` |
- **提交粒度**：一次 commit 只做一件事，禁止将无关变更混入同一提交。
- **禁止提交**：`.env`、`__pycache__/`、`data/`、`*.cookies.txt`、含真实 API Key 的任何文件。推送前执行 `git diff --staged` 确认。
- **分支策略**：`main` 为稳定分支；功能开发在 feature 分支完成，通过 PR 合并。

---

## 10. 安全规范
- **密钥管理**：
  - API Key（DeepSeek 等）**仅**存在于 `.env`，绝不可写入 `.env.example`、源码或注释。
  - `.env.example` 中敏感字段值为占位符（如 `your-deepseek-api-key-here`）。
  - `.gitignore` 必须包含 `.env`，确保不会被意外提交。
- **泄露应急**：一旦发现 Key 被推送到 GitHub：
  1. 立即在服务商后台（DeepSeek / GitHub Settings）轮换该 Key
  2. 使用 `git filter-branch` 或 `bfg` 清理历史
  3. 检查是否有未授权调用记录
- **依赖审计**：定期检查 `requirements.txt` 中依赖的安全公告，避免已知漏洞。
- **输入校验**：外部输入（YouTube URL、频道名）必须校验格式，防止命令注入。

---

## 11. 代码风格与类型注解
- **类型注解**：所有公开函数必须使用 Python 3.10+ type hints。

  ```python
  # ✅ 正确
  def transcribe_with_whisper(model: WhisperModel, audio_path: Path) -> list[dict]:
      """用 Faster-Whisper 将音频转写为字幕段列表。

      Args:
          model: 已加载的 Faster-Whisper 模型实例。
          audio_path: 16kHz 单声道 WAV 文件路径。

      Returns:
          字幕段列表，每段含 start / end / text 字段。
      """
      ...

  # ❌ 错误：无类型注解，无 docstring
  def transcribe_with_whisper(model, audio_path):
      ...
  ```
- **Docstring**：所有公开函数必须有 docstring，至少包含一行功能描述；参数超过 2 个或有复杂返回值时，需写明参数和返回值说明。
- **导入顺序**：标准库 → 第三方库 → 项目内部模块，每组之间空一行。
- **行宽**：推荐 ≤ 100 字符，最大 120 字符。
- **字符串编码**：读写文件统一指定 `encoding="utf-8"`，不得依赖系统默认编码。

---

## 版本历史
| 版本 | 日期 | 变更 |
|------|------|------|
| V1.0 | 2025-05 | 初始版本：Whisper + Ollama 单后端架构 |
| V2.0 | 2026-07 | 迁移 Faster-Whisper；新增 DeepSeek 后端与 fallback 链；新增 Streamlit UI；新增缓存审查机制；补充 Cookie/代理/镜像配置规范 |
| V2.1 | 2026-07 | 新增：Git 提交规范（Conventional Commits）、安全规范（密钥管理 / 泄露应急 / 依赖审计）、代码风格与类型注解规范 |
