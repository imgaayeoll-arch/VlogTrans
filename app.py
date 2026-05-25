import sys
import sysconfig
_site_pkgs = sysconfig.get_path("purelib")
if _site_pkgs not in sys.path:
    sys.path.insert(0, _site_pkgs)

import os
import subprocess
import threading
import time
import streamlit as st
from config import settings
from modules.ui_helpers import (
    scan_cache_videos,
    scan_output_videos,
    count_processed_ids,
    remove_processed_id,
    check_ffmpeg_status,
    check_ytdlp_status,
    check_deno_status,
    check_firefox_cookies_status,
    check_ollama_status,
    check_cookies_file_status,
    update_env_channel_urls,
    load_video_review_data,
    save_review_data,
    find_video_for_id,
    find_srt_for_id,
)

st.set_page_config(page_title="VlogTrans", page_icon="🎬", layout="wide")

tab1, tab2, tab3, tab4 = st.tabs(["概览", "配置检查", "任务运行", "翻译审查"])

with tab1:
    st.header("概览")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("频道数量", len(settings.youtube_channel_urls))
    with col2:
        cache_videos = scan_cache_videos(settings.cache_path)
        st.metric("缓存视频", len(cache_videos))
    with col3:
        output_videos = scan_output_videos(settings.output_path)
        st.metric("已输出视频", len(output_videos))
    with col4:
        processed_count = count_processed_ids(settings.db_path)
        st.metric("已处理 ID", processed_count)

    st.divider()

    st.subheader("最近输出")
    if output_videos:
        for v in output_videos:
            modified_str = v["modified"].strftime("%Y-%m-%d %H:%M")
            st.text(f"{v['name']}  ({v['size_mb']} MB, {modified_str})")
    else:
        st.info("暂无输出视频")

    st.divider()

    st.subheader("已处理视频")
    if processed_count > 0:
        import json
        from pathlib import Path

        db_file = Path(settings.db_path)
        try:
            processed_ids = json.loads(db_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            processed_ids = []

        for vid in processed_ids:
            cols = st.columns([3, 1])
            with cols[0]:
                st.text(vid)
            with cols[1]:
                if st.button("重新处理", key=f"reprocess_{vid}"):
                    remove_processed_id(settings.db_path, vid)
                    st.success(f"已移除 {vid}，下次 burn 时将重新处理")
                    st.rerun()
    else:
        st.info("暂无已处理视频")

with tab2:
    st.header("配置检查")

    st.subheader("依赖状态")

    col1, col2 = st.columns(2)

    with col1:
        ffmpeg = check_ffmpeg_status(settings.ffmpeg_path)
        if ffmpeg["available"]:
            st.success(f"FFmpeg ✅ — {ffmpeg['version']}")
        else:
            st.error("FFmpeg ❌ — 未找到")

        ytdlp = check_ytdlp_status(settings.yt_dlp_path)
        if ytdlp["available"]:
            channel_label = f" ({ytdlp['channel']})" if ytdlp["channel"] else ""
            st.success(f"yt-dlp ✅ — {ytdlp['version']}{channel_label}")
        else:
            st.error("yt-dlp ❌ — 未找到")

        deno = check_deno_status()
        if deno["available"]:
            st.success(f"deno ✅ — {deno['version']}")
        else:
            st.warning("deno ⚠️ — 未找到（yt-dlp 解 JS 挑战需要 deno）")

        firefox = check_firefox_cookies_status()
        if firefox["available"]:
            st.success(f"Firefox cookies ✅ — {firefox['profile_count']} 个 profile")
        else:
            st.warning("Firefox cookies ⚠️ — 未检测到 Firefox profile")

    with col2:
        ollama = check_ollama_status()
        if ollama["running"]:
            model_status = "✅ 模型就绪" if ollama["model_ready"] else "⚠️ 模型未就绪"
            model_list = ", ".join(ollama["models"][:5])
            if len(ollama["models"]) > 5:
                model_list += f" 等 {len(ollama['models'])} 个"
            st.success(f"Ollama ✅ — {model_status}\n\n模型: {model_list}")
        else:
            st.error("Ollama ❌ — 未运行")

        st.metric("Whisper 模型", settings.whisper_model)

        cookies_file = check_cookies_file_status(settings.youtube_cookies_path)
        if cookies_file["exists"]:
            st.success(f"Cookies 文件 ✅ — {cookies_file['size_kb']} KB")
        elif settings.youtube_cookies_path:
            st.warning(f"Cookies 文件 ⚠️ — 路径不存在: {cookies_file['path']}")
        else:
            st.info("Cookies 文件 — 未配置（使用 Firefox 浏览器 cookies）")

        http_proxy = os.environ.get("HTTP_PROXY", os.environ.get("http_proxy", ""))
        https_proxy = os.environ.get("HTTPS_PROXY", os.environ.get("https_proxy", ""))
        proxy_info = https_proxy or http_proxy or "未设置"
        st.metric("代理", proxy_info)

    st.divider()

    st.subheader("频道配置")
    current_urls = "\n".join(settings.youtube_channel_urls)
    new_urls_text = st.text_area(
        "YOUTUBE_CHANNEL_URLS（每行一个）",
        value=current_urls,
        height=120,
        key="channel_urls_editor",
    )

    if st.button("保存频道配置"):
        new_urls = [u.strip() for u in new_urls_text.strip().splitlines() if u.strip()]
        if new_urls:
            update_env_channel_urls(settings.config_source, new_urls)
            st.success("配置已更新！请重启 Streamlit 使配置生效。")
        else:
            st.error("至少需要一个频道 URL")

    st.divider()

    st.subheader("其他配置（只读）")
    readonly_cols = st.columns(3)
    with readonly_cols[0]:
        st.text(f"下载路径: {settings.download_path}")
        st.text(f"缓存路径: {settings.cache_path}")
        st.text(f"输出路径: {settings.output_path}")
    with readonly_cols[1]:
        st.text(f"字幕路径: {settings.subtitle_path}")
        st.text(f"数据库: {settings.db_path}")
        st.text(f"翻译后端: {settings.translation_backend}")
    with readonly_cols[2]:
        st.text(f"Ollama 地址: {settings.ollama_host}")
        st.text(f"翻译模型: {settings.translation_model}")
        st.text(f"yt-dlp 路径: {settings.yt_dlp_path}")

with tab3:
    st.header("任务运行")

    if "running_task" not in st.session_state:
        st.session_state.running_task = None
        st.session_state.task_process = None
        st.session_state.log_lines = []
        st.session_state.task_start_time = None
        st.session_state.task_thread = None

    if st.session_state.task_process is not None:
        poll_result = st.session_state.task_process.poll()
        if poll_result is not None:
            st.session_state.running_task = None
            st.session_state.task_process = None
            if st.session_state.task_thread is not None:
                st.session_state.task_thread.join(timeout=2)
                st.session_state.task_thread = None

    is_running = st.session_state.running_task is not None

    def start_task(cmd_args, task_name):
        python_exe = sys.executable
        full_cmd = [python_exe, "main.py"] + cmd_args
        st.session_state.log_lines = []
        st.session_state.running_task = task_name
        st.session_state.task_start_time = time.time()

        process = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)) or None,
        )
        st.session_state.task_process = process

        def read_output():
            try:
                for line in process.stdout:
                    st.session_state.log_lines.append(line.rstrip())
            except Exception:
                pass

        thread = threading.Thread(target=read_output, daemon=True)
        thread.start()
        st.session_state.task_thread = thread
        st.rerun()

    if is_running:
        st.warning(f"任务运行中: {st.session_state.running_task}")
        elapsed = time.time() - st.session_state.task_start_time if st.session_state.task_start_time else 0
        st.metric("已运行时间", f"{elapsed:.0f} 秒")

        log_container = st.empty()
        log_text = "\n".join(st.session_state.log_lines[-200:])
        log_container.code(log_text, language="log")

        col_stop, _ = st.columns([1, 3])
        with col_stop:
            if st.button("停止任务", type="secondary"):
                if st.session_state.task_process is not None:
                    st.session_state.task_process.terminate()
                    st.session_state.running_task = None
                    st.session_state.task_process = None
                    st.session_state.log_lines.append("\n--- 任务已被用户停止 ---")
                    st.rerun()

        if st.session_state.task_process is not None:
            poll_result = st.session_state.task_process.poll()
            if poll_result is not None:
                st.session_state.running_task = None
                exit_code = st.session_state.task_process.returncode
                st.session_state.task_process = None
                total_time = time.time() - st.session_state.task_start_time if st.session_state.task_start_time else 0
                if exit_code == 0:
                    st.success(f"任务完成！退出码: {exit_code}，耗时: {total_time:.1f} 秒")
                else:
                    st.error(f"任务失败！退出码: {exit_code}，耗时: {total_time:.1f} 秒")
                st.rerun()
            else:
                time.sleep(1)
                st.rerun()
    else:
        if st.session_state.log_lines:
            exit_code = None
            total_time = time.time() - st.session_state.task_start_time if st.session_state.task_start_time else 0
            st.success(f"上次任务完成，耗时: {total_time:.1f} 秒")

            with st.expander("查看上次日志"):
                st.code("\n".join(st.session_state.log_lines), language="log")

            if st.button("清除日志"):
                st.session_state.log_lines = []
                st.session_state.task_start_time = None
                st.rerun()

        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            if st.button("准备阶段 (--prepare)", disabled=is_running, use_container_width=True):
                start_task(["--prepare"], "prepare")
        with col2:
            if st.button("烧录阶段 (--burn)", disabled=is_running, use_container_width=True):
                start_task(["--burn"], "burn")

        st.divider()
        st.subheader("单视频处理")
        video_url = st.text_input("视频 URL", placeholder="https://youtu.be/xxxxx", key="video_url_input")
        if st.button("单视频处理 (--video)", disabled=is_running, use_container_width=True):
            if not video_url:
                st.error("请输入视频 URL")
            else:
                start_task(["--video", video_url], f"video: {video_url}")

