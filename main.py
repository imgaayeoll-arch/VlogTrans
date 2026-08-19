import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from faster_whisper import WhisperModel
import torch
from config import settings
from modules.merger import SubtitleMerger
from modules.progress import terminal_progress
from modules.radar.radar import YoutubeRadar
from modules.storage import VideoStorage
from modules.translator.translator import (
    batch_translate,
    check_translation_backends,
    get_current_model_name,
)
from tqdm import tqdm


def _setup_hf_env():
    """Configure HuggingFace mirror and bypass proxy for model downloads."""
    import os
    os.environ["HF_ENDPOINT"] = settings.hf_endpoint
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)


def setup_ffmpeg_path():
    ffmpeg_dir = Path(settings.ffmpeg_path).parent
    ffmpeg_dir_str = str(ffmpeg_dir.resolve())
    current_path = os.environ.get("PATH", "")
    if ffmpeg_dir_str not in current_path:
        os.environ["PATH"] = ffmpeg_dir_str + os.pathsep + current_path
    venv_scripts = str(Path(__file__).parent / ".venv" / "Scripts")
    if venv_scripts not in current_path:
        os.environ["PATH"] = venv_scripts + os.pathsep + os.environ.get("PATH", "")


def check_ffmpeg():
    try:
        result = subprocess.run(
            [settings.ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0] if result.stdout else "unknown"
            logger.info(f"✓ FFmpeg 已就绪: {version_line}")
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as e:
        logger.warning(f"FFmpeg 检测异常: {e}")

    logger.error("=" * 60)
    logger.error("✗ FFmpeg 未安装或路径不正确")
    logger.error("  当前使用的路径: " + settings.ffmpeg_path)
    logger.error("")
    logger.error("解决方案：")
    logger.error("  方案1 (推荐): 使用 winget 安装")
    logger.error("    > winget install ffmpeg")
    logger.error("")
    logger.error("  方案2: 手动下载安装")
    logger.error("    > 下载地址: https://ffmpeg.org/download.html")
    logger.error("    > 安装后确保 ffmpeg.exe 在系统 PATH 中")
    logger.error("")
    logger.error("  方案3: 设置环境变量")
    logger.error("    > 在 .env 文件中添加: FFMPEG_PATH=C:/path/to/ffmpeg.exe")
    logger.error("=" * 60)
    return False


logger = logging.getLogger("VlogTrans")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
logger.addHandler(handler)


def ensure_directories():
    Path(settings.download_path).mkdir(parents=True, exist_ok=True)
    Path(settings.subtitle_path).mkdir(parents=True, exist_ok=True)
    Path(settings.output_path).mkdir(parents=True, exist_ok=True)
    Path(settings.cache_path).mkdir(parents=True, exist_ok=True)


def _cache_dir(video_id):
    return Path(settings.cache_path) / video_id


def _load_segments_cache(video_id):
    cache_file = _cache_dir(video_id) / "segments.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if data.get("whisper_model") != settings.whisper_model:
            logger.info(f"Whisper 模型已变更 ({data.get('whisper_model')} → {settings.whisper_model})，重新转录")
            return None
        logger.info(f"✓ 从缓存加载转录结果: {cache_file}")
        return data.get("segments")
    except (json.JSONDecodeError, KeyError):
        logger.warning(f"缓存文件损坏，将重新转录: {cache_file}")
        return None


def _save_segments_cache(video_id, segments):
    cache_file = _cache_dir(video_id) / "segments.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "whisper_model": settings.whisper_model,
        "segments": segments,
    }
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"✓ 转录结果已缓存: {cache_file}")


def _load_translated_cache(video_id, batch_size):
    cache_file = _cache_dir(video_id) / "translated.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        actual_model = get_current_model_name()
        if data.get("model") != actual_model:
            logger.info(f"翻译模型已变更 ({data.get('model')} → {actual_model})，重新翻译")
            return None
        if data.get("batch_size") != batch_size:
            logger.info(f"batch_size 已变更 ({data.get('batch_size')} → {batch_size})，重新翻译")
            return None
        logger.info(f"✓ 从缓存加载翻译结果: {cache_file}")
        return data.get("translations")
    except (json.JSONDecodeError, KeyError):
        logger.warning(f"缓存文件损坏，将重新翻译: {cache_file}")
        return None


