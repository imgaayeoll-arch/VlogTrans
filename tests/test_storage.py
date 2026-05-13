import json
from config import settings
from modules.storage import VideoStorage


def test_storage_initializes_empty_database(tmp_path, monkeypatch):
    db_file = tmp_path / "storage.json"
    monkeypatch.setattr(settings, "db_path", str(db_file))

    storage = VideoStorage()

    assert db_file.exists()
    assert storage.is_processed("video_1") is False


def test_storage_adds_video_id(tmp_path, monkeypatch):
    db_file = tmp_path / "storage.json"
    monkeypatch.setattr(settings, "db_path", str(db_file))

    storage = VideoStorage()
    storage.add_video("video_1")

    assert storage.is_processed("video_1") is True

    with open(db_file, "r", encoding="utf-8") as file:
        data = json.load(file)

    assert data == ["video_1"]


def test_storage_handles_duplicate_ids(tmp_path, monkeypatch):
    db_file = tmp_path / "storage.json"
    monkeypatch.setattr(settings, "db_path", str(db_file))

    storage = VideoStorage()
    storage.add_video("video_1")
    storage.add_video("video_1")

    with open(db_file, "r", encoding="utf-8") as file:
        data = json.load(file)

    assert data == ["video_1"]
    assert storage.is_processed("video_1") is True
