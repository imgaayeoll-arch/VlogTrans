import logging
import os
import re
import shlex
import subprocess
import threading

from config import settings
from modules.progress import terminal_progress
from modules.storage import VideoStorage

logger = logging.getLogger(__name__)


class YoutubeRadar:
    def __init__(self):
        self.channel_urls = settings.youtube_channel_urls
        self.storage = VideoStorage()
        self.download_path = settings.download_path
        self._subprocess_env = self._build_subprocess_env()

    def _proxy_args(self):
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        if proxy:
            return ["--proxy", proxy]
        return []

    @staticmethod
    def _build_subprocess_env():
        env = os.environ.copy()
        deno_bin = os.path.expanduser("~/.deno/bin")
        if os.path.isdir(deno_bin) and deno_bin not in env.get("PATH", ""):
            env["PATH"] = deno_bin + os.pathsep + env.get("PATH", "")
        return env

    # ================= Cookie 处理 =================
    def _cookie_source_args(self):
        args = [
            ["--cookies-from-browser", "firefox"],
        ]
        if settings.youtube_cookies_path:
            args.append(["--cookies", settings.youtube_cookies_path])
        return args

    def _run_yt_dlp_with_cookies(self, base_cmd, timeout, progress=False, desc="下载"):
        for cookie_args in self._cookie_source_args():
            cmd = base_cmd + cookie_args
            logger.debug(f"Trying yt-dlp with cookies: {shlex.join(cmd)}")
            result = self._run_yt_dlp_once(cmd, timeout, progress, desc)
            if result.returncode == 0:
                return result

            stderr = result.stderr or ""
            cookie_errors = [
                "Could not copy",
                "failed to load cookies",
                "dpapi",
                "failed to decrypt",
                "unable to decrypt",
                "cookie",
            ]
            if any(token.lower() in stderr.lower() for token in cookie_errors):
                logger.warning(f"Cookie extraction failed: {stderr.strip()}")
            else:
                logger.warning(
                    f"yt-dlp exited with {result.returncode}, trying next method: {stderr.strip()[:200]}"
                )

        logger.warning("All cookie methods failed, retrying without cookies.")
        return self._run_yt_dlp_once(base_cmd, timeout, progress, desc)

    def _run_yt_dlp_once(self, cmd, timeout, progress, desc):
        if not progress:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=self._subprocess_env)
        return self._run_streaming(cmd, timeout, desc)

    def _run_streaming(self, cmd, timeout, desc):
        """带进度条地运行 yt-dlp：边读 stderr 边驱动 tqdm，同时累进缓冲区供 cookie 检测。"""
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=self._subprocess_env)
        stderr_buf = []
        bar = terminal_progress(total=100.0, desc=desc, unit="%")

        def _read():
            for line in proc.stderr:
                stderr_buf.append(line)
                m = re.search(r"\[download\]\s+([\d.]+)%", line)
                if m:
                    bar.n = float(m.group(1))
                    bar.refresh()

        reader = threading.Thread(target=_read, daemon=True)
        reader.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
        finally:
            reader.join(timeout=5)
            bar.close()

        return subprocess.CompletedProcess(cmd, proc.returncode, proc.stdout.read(), "".join(stderr_buf))

    # ================= 获取最新的 N 个视频（默认 3 个） =================
    def _get_latest_videos(self, channel_url, max_count=3):
        """
        获取频道最新的 max_count 个视频（按发布时间倒序）。
        返回列表，每个元素为 dict: {id, title}
        """
        # 确保 URL 是 /videos 子页面，以便获取完整的视频列表
        if '/videos' not in channel_url:
            channel_url = channel_url.rstrip('/')
            if '@' in channel_url:
                channel_url = f"{channel_url}/videos"
            elif '/channel/' in channel_url:
                channel_url = f"{channel_url}/videos"
        # 构建命令：获取视频ID和标题，按上传时间倒序（最新在前），限制数量
        cmd = [
            settings.yt_dlp_path,
            "--flat-playlist",
            "--playlist-reverse",
            "--playlist-end", str(max_count),
            "--print", "%(id)s\t%(title)s",
            channel_url
        ]
        cmd += self._proxy_args()

        logger.debug(f"Executing: {shlex.join(cmd)}")
        result = self._run_yt_dlp_with_cookies(cmd, timeout=120)
        if result.returncode != 0:
            logger.warning(f"yt-dlp get_latest_videos failed: {result.stderr}")
            return []

        # 由于 --playlist-reverse 先输出最老的，我们需要反转顺序
        lines = result.stdout.strip().split('\n')
        videos = []
        for line in reversed(lines):            # 从最新到最老
            if not line.strip():
                continue
            parts = line.split('\t', 1)
            if len(parts) < 2:
                continue
            video_id, title = parts
            if not video_id or len(video_id) != 11:
                continue
            videos.append({
                "id": video_id,
                "title": title.strip(),
            })
        logger.info(f"Retrieved {len(videos)} latest videos from channel (limit {max_count})")
        return videos

    # ================= 检测新视频（只处理最新的 3 个，去重） =================
    def get_new_videos(self):
        new_videos = []
        MAX_VIDEOS = 1

        for channel_url in self.channel_urls:
            logger.info(f"Checking channel: {channel_url}")
            latest = self._get_latest_videos(channel_url, max_count=MAX_VIDEOS)
            if not latest:
                logger.warning(f"No videos retrieved from {channel_url}")
                continue

            for video in latest:
                video_id = video["id"]
                if self.storage.is_processed(video_id):
                    continue
                new_videos.append({
                    "id": video_id,
                    "title": video["title"],
                    "upload_date": None,
                    "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
                })
                logger.info(f"Added new video: {video_id} - {video['title']}")

        logger.info(f"Total new videos found: {len(new_videos)}")
        return new_videos

    # ================= 下载视频（兼容性最好的格式） =================
    def download_video(self, video_id):
        if self.storage.is_processed(video_id):
            logger.info(f"Video {video_id} already processed, skipping download.")
            return None

        os.makedirs(self.download_path, exist_ok=True)
        url = f"https://www.youtube.com/watch?v={video_id}"
        output_template = os.path.join(self.download_path, "%(title).200s-%(id)s.%(ext)s")

        base_cmd = [
            settings.yt_dlp_path,
            "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "--merge-output-format", "mp4",
            "-o", output_template,
            "--no-playlist",
        ] + self._proxy_args() + [url]

        try:
            result = self._run_yt_dlp_with_cookies(base_cmd, timeout=600, progress=True)
            if result.returncode != 0:
                logger.error(f"yt-dlp download failed for {video_id}: {result.stderr}")
                return None

            for file in os.listdir(self.download_path):
                if video_id in file and file.endswith(".mp4"):
                    return os.path.join(self.download_path, file)

            logger.warning(f"Downloaded file not found for {video_id}")
            return None
        except Exception as exc:
            logger.error(f"Failed to download video {video_id}: {exc}")
            return None

    def download_video_by_url(self, url):
        os.makedirs(self.download_path, exist_ok=True)
        output_template = os.path.join(self.download_path, "%(title).200s-%(id)s.%(ext)s")

        base_cmd = [
            settings.yt_dlp_path,
            "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "--merge-output-format", "mp4",
            "--no-simulate",
            "--print", "%(id)s\t%(title)s",
            "-o", output_template,
            "--no-playlist",
        ] + self._proxy_args() + [url]

        logger.info(f"Running command: {shlex.join(base_cmd)}")  

        try:
            result = self._run_yt_dlp_with_cookies(base_cmd, timeout=600, progress=True)
            if result.returncode != 0:
                logger.error(f"yt-dlp download failed for {url}: {result.stderr}")
                return None

            video_id = None
            title = None
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t", 1)
                if len(parts) == 2 and len(parts[0]) == 11:
                    video_id = parts[0]
                    title = parts[1].strip()
                    break

            if not video_id:
                logger.error(f"Could not extract video ID from {url}")
                return None

            for file in os.listdir(self.download_path):
                if video_id in file and file.lower().endswith((".mp4", ".webm", ".mkv")):
                    return {
                        "id": video_id,
                        "title": title or video_id,
                        "path": os.path.join(self.download_path, file),
                    }

            logger.warning(f"Downloaded file not found for {video_id}")
            return None
        except Exception as exc:
            logger.error(f"Failed to download video {url}: {exc}")
            return None