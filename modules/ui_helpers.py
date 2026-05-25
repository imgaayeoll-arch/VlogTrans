import json
import os
import re
import subprocess
from datetime import datetime
from glob import glob
from pathlib import Path


def scan_cache_videos(cache_path: str) -> list[dict]:
    cache_dir = Path(cache_path)
    if not cache_dir.exists():
        return []
    results = []
    for d in sorted(cache_dir.iterdir()):
        if not d.is_dir():
            continue
        video_id = d.name
        meta_file = d / "meta.json"
        title = ""
        if meta_file.exists():
            try:
                title = json.loads(meta_file.read_text(encoding="utf-8")).get("title", "")
            except (json.JSONDecodeError, KeyError):
                pass
        results.append({
            "id": video_id,
            "title": title,
            "has_segments": (d / "segments.json").exists(),
            "has_translated": (d / "translated.json").exists(),
            "has_review": (d / "review.txt").exists(),
        })
    return results


def scan_output_videos(output_path: str) -> list[dict]:
    output_dir = Path(output_path)
    if not output_dir.exists():
        return []
    results = []
    for f in sorted(output_dir.glob("*.mp4")):
        stat = f.stat()
        results.append({
            "name": f.name,
            "path": str(f),
            "size_mb": round(stat.st_size / (1024 * 1024), 1),
            "modified": datetime.fromtimestamp(stat.st_mtime),
        })
    return results