def _save_translated_cache(video_id, translations, batch_size):
    cache_file = _cache_dir(video_id) / "translated.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "model": get_current_model_name(),
        "batch_size": batch_size,
        "translations": translations,
    }
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"✓ 翻译结果已缓存: {cache_file}")


def _save_meta_cache(video_id, title):
    cache_file = _cache_dir(video_id) / "meta.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    data = {"title": title}
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_meta_cache(video_id):
    cache_file = _cache_dir(video_id) / "meta.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return data.get("title")
    except (json.JSONDecodeError, KeyError):
        return None


def _load_segments_cache_raw(video_id):
    cache_file = _cache_dir(video_id) / "segments.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return data.get("segments")
    except (json.JSONDecodeError, KeyError):
        return None


def _load_translated_cache_raw(video_id):
    cache_file = _cache_dir(video_id) / "translated.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return data.get("translations")
    except (json.JSONDecodeError, KeyError):
        return None


def _save_review_file(video_id, segments, translated_texts):
    review_file = _cache_dir(video_id) / "review.txt"
    lines = []
    for i, (seg, zh) in enumerate(zip(segments, translated_texts), 1):
        lines.append(f"[{i:03d}] {seg['text']}")
        lines.append(f"     {zh}")
        lines.append("")
    review_file.write_text("\n".join(lines), encoding="utf-8")
    return review_file


def _parse_review_file(video_id):
    review_file = _cache_dir(video_id) / "review.txt"
    if not review_file.exists():
        return None
    translations = []
    for line in review_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        # 跳过空行与英文行（[NNN] 开头），其余任意缩进（空格/tab）视为译文
        if not stripped or re.match(r"^\[\d+\]", stripped):
            continue
        translations.append(stripped)
    return translations if translations else None


def _sync_review_to_cache(video_id):
    review_file = _cache_dir(video_id) / "review.txt"
    translated_file = _cache_dir(video_id) / "translated.json"
    if not review_file.exists() or not translated_file.exists():
        return
    if review_file.stat().st_mtime <= translated_file.stat().st_mtime:
        return
    translations = _parse_review_file(video_id)
    if not translations:
        return
    try:
        data = json.loads(translated_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return
    if len(translations) != len(data.get("translations", [])):
        logger.warning(
            f"review.txt 行数 ({len(translations)}) 与 translated.json ({len(data.get('translations', []))}) 不一致，跳过回写"
        )
        return
    data["translations"] = translations
    translated_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"✓ 已从 review.txt 回写翻译修改: {translated_file}")


def _cleanup_cache(video_id):
    cache = _cache_dir(video_id)
    if cache.exists():
        shutil.rmtree(cache)
        logger.info(f"✓ 已清理缓存目录: {cache}")


def sanitize_filename(value, fallback):
    cleaned = "".join(c if c.isalnum() or c in " -_." else "_" for c in (value or ""))
    cleaned = cleaned.strip().strip("._-")
    return cleaned[:180] or fallback


def _emit_progress(data: dict) -> None:
    """输出进度事件到 stdout，以 >>>PROGRESS: 前缀标记供 Streamlit UI 解析。

    仅在 stdout 为管道（被 Streamlit 子进程消费）时输出；终端直跑时跳过，
    避免与 tqdm 进度条混在一起造成噪音。
    """
    if sys.stdout.isatty():
        return
    line = ">>>PROGRESS:" + json.dumps(data, ensure_ascii=False)
    print(line, flush=True)


