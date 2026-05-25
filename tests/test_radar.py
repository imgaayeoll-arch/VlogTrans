from unittest.mock import MagicMock

import modules.radar.radar as radar_module
from modules.radar import YoutubeRadar


# --- Helpers ---

def _make_subprocess_result(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _flat_playlist_output(*videos):
    """Build yt-dlp --print '%(id)s\\t%(title)s' stdout."""
    return "\n".join(f"{vid}\t{title}" for vid, title in videos)


# --- Case A: get_new_videos filters processed IDs ---

def test_get_new_videos_filters_processed_ids(monkeypatch):
    monkeypatch.setattr(radar_module.settings, "youtube_channel_urls",
                        ["https://youtube.com/@example"])
    monkeypatch.setattr(radar_module.settings, "yt_dlp_path", "yt-dlp")

    storage = MagicMock()
    storage.is_processed.side_effect = lambda vid: vid == "processed01"
    monkeypatch.setattr(radar_module, "VideoStorage", lambda: storage)

    mock_run = MagicMock()
    mock_run.return_value = _make_subprocess_result(
        stdout=_flat_playlist_output(
            ("processed01", "Old Video"),
            ("newvideo001", "New Video"),
        )
    )
    monkeypatch.setattr(radar_module, "subprocess", MagicMock(run=mock_run))

    radar = YoutubeRadar()
    new_videos = radar.get_new_videos()

    assert len(new_videos) == 1
    assert new_videos[0]["id"] == "newvideo001"
    assert new_videos[0]["title"] == "New Video"


# --- Case B: download_video downloads and persists ---

def test_download_video_downloads_and_persists(monkeypatch, tmp_path):
    video_id = "newvideo001"
    download_dir = tmp_path / "videos"
    download_dir.mkdir()

    monkeypatch.setattr(radar_module.settings, "download_path", str(download_dir))
    monkeypatch.setattr(radar_module.settings, "yt_dlp_path", "yt-dlp")
    monkeypatch.setattr(radar_module.settings, "youtube_cookies_path", "")

    storage = MagicMock()
    storage.is_processed.return_value = False
    storage.add_video = MagicMock()
    monkeypatch.setattr(radar_module, "VideoStorage", lambda: storage)

    # Simulate successful download on first cookie attempt
    mock_run = MagicMock()
    mock_run.return_value = _make_subprocess_result(returncode=0)
    monkeypatch.setattr(radar_module, "subprocess", MagicMock(run=mock_run))

    # Create the "downloaded" file (name must contain video_id)
    (download_dir / f"{video_id}.mp4").write_text("")

    radar = YoutubeRadar()
    output_path = radar.download_video(video_id)

    assert output_path == str(download_dir / f"{video_id}.mp4")
    mock_run.assert_called()
    # Note: download_video() does NOT call storage.add_video() —
    # that is done by the caller (main.py prepare flow)


# --- Case C: download_video skips already processed ---

def test_download_video_skips_processed(monkeypatch):
    video_id = "processed01"

    monkeypatch.setattr(radar_module.settings, "download_path", "data/videos")
    monkeypatch.setattr(radar_module.settings, "yt_dlp_path", "yt-dlp")

    storage = MagicMock()
    storage.is_processed.return_value = True
    monkeypatch.setattr(radar_module, "VideoStorage", lambda: storage)

    mock_run = MagicMock()
    monkeypatch.setattr(radar_module, "subprocess", MagicMock(run=mock_run))

    radar = YoutubeRadar()
    result = radar.download_video(video_id)

    assert result is None
    mock_run.assert_not_called()
    storage.add_video.assert_not_called()
