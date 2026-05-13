import os
from datetime import datetime
from unittest.mock import MagicMock

import modules.radar.radar as radar_module
from modules.radar import YoutubeRadar


def test_get_new_videos_filters_processed_ids(monkeypatch):
    monkeypatch.setattr(radar_module.settings, 'youtube_channel_urls', ['https://youtube.com/@example'])
    monkeypatch.setattr(radar_module.YoutubeRadar, '_business_day_threshold', lambda self, days=3: datetime(2020, 1, 1).date())

    storage = MagicMock()
    storage.is_processed.side_effect = lambda video_id: video_id == 'oldid'
    monkeypatch.setattr(radar_module, 'VideoStorage', lambda: storage)

    ydl_instance = MagicMock()
    ydl_instance.extract_info.return_value = {
        'entries': [
            {
                'id': 'oldid',
                'title': 'Old Video',
                'upload_date': '20200101',
                'webpage_url': 'https://www.youtube.com/watch?v=oldid',
            },
            {
                'id': 'newid',
                'title': 'New Video',
                'upload_date': '20200102',
                'webpage_url': 'https://www.youtube.com/watch?v=newid',
            },
        ]
    }

    ydl_class = MagicMock()
    ydl_class.return_value.__enter__.return_value = ydl_instance
    monkeypatch.setattr(radar_module, 'YoutubeDL', ydl_class)

    radar = YoutubeRadar()
    new_videos = radar.get_new_videos()

    assert len(new_videos) == 1
    assert new_videos[0]['id'] == 'newid'
    assert new_videos[0]['title'] == 'New Video'


def test_download_video_downloads_and_persists(monkeypatch, tmp_path):
    download_dir = tmp_path / 'videos'
    monkeypatch.setattr(radar_module.settings, 'download_path', str(download_dir))

    storage = MagicMock()
    storage.is_processed.return_value = False
    storage.add_video = MagicMock()
    monkeypatch.setattr(radar_module, 'VideoStorage', lambda: storage)

    ydl_instance = MagicMock()
    ydl_instance.extract_info.return_value = {'id': 'newid', 'title': 'New Video', 'ext': 'mp4'}
    ydl_instance.prepare_filename.return_value = str(download_dir / 'New Video-newid.mp4')

    ydl_class = MagicMock()
    ydl_class.return_value.__enter__.return_value = ydl_instance
    monkeypatch.setattr(radar_module, 'YoutubeDL', ydl_class)

    radar = YoutubeRadar()
    output_path = radar.download_video('newid')

    assert str(download_dir / 'New Video-newid.mp4') == output_path
    storage.add_video.assert_called_once_with('newid')
    ydl_instance.extract_info.assert_called_once()


def test_download_video_skips_processed(monkeypatch, tmp_path):
    monkeypatch.setattr(radar_module.settings, 'download_path', str(tmp_path / 'videos'))

    storage = MagicMock()
    storage.is_processed.return_value = True
    monkeypatch.setattr(radar_module, 'VideoStorage', lambda: storage)

    ydl_instance = MagicMock()
    ydl_class = MagicMock()
    ydl_class.return_value.__enter__.return_value = ydl_instance
    monkeypatch.setattr(radar_module, 'YoutubeDL', ydl_class)

    radar = YoutubeRadar()
    result = radar.download_video('newid')

    assert result is None
    ydl_instance.extract_info.assert_not_called()
    storage.add_video.assert_not_called()
