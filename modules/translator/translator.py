import logging

from config import settings
from modules.translator.backends.ollama_backend import OllamaBackend

logger = logging.getLogger(__name__)

_BACKENDS = {
    "ollama": OllamaBackend,
}

_backend_instance = None


def _get_backend():
    global _backend_instance
    if _backend_instance is not None:
        return _backend_instance

    backend_name = settings.translation_backend
    backend_cls = _BACKENDS.get(backend_name)
    if backend_cls is None:
        raise ValueError(
            f"未知的翻译后端: {backend_name}，"
            f"可选值: {', '.join(_BACKENDS.keys())}"
        )

    _backend_instance = backend_cls()
    return _backend_instance


def batch_translate(segments, batch_size=10):
    backend = _get_backend()
    return backend.translate(segments, batch_size=batch_size)
