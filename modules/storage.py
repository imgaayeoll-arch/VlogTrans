import json
import os
import threading
from config import settings


class VideoStorage:
    def __init__(self):
        self.path = settings.db_path
        self._lock = threading.Lock()
        self._ensure_storage_exists()

    def _ensure_storage_exists(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as file:
                json.dump([], file, ensure_ascii=False, indent=2)

    def _load_ids(self):
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as file:
                    data = json.load(file)
            except (json.JSONDecodeError, FileNotFoundError):
                data = []
            return set(data)

    def _save_ids(self, video_ids):
        with self._lock:
            with open(self.path, "w", encoding="utf-8") as file:
                json.dump(sorted(video_ids), file, ensure_ascii=False, indent=2)

    def is_processed(self, video_id):
        """Return True if the video ID is already stored."""
        return video_id in self._load_ids()

    def add_video(self, video_id):
        """Add a video ID to storage and persist immediately."""
        video_ids = self._load_ids()
        if video_id not in video_ids:
            video_ids.add(video_id)
            self._save_ids(video_ids)