def scan_downloaded_videos(download_path: str) -> list[dict]:
    download_dir = Path(download_path)
    if not download_dir.exists():
        return []
    video_exts = {".mp4", ".webm", ".mkv", ".avi", ".mov"}
    results = []
    for f in sorted(download_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in video_exts:
            continue
        video_id = ""
        for part in f.stem.split("-"):
            if len(part) >= 10 and part not in ("mp4", "webm"):
                video_id = part
                break
        results.append({
            "name": f.name,
            "path": str(f),
            "video_id": video_id,
        })
    return results


def count_processed_ids(db_path: str) -> int:
    db_file = Path(db_path)
    if not db_file.exists():
        return 0
    try:
        data = json.loads(db_file.read_text(encoding="utf-8"))
        return len(data)
    except (json.JSONDecodeError, FileNotFoundError):
        return 0


def remove_processed_id(db_path: str, video_id: str) -> None:
    db_file = Path(db_path)
    if not db_file.exists():
        return
    try:
        data = json.loads(db_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return
    new_data = [vid for vid in data if vid != video_id]
    db_file.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8")


def find_video_for_id(download_path: str, video_id: str) -> str | None:
    pattern = os.path.join(download_path, f"*{video_id}*")
    matches = [m for m in glob(pattern) if Path(m).suffix.lower() in (".mp4", ".webm", ".mkv", ".avi", ".mov")]
    return matches[0] if matches else None


def find_srt_for_id(subtitle_path: str, video_id: str) -> str | None:
    pattern = os.path.join(subtitle_path, f"*{video_id}*.srt")
    matches = glob(pattern)
    return matches[0] if matches else None


def check_ffmpeg_status(ffmpeg_path: str) -> dict:
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            first_line = result.stdout.splitlines()[0] if result.stdout else ""
            version_match = re.search(r"ffmpeg version\s+(\S+)", first_line)
            version = version_match.group(1) if version_match else first_line[:50]
            return {"available": True, "version": version}
        return {"available": False, "version": ""}
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {"available": False, "version": ""}


def check_ytdlp_status(ytdlp_path: str) -> dict:
    try:
        proc = subprocess.Popen(
            [ytdlp_path, "--version"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            stdin=subprocess.DEVNULL,
        )
        output_lines = []

        def _read_stdout():
            for line in proc.stdout:
                output_lines.append(line)

        import threading
        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()
        reader.join(timeout=10)
        proc.kill()
        proc.wait(timeout=5)

        version = output_lines[0].strip() if output_lines else ""
        if version:
            channel = ""
            if re.match(r"^\d{4}\.\d{2}\.\d{2}$", version):
                channel = "stable"
            elif re.match(r"^\d{4}\.\d{2}\.\d{2}\.\d+$", version):
                channel = "nightly"
            return {"available": True, "version": version, "channel": channel}
        return {"available": False, "version": "", "channel": ""}
    except (FileNotFoundError, OSError):
        return {"available": False, "version": "", "channel": ""}


def check_deno_status() -> dict:
    deno_bin = os.path.expanduser("~/.deno/bin/deno.exe" if os.name == "nt" else "~/.deno/bin/deno")
    if not os.path.isfile(deno_bin):
        return {"available": False, "version": "", "path": ""}
    try:
        result = subprocess.run(
            [deno_bin, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            first_line = result.stdout.splitlines()[0] if result.stdout else ""
            version_match = re.search(r"deno\s+(\S+)", first_line)
            version = version_match.group(1) if version_match else first_line[:50]
            return {"available": True, "version": version, "path": deno_bin}
        return {"available": False, "version": "", "path": deno_bin}
    except (subprocess.TimeoutExpired, OSError):
        return {"available": False, "version": "", "path": deno_bin}


def check_firefox_cookies_status() -> dict:
    if os.name == "nt":
        profile_dir = os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")
    elif os.name == "posix":
        profile_dir = os.path.expanduser("~/Library/Application Support/Firefox/Profiles") if os.uname().sysname == "Darwin" else os.path.expanduser("~/.mozilla/firefox")
    else:
        profile_dir = ""
    if profile_dir and os.path.isdir(profile_dir):
        profiles = [d for d in os.listdir(profile_dir) if os.path.isdir(os.path.join(profile_dir, d))]
        return {"available": True, "profile_dir": profile_dir, "profile_count": len(profiles)}
    return {"available": False, "profile_dir": profile_dir, "profile_count": 0}


def check_ollama_status() -> dict:
    try:
        from config import settings
        import httpx

        base_url = settings.ollama_host.rstrip("/")
        disable_proxy = os.getenv("OLLAMA_DISABLE_PROXY", "").lower() in ("true", "1", "yes")

        client_kwargs = {"timeout": 10.0}
        if disable_proxy:
            client_kwargs["proxy"] = None
            client_kwargs["trust_env"] = False

        client = httpx.Client(**client_kwargs)
        try:
            response = client.get(f"{base_url}/api/tags")
        except httpx.ConnectError:
            return {"running": False, "model_ready": False, "models": []}
        except Exception:
            return {"running": False, "model_ready": False, "models": []}
        finally:
            client.close()

        if response.status_code != 200:
            return {"running": False, "model_ready": False, "models": []}

        data = response.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        model_ready = any(
            settings.translation_model in m or m.startswith(settings.translation_model)
            for m in models
        )
        return {"running": True, "model_ready": model_ready, "models": models}
    except Exception:
        return {"running": False, "model_ready": False, "models": []}


def check_cookies_file_status(cookies_path: str) -> dict:
    if not cookies_path:
        return {"exists": False, "path": "", "size_kb": 0.0}
    p = Path(cookies_path)
    if p.exists():
        size_kb = round(p.stat().st_size / 1024, 1)
        return {"exists": True, "path": str(p), "size_kb": size_kb}
    return {"exists": False, "path": str(p), "size_kb": 0.0}


def load_video_review_data(cache_path: str, video_id: str) -> dict | None:
    cache_dir = Path(cache_path) / video_id
    if not cache_dir.is_dir():
        return None

    segments_file = cache_dir / "segments.json"
    translated_file = cache_dir / "translated.json"
    meta_file = cache_dir / "meta.json"

    if not segments_file.exists() or not translated_file.exists():
        return None

    try:
        seg_data = json.loads(segments_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return None

    try:
        trans_data = json.loads(translated_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError):
        return None

    title = ""
    if meta_file.exists():
        try:
            title = json.loads(meta_file.read_text(encoding="utf-8")).get("title", "")
        except (json.JSONDecodeError, KeyError):
            pass

    return {
        "segments": seg_data.get("segments", []),
        "translations": trans_data.get("translations", []),
        "title": title,
        "segment_meta": {k: v for k, v in seg_data.items() if k != "segments"},
        "translation_meta": {k: v for k, v in trans_data.items() if k != "translations"},
    }


def save_review_data(
    cache_path: str,
    video_id: str,
    segments: list,
    translations: list,
    english_edited: list | None = None,
    segment_meta: dict | None = None,
    translation_meta: dict | None = None,
) -> dict:
    cache_dir = Path(cache_path) / video_id
    cache_dir.mkdir(parents=True, exist_ok=True)

    if len(segments) != len(translations):
        return {
            "success": False,
            "message": f"英文行数 ({len(segments)}) 与中文行数 ({len(translations)}) 不一致，无法保存",
        }

    review_file = cache_dir / "review.txt"
    lines = []
    for i, (seg, zh) in enumerate(zip(segments, translations), 1):
        lines.append(f"[{i:03d}] {seg['text']}")
        lines.append(f"     {zh}")
        lines.append("")
    review_file.write_text("\n".join(lines), encoding="utf-8")

    if english_edited is not None:
        segments_file = cache_dir / "segments.json"
        meta = segment_meta or {}
        if segments_file.exists():
            try:
                existing = json.loads(segments_file.read_text(encoding="utf-8"))
                meta = {k: v for k, v in existing.items() if k != "segments"}
            except (json.JSONDecodeError, KeyError):
                pass
        seg_data = {"segments": segments}
        seg_data.update(meta)
        segments_file.write_text(json.dumps(seg_data, ensure_ascii=False, indent=2), encoding="utf-8")

    translated_file = cache_dir / "translated.json"
    trans_meta = translation_meta or {}
    if translated_file.exists():
        try:
            existing = json.loads(translated_file.read_text(encoding="utf-8"))
            trans_meta = {k: v for k, v in existing.items() if k != "translations"}
        except (json.JSONDecodeError, KeyError):
            pass
    trans_data = {"translations": translations}
    trans_data.update(trans_meta)
    translated_file.write_text(json.dumps(trans_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"success": True, "message": "翻译已保存到 review.txt、segments.json、translated.json"}


def update_env_channel_urls(env_path: str, urls: list[str]) -> None:
    env_file = Path(env_path)
    if not env_file.exists():
        return

    lines = env_file.read_text(encoding="utf-8").splitlines()
    new_value = ",".join(urls)
    found = False
    for i, line in enumerate(lines):
        if line.startswith("YOUTUBE_CHANNEL_URLS="):
            lines[i] = f"YOUTUBE_CHANNEL_URLS={new_value}"
            found = True
            break
    if not found:
        lines.append(f"YOUTUBE_CHANNEL_URLS={new_value}")

    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