with tab4:
    st.header("翻译审查")

    cache_videos = scan_cache_videos(settings.cache_path)
    if not cache_videos:
        st.info("暂无缓存视频。请先运行准备阶段。")
    else:
        options = []
        for v in cache_videos:
            label = f"📝 {v['id']}"
            if v["title"]:
                label += f" ({v['title'][:50]})"
            if not v["has_segments"] or not v["has_translated"]:
                label += " ⚠️ 缓存不完整"
            options.append((label, v["id"]))

        selected_label = st.selectbox(
            "选择视频",
            options=[lbl for lbl, _ in options],
            index=None,
            placeholder="请选择...",
        )
        selected_id = None
        for lbl, vid in options:
            if lbl == selected_label:
                selected_id = vid
                break

        if selected_id:
            review_data = load_video_review_data(settings.cache_path, selected_id)

            if review_data is None:
                srt_path = find_srt_for_id(settings.subtitle_path, selected_id)
                if srt_path:
                    st.warning("该视频已烧录，缓存已清理，无法编辑翻译")
                    with open(srt_path, "r", encoding="utf-8") as f:
                        srt_content = f.read()
                    with st.expander("查看 SRT 字幕（只读）"):
                        st.code(srt_content, language="srt")
                else:
                    st.error("缓存不完整且未找到 SRT 文件，请重新运行 --prepare")
            else:
                video_path = find_video_for_id(settings.download_path, selected_id)
                if video_path:
                    st.video(video_path)

                segments = review_data["segments"]
                translations = review_data["translations"]
                segment_meta = review_data["segment_meta"]
                translation_meta = review_data["translation_meta"]

                st.subheader(f"翻译编辑 ({len(segments)} 段)")

                import pandas as pd

                df_data = {
                    "序号": list(range(1, len(segments) + 1)),
                    "英文原文": [s["text"] for s in segments],
                    "中文翻译": translations,
                }
                df = pd.DataFrame(df_data)

                edited_df = st.data_editor(
                    df,
                    num_rows="fixed",
                    use_container_width=True,
                    column_config={
                        "序号": st.column_config.NumberColumn(disabled=True, width="small"),
                        "英文原文": st.column_config.TextColumn(width="large"),
                        "中文翻译": st.column_config.TextColumn(width="large"),
                    },
                    key=f"review_editor_{selected_id}",
                )

                if st.button("保存翻译", key=f"save_review_{selected_id}"):
                    new_english = edited_df["英文原文"].tolist()
                    new_chinese = edited_df["中文翻译"].tolist()

                    updated_segments = []
                    for i, seg in enumerate(segments):
                        new_seg = dict(seg)
                        new_seg["text"] = new_english[i]
                        updated_segments.append(new_seg)

                    english_changed = any(
                        s["text"] != ne for s, ne in zip(segments, new_english)
                    )

                    result = save_review_data(
                        settings.cache_path,
                        selected_id,
                        updated_segments,
                        new_chinese,
                        english_edited=updated_segments if english_changed else None,
                        segment_meta=segment_meta,
                        translation_meta=translation_meta,
                    )

                    if result["success"]:
                        st.success(result["message"])
                    else:
                        st.error(result["message"])
