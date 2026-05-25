import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.merger import SubtitleMerger


class TestSubtitleMerger(unittest.TestCase):
    def test_generate_bilingual_srt_creates_file(self):
        segments = [
            {"start": "00:00:01,000", "end": "00:00:03,000", "text": "Hello world"},
            {"start": "00:00:03,500", "end": "00:00:05,000", "text": "Let's go"},
        ]
        translated_data = ["你好，世界", "走吧"]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "bilingual.srt"
            merger = SubtitleMerger()
            result_path = merger.generate_bilingual_srt(segments, translated_data, str(output_path))

            self.assertEqual(result_path, str(output_path))
            self.assertTrue(output_path.exists())

            content = output_path.read_text(encoding="utf-8")
            expected = (
                "1\n"
                "00:00:01,000 --> 00:00:03,000\n"
                "Hello world\n"
                "你好，世界\n\n"
                "2\n"
                "00:00:03,500 --> 00:00:05,000\n"
                "Let's go\n"
                "走吧\n\n"
            )
            self.assertEqual(content, expected)

    @patch.object(SubtitleMerger, "_detect_best_codec", return_value="h264_nvenc")
    @patch("modules.merger.merger.subprocess.run")
    def test_burn_subtitles_uses_nvenc(self, mock_run, mock_codec):
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "video.mp4"
            srt_path = Path(tmpdir) / "subtitles.srt"
            output_path = Path(tmpdir) / "output.mp4"

            merger = SubtitleMerger()
            merger.burn_subtitles(str(video_path), str(srt_path), str(output_path))

            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertIn("h264_nvenc", args)
            self.assertIn(str(output_path), args)
            self.assertTrue(any("subtitles=" in arg for arg in args))

    @patch.object(SubtitleMerger, "_detect_best_codec", return_value="libx264")
    @patch("modules.merger.merger.subprocess.run")
    def test_burn_subtitles_falls_back_to_libx264(self, mock_run, mock_codec):
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "video.mp4"
            srt_path = Path(tmpdir) / "subtitles.srt"
            output_path = Path(tmpdir) / "output.mp4"

            merger = SubtitleMerger()
            merger.burn_subtitles(str(video_path), str(srt_path), str(output_path))

            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertIn("libx264", args)
            self.assertIn(str(output_path), args)
            self.assertTrue(any("subtitles=" in arg for arg in args))


if __name__ == "__main__":
    unittest.main()
