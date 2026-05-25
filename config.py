import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    config_source = ".env"
    youtube_channel_url = os.getenv("YOUTUBE_CHANNEL_URL", "https://youtube.com/@example")
    youtube_channel_urls = [url.strip() for url in os.getenv("YOUTUBE_CHANNEL_URLS", youtube_channel_url).split(",") if url.strip()]
    download_path = os.getenv("DOWNLOAD_PATH", "data/videos")
    subtitle_path = os.getenv("SUBTITLE_PATH", "data/subtitles")
    output_path = os.getenv("OUTPUT_PATH", "data/output")
    video_id_store_path = os.getenv("VIDEO_ID_STORE_PATH", "data/downloaded_video_ids.json")
    db_path = os.getenv("DB_PATH", video_id_store_path)
    ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    translation_model = os.getenv("TRANSLATION_MODEL") or os.getenv("DEESEEK_MODEL", "qwen2.5")
    whisper_model = os.getenv("WHISPER_MODEL", "small.en")
    youtube_cookies_path = os.getenv("YOUTUBE_COOKIES_PATH", "")
    retry_attempts = int(os.getenv("RETRY_ATTEMPTS", "3"))
    retry_delay_seconds = int(os.getenv("RETRY_DELAY_SECONDS", "5"))
    yt_dlp_path = os.getenv("YT_DLP_PATH", "yt-dlp")
    translation_backend = os.getenv("TRANSLATION_BACKEND", "ollama")
    cache_path = os.getenv("CACHE_PATH", "data/cache")

    @property
    def ffmpeg_path(self):
        env_path = os.getenv("FFMPEG_PATH")
        if env_path and Path(env_path).exists():
            return env_path

        ffmpeg_in_path = shutil.which("ffmpeg")
        if ffmpeg_in_path:
            return ffmpeg_in_path

        if os.name == "nt":
            common_paths = [
                Path("D:/ffmpeg/bin/ffmpeg.exe"),
                Path("C:/ffmpeg/bin/ffmpeg.exe"),
                Path(os.path.dirname(__file__)) / "ffmpeg.exe",
            ]
            for path in common_paths:
                if path.exists():
                    return str(path)

        return "ffmpeg"


settings = Settings()
