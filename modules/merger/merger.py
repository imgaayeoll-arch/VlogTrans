import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from config import settings
from modules.progress import terminal_progress

logger = logging.getLogger(__name__)


class SubtitleMerger:
    def __init__(self):
        self.ffmpeg_cmd = settings.ffmpeg_path
        self._codec = None

    def generate_bilingual_srt(self, segments, translated_data, output_srt_path):
        """Generate a bilingual .srt file with English and Chinese lines."""
        if len(segments) != len(translated_data):
            raise ValueError("segments and translated_data must have equal length")

        output_path = Path(output_srt_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as srt_file:
            for index, (segment, chinese_text) in enumerate(zip(segments, translated_data), start=1):
                start = segment["start"]
                end = segment["end"]
                english_text = segment["text"]

                srt_file.write(f"{index}\n")
                srt_file.write(f"{start} --> {end}\n")
                srt_file.write(f"{english_text}\n")
                srt_file.write(f"{chinese_text}\n")
                srt_file.write("\n")

        return str(output_path)

    def _detect_best_codec(self):
        if self._codec is not None:
            return self._codec

        candidates = ["h264_nvenc", "h264_amf", "libx264"]
        for codec in candidates:
            try:
                cmd = [
                    self.ffmpeg_cmd,
                    "-y",
                    "-f", "lavfi",
                    "-i", "color=c=black:s=64x64:d=0.1",
                    "-c:v", codec,
                    "-frames:v", "1",
                    "-f", "null",
                    os.devnull,
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    logger.info(f"✓ 视频编码器选择: {codec}")
                    self._codec = codec
                    return codec
                logger.debug(f"编码器 {codec} 返回码 {result.returncode}，尝试下一个")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                logger.debug(f"编码器 {codec} 不可用，尝试下一个")
                continue

        logger.warning("所有硬件编码器均不可用，使用 libx264")
        self._codec = "libx264"
        return self._codec

    @staticmethod
    def _escape_srt_path(srt_path):
        p = str(srt_path).replace("\\", "/")
        p = p.replace(":", "\\:")
        p = p.replace("'", "\\'")
        p = p.replace("[", "\\[")
        p = p.replace("]", "\\]")
        return p

    def _codec_quality_args(self, codec):
        if codec == "h264_nvenc":
            return ["-rc", "constqp", "-qp", "20"]
        if codec == "h264_amf":
            return ["-rc", "cqp", "-qp_i", "18", "-qp_p", "20"]
        return ["-crf", "18", "-preset", "medium"]

    def _ffprobe_path(self):
        suffix = ".exe" if os.name == "nt" else ""
        sibling = Path(self.ffmpeg_cmd).with_name(f"ffprobe{suffix}")
        if sibling.exists():
            return str(sibling)
        return shutil.which("ffprobe") or "ffprobe"

    def _probe_duration(self, video_path):
        try:
            result = subprocess.run(
                [self._ffprobe_path(), "-v", "error", "-show_entries",
                 "format=duration", "-of", "csv=p=0", str(video_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                value = (result.stdout or "").strip()
                if value:
                    return float(value)
        except (subprocess.SubprocessError, ValueError):
            pass
        return None

    def burn_subtitles(self, video_path, srt_path, output_video_path):
        output_video = Path(output_video_path)
        output_video.parent.mkdir(parents=True, exist_ok=True)

        codec = self._detect_best_codec()

        escaped_srt = self._escape_srt_path(srt_path)
        subtitle_filter = (
            f"subtitles='{escaped_srt}':force_style='FontName=Arial,FontSize=18,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,BorderStyle=1'"
        )

        cmd = [
            self.ffmpeg_cmd,
            "-y",
            "-progress", "pipe:1",
            "-nostats",
            "-i",
            str(video_path),
            "-vf",
            subtitle_filter,
            "-c:v",
            codec,
        ] + self._codec_quality_args(codec) + [
            "-c:a",
            "copy",
            str(output_video),
        ]

        duration = self._probe_duration(video_path)

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stderr_buf = []
        bar = terminal_progress(total=duration, desc="烧录", unit="s", dynamic_ncols=True)

        def _read_stdout():
            for line in proc.stdout:
                m = re.search(r"out_time_ms=(\d+)", line)
                if m:
                    bar.n = int(m.group(1)) / 1_000_000
                    bar.refresh()

        stdout_reader = threading.Thread(target=_read_stdout, daemon=True)
        stderr_reader = threading.Thread(
            target=lambda: stderr_buf.extend(proc.stderr), daemon=True
        )
        stdout_reader.start()
        stderr_reader.start()

        proc.wait()
        stdout_reader.join(timeout=5)
        stderr_reader.join(timeout=5)
        bar.close()

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode, cmd, output=None, stderr="".join(stderr_buf)
            )

        return str(output_video)