def format_timestamp(seconds):
    milliseconds = int(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600 * 1000)
    minutes, remainder = divmod(remainder, 60 * 1000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def extract_audio(video_path, audio_path):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(audio_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg 执行失败: {e.stderr}")
        raise
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg 处理超时（超过 5 分钟）")
        raise
    return str(audio_path)


def transcribe_with_whisper(model, audio_path):
    logger.info("Transcribing audio with Faster-Whisper...")
    segments_iter, info = model.transcribe(
        str(audio_path),
        language="en",
        task="transcribe",
        beam_size=5,
        condition_on_previous_text=False,
        vad_filter=False,
    )
    logger.info(
        f"Detected language: {info.language} (probability: {info.language_probability:.2f}), "
        f"duration: {info.duration:.1f}s"
    )
    segments = []
    with terminal_progress(total=info.duration, desc="转录", unit="s") as bar:
        last = 0.0
        for segment in segments_iter:
            segments.append({
                "start": format_timestamp(segment.start),
                "end": format_timestamp(segment.end),
                "text": segment.text.strip(),
            })
            bar.update(segment.end - last)
            last = segment.end
        if info.duration:
            bar.update(info.duration - last)
    return segments


def _parse_timestamp(ts):
    parts = ts.replace(",", ".").split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def _vad_adjust_segments(segments, audio_path):
    try:
        vad_model, vad_utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
    except Exception as e:
        logger.warning(f"VAD model load failed, skipping VAD adjustment: {e}")
        return segments

    (get_speech_timestamps, _, read_audio, _, _) = vad_utils

    try:
        wav = read_audio(str(audio_path), sampling_rate=16000)
    except Exception as e:
        logger.warning(f"VAD read audio failed, skipping: {e}")
        return segments

    speech_ts = get_speech_timestamps(wav, vad_model, sampling_rate=16000,
                                      return_seconds=True)

    if not speech_ts:
        logger.info("VAD detected no speech in audio, keeping original segments")
        return segments

    adjusted = []
    for seg in segments:
        start_sec = _parse_timestamp(seg["start"])
        end_sec = _parse_timestamp(seg["end"])

        best_start = start_sec
        for st in speech_ts:
            speech_start = st["start"]
            speech_end = st["end"]
            if speech_start <= end_sec and speech_end >= start_sec:
                if speech_start > start_sec:
                    best_start = speech_start
                break

        if best_start > start_sec:
            gap = best_start - start_sec
            if gap > 0.3:
                logger.debug(
                    f"VAD adjusted [{seg['text'][:30]}] start "
                    f"{seg['start']} → +{gap:.1f}s"
                )
                from datetime import timedelta
                new_start = str(timedelta(seconds=best_start)).replace(".", ",")
                if "." not in new_start and "," not in new_start:
                    new_start += ",000"
                parts = new_start.split(":")
                if len(parts) == 3:
                    sec_parts = parts[2].split(",")
                    if len(sec_parts) == 2:
                        parts[2] = f"{int(sec_parts[0]):02d},{sec_parts[1][:3].ljust(3,'0')}"
                    new_start = ":".join(parts)
                seg = {**seg, "start": new_start}

        adjusted.append(seg)

    logger.info(f"VAD adjusted {sum(1 for a, b in zip(segments, adjusted) if a['start'] != b['start'])} segment start times")
    return adjusted


def _remove_hallucination_segments(segments):
    if len(segments) < 2:
        return segments

    remove_indices = set()
    for i in range(len(segments) - 1):
        cur_text = segments[i]["text"].strip()
        next_text = segments[i + 1]["text"].strip()
        if cur_text and next_text and next_text.startswith(cur_text):
            cur_end = _parse_timestamp(segments[i]["end"])
            next_start = _parse_timestamp(segments[i + 1]["start"])
            if next_start - cur_end < 3.0:
                remove_indices.add(i)
                logger.debug(f"Hallucination removed [{i}]: '{cur_text[:40]}' → prefix of [{i+1}]")

    if not remove_indices:
        return segments

    result = [s for idx, s in enumerate(segments) if idx not in remove_indices]
    logger.info(f"Removed {len(remove_indices)} hallucination segment(s)")
    return result


def _remove_empty_segments(segments):
    result = [s for s in segments if s.get("text", "").strip()]
    removed = len(segments) - len(result)
    if removed:
        logger.info(f"Removed {removed} empty segment(s)")
    return result


def cleanup_files(paths):
    for path in paths:
        try:
            if path and Path(path).exists():
                Path(path).unlink()
                logger.info(f"Removed temporary file: {path}")
        except Exception as exc:
            logger.warning(f"Failed to remove temp file {path}: {exc}")


def build_output_paths(video_title, video_id):
    safe_name = sanitize_filename(video_title, video_id)
    subtitle_name = f"{safe_name}-{video_id}.srt"
    output_name = f"{safe_name}-{video_id}.mp4"
    return (
        str(Path(settings.subtitle_path) / subtitle_name),
        str(Path(settings.output_path) / output_name),
    )


def prepare():
    ensure_directories()

    logger.info(f"Loading config from {settings.config_source}")

    if not check_ffmpeg():
        logger.error("FFmpeg 依赖检查失败，程序退出")
        return []

    setup_ffmpeg_path()

    backend_status = check_translation_backends()
    if not backend_status["available"]:
        logger.error("无可用翻译后端，程序退出")
        return []
    logger.info(f"翻译后端就绪: {' → '.join(backend_status['backends'])}")

    storage = VideoStorage()
    radar = YoutubeRadar()
    translator = batch_translate
    _setup_hf_env()
    whisper_model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
    batch_size = 5

    logger.info("Starting radar discovery for the latest 7 business days...")
    new_videos = radar.get_new_videos()

    videos_to_process = []
    for video in new_videos:
        if storage.is_processed(video["id"]):
            logger.info(f"Skipping already processed video {video['id']}")
            continue
        videos_to_process.append(video)

    if not videos_to_process:
        logger.info("未检测到新的待处理视频。")
        print("🎉没有需要准备的视频。")
        return []

    video_total = len(videos_to_process)
    _emit_progress({"type": "phase", "name": "prepare", "video_total": video_total})

    prepared_ids = []
    for idx, video in enumerate(tqdm(videos_to_process, desc="Preparing videos", unit="video", colour="green"), 1):
        video_id = video["id"]
        title = video.get("title") or video_id
        logger.info(f"Preparing video {video_id} - {title}")
        _emit_progress({"type": "video", "id": video_id, "title": title, "current": idx, "total": video_total})

        try:
            _save_meta_cache(video_id, title)

            logger.info("Step A: Downloading video...")
            _emit_progress({"type": "step", "name": "download"})
            downloaded_video_path = radar.download_video(video_id)
            if not downloaded_video_path:
                logger.warning(f"Download skipped for {video_id}.")
                _emit_progress({"type": "error", "step": "download", "message": "Download failed"})
                continue
            _emit_progress({"type": "step_done", "name": "download"})

            segments = _load_segments_cache(video_id)
            if segments is not None:
                logger.info("Step B: 跳过转录，使用缓存结果")
                _emit_progress({"type": "step", "name": "transcribe"})
                _emit_progress({"type": "step_done", "name": "transcribe"})
            else:
                logger.info("Step B: Extracting English subtitle segments with Whisper...")
                _emit_progress({"type": "step", "name": "transcribe"})
                audio_path = Path(settings.download_path) / f"{video_id}.wav"
                extract_audio(downloaded_video_path, audio_path)
                segments = transcribe_with_whisper(whisper_model, audio_path)

                if not segments:
                    raise RuntimeError("Whisper did not return any subtitle segments.")

                logger.info("Step B2: VAD adjusting segment start times...")
                segments = _vad_adjust_segments(segments, audio_path)

                logger.info("Step B3: Removing hallucination segments...")
                segments = _remove_hallucination_segments(segments)

                logger.info("Step B4: Removing empty segments...")
                segments = _remove_empty_segments(segments)

                _save_segments_cache(video_id, segments)
                cleanup_files([audio_path])
                _emit_progress({"type": "step_done", "name": "transcribe"})

            translated_texts = _load_translated_cache(video_id, batch_size)
            if translated_texts is not None and len(translated_texts) != len(segments):
                logger.warning(
                    f"翻译缓存行数 ({len(translated_texts)}) 与转录段数 ({len(segments)}) 不一致，重新翻译"
                )
                translated_texts = None
            if translated_texts is not None:
                logger.info("Step C: 跳过翻译，使用缓存结果")
                _emit_progress({"type": "step", "name": "translate"})
                _emit_progress({"type": "step_done", "name": "translate"})
            else:
                logger.info("Step C: Translating segments in batches...")
                _emit_progress({"type": "step", "name": "translate"})
                english_texts = [segment["text"] for segment in segments]
                total_batches = (len(english_texts) + batch_size - 1) // batch_size
                with terminal_progress(total=total_batches, desc="翻译", unit="批") as bar:
                    def cb(cur, tot):
                        _emit_progress({"type": "batch", "current": cur, "total": tot})
                        bar.n = cur
                        bar.refresh()

                    translated_texts = translator(english_texts, batch_size=batch_size,
                                                  progress_callback=cb)
                _save_translated_cache(video_id, translated_texts, batch_size)
                _emit_progress({"type": "step_done", "name": "translate"})

            review_file = _save_review_file(video_id, segments, translated_texts)
            prepared_ids.append(video_id)

            print(f"\n📝 视频 {video_id} 准备完成！")
            print(f"   中英对照: {review_file}")
            print(f"   翻译数据: {_cache_dir(video_id) / 'translated.json'}")
            print(f"   请审查后运行: python main.py --burn\n")

        except Exception as exc:
            logger.error(f"Failed preparing video {video_id}: {exc}", exc_info=True)
            _emit_progress({"type": "error", "step": "", "message": str(exc)[:100]})
            continue

    _emit_progress({"type": "phase_done", "name": "prepare"})
    print("🎉准备阶段完成！请审查翻译结果后运行 python main.py --burn")
    return prepared_ids


def burn():
    ensure_directories()

    logger.info(f"Loading config from {settings.config_source}")

    if not check_ffmpeg():
        logger.error("FFmpeg 依赖检查失败，程序退出")
        return

    setup_ffmpeg_path()

    storage = VideoStorage()
    merger = SubtitleMerger()

    cache_base = Path(settings.cache_path)
    if not cache_base.exists():
        logger.error("没有找到缓存目录，请先运行 python main.py --prepare")
        return

    video_ids = [d.name for d in cache_base.iterdir() if d.is_dir()]
    if not video_ids:
        logger.error("没有找到准备好的视频缓存，请先运行 python main.py --prepare")
        return

    burn_videos = []
    for video_id in video_ids:
        if storage.is_processed(video_id):
            logger.info(f"Skipping already processed video {video_id}")
            continue
        burn_videos.append(video_id)

    if not burn_videos:
        logger.info("所有缓存视频均已处理完毕，无需烧录。")
        return

    video_total = len(burn_videos)
    _emit_progress({"type": "phase", "name": "burn", "video_total": video_total})

    for idx, video_id in enumerate(burn_videos, 1):
        _sync_review_to_cache(video_id)

        title = _load_meta_cache(video_id) or video_id
        _emit_progress({"type": "video", "id": video_id, "title": title, "current": idx, "total": video_total})
        segments = _load_segments_cache_raw(video_id)
        translated_texts = _load_translated_cache_raw(video_id)
        if segments is None or translated_texts is None:
            logger.error(f"视频 {video_id} 缓存不完整，请重新运行 --prepare")
            _emit_progress({"type": "error", "step": "", "message": "缓存不完整"})
            continue

        logger.info(f"Burning subtitles for video {video_id} - {title}")

        downloaded_video_path = None
        for file in Path(settings.download_path).iterdir():
            if video_id in file.name and file.suffix.lower() in (".mp4", ".webm", ".mkv", ".avi", ".mov"):
                downloaded_video_path = str(file)
                break

        if not downloaded_video_path:
            logger.error(f"视频 {video_id} 的下载文件未找到，请重新运行 --prepare")
            _emit_progress({"type": "error", "step": "", "message": "视频文件未找到"})
            continue

        try:
            _emit_progress({"type": "step", "name": "srt"})
            subtitle_path, output_video_path = build_output_paths(title, video_id)
            merger.generate_bilingual_srt(segments, translated_texts, subtitle_path)
            _emit_progress({"type": "step_done", "name": "srt"})

            _emit_progress({"type": "step", "name": "burn"})
            merger.burn_subtitles(downloaded_video_path, subtitle_path, output_video_path)
            _emit_progress({"type": "step_done", "name": "burn"})

            logger.info("Marking video as processed and cleaning up cache...")
            storage.add_video(video_id)
            _cleanup_cache(video_id)

            print(f"✅ 视频 {video_id} 处理完成！输出: {output_video_path}")

        except Exception as exc:
            logger.error(f"Failed burning subtitles for {video_id}: {exc}", exc_info=True)
            _emit_progress({"type": "error", "step": "", "message": str(exc)[:100]})
            continue

    _emit_progress({"type": "phase_done", "name": "burn"})
    print("🎉烧录阶段完成！请在输出文件夹查收。")


def process_video(url):
    ensure_directories()

    logger.info(f"Loading config from {settings.config_source}")

    if not check_ffmpeg():
        logger.error("FFmpeg 依赖检查失败，程序退出")
        return

    setup_ffmpeg_path()

    backend_status = check_translation_backends()
    if not backend_status["available"]:
        logger.error("无可用翻译后端，程序退出")
        return
    logger.info(f"翻译后端就绪: {' → '.join(backend_status['backends'])}")

    storage = VideoStorage()
    radar = YoutubeRadar()
    translator = batch_translate
    _setup_hf_env()
    whisper_model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
    batch_size = 5

    logger.info(f"Processing single video: {url}")
    _emit_progress({"type": "phase", "name": "single_video", "video_total": 1})

    _emit_progress({"type": "step", "name": "download"})
    result = radar.download_video_by_url(url)
    if not result:
        logger.error(f"Failed to download video from {url}")
        _emit_progress({"type": "error", "step": "download", "message": "Download failed"})
        return
    _emit_progress({"type": "step_done", "name": "download"})

    video_id = result["id"]
    title = result["title"]
    downloaded_video_path = result["path"]
    _emit_progress({"type": "video", "id": video_id, "title": title, "current": 1, "total": 1})

    if storage.is_processed(video_id):
        logger.info(f"Video {video_id} already processed, skipping.")
        return

    logger.info(f"Preparing video {video_id} - {title}")

    try:
        _save_meta_cache(video_id, title)

        segments = _load_segments_cache(video_id)
        if segments is not None:
            logger.info("Step B: 跳过转录，使用缓存结果")
            _emit_progress({"type": "step", "name": "transcribe"})
            _emit_progress({"type": "step_done", "name": "transcribe"})
        else:
            logger.info("Step B: Extracting English subtitle segments with Whisper...")
            _emit_progress({"type": "step", "name": "transcribe"})
            audio_path = Path(settings.download_path) / f"{video_id}.wav"
            extract_audio(downloaded_video_path, audio_path)
            segments = transcribe_with_whisper(whisper_model, audio_path)

            if not segments:
                raise RuntimeError("Whisper did not return any subtitle segments.")

            logger.info("Step B2: VAD adjusting segment start times...")
            segments = _vad_adjust_segments(segments, audio_path)

            logger.info("Step B3: Removing hallucination segments...")
            segments = _remove_hallucination_segments(segments)

            logger.info("Step B4: Removing empty segments...")
            segments = _remove_empty_segments(segments)

            _save_segments_cache(video_id, segments)
            cleanup_files([audio_path])
            _emit_progress({"type": "step_done", "name": "transcribe"})

        translated_texts = _load_translated_cache(video_id, batch_size)
        if translated_texts is not None and len(translated_texts) != len(segments):
            logger.warning(
                f"翻译缓存行数 ({len(translated_texts)}) 与转录段数 ({len(segments)}) 不一致，重新翻译"
            )
            translated_texts = None
        if translated_texts is not None:
            logger.info("Step C: 跳过翻译，使用缓存结果")
            _emit_progress({"type": "step", "name": "translate"})
            _emit_progress({"type": "step_done", "name": "translate"})
        else:
            logger.info("Step C: Translating segments in batches...")
            _emit_progress({"type": "step", "name": "translate"})
            english_texts = [segment["text"] for segment in segments]
            total_batches = (len(english_texts) + batch_size - 1) // batch_size
            with terminal_progress(total=total_batches, desc="翻译", unit="批") as bar:
                def cb(cur, tot):
                    _emit_progress({"type": "batch", "current": cur, "total": tot})
                    bar.n = cur
                    bar.refresh()

                translated_texts = translator(english_texts, batch_size=batch_size,
                                              progress_callback=cb)
            _save_translated_cache(video_id, translated_texts, batch_size)
            _emit_progress({"type": "step_done", "name": "translate"})

        review_file = _save_review_file(video_id, segments, translated_texts)

        print(f"\n📝 视频 {video_id} 准备完成！")
        print(f"   中英对照: {review_file}")
        print(f"   翻译数据: {_cache_dir(video_id) / 'translated.json'}")
        print(f"   请审查后运行: python main.py --burn\n")

    except Exception as exc:
        logger.error(f"Failed preparing video {video_id}: {exc}", exc_info=True)
        _emit_progress({"type": "error", "step": "", "message": str(exc)[:100]})


def main():
    parser = argparse.ArgumentParser(description="VlogTrans - YouTube Vlog 自动汉化工具")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--prepare",
        action="store_true",
        help="准备阶段：下载视频、转录、翻译（可审查翻译结果）",
    )
    group.add_argument(
        "--burn",
        action="store_true",
        help="烧录阶段：读取缓存，将字幕烧录到视频中",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="一键运行：准备 + 烧录，无需审查直接完成全流程",
    )
    group.add_argument(
        "--video",
        type=str,
        help="处理单个视频URL：下载、转录、翻译",
    )
    args = parser.parse_args()

    if args.video:
        process_video(args.video)
    elif args.prepare:
        prepare()
    elif args.burn:
        burn()
    elif args.all:
        prepared_ids = prepare()
        if prepared_ids:
            print("\n⚡ 一键模式：跳过审查，直接烧录...\n")
            burn()
    else:
        prepare()


if __name__ == "__main__":
    main()
