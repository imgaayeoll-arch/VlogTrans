import logging

from config import settings
from modules.translator.backends.ollama_backend import OllamaBackend
from modules.translator.backends.deepseek_backend import DeepSeekBackend

logger = logging.getLogger(__name__)

_BACKENDS = {
    "ollama": OllamaBackend,
    "deepseek": DeepSeekBackend,
}

_backend_chain = None
_current_model_name = None


def _get_backend_chain():
    global _backend_chain
    if _backend_chain is not None:
        return _backend_chain

    chain = []
    for name in settings.translation_backends_order:
        cls = _BACKENDS.get(name)
        if cls is None:
            logger.warning(f"未知的翻译后端: {name}，跳过")
            continue
        try:
            instance = cls()
            if instance.health_check():
                chain.append(instance)
            else:
                logger.info(f"backend {name} 健康检查未通过，跳过")
        except Exception as e:
            logger.warning(f"初始化 backend {name} 失败: {e}，跳过")

    if not chain:
        raise RuntimeError(
            f"无可用翻译后端，配置顺序: {settings.translation_backends_order}"
        )

    logger.info(
        f"翻译后端链: {' → '.join(b.__class__.__name__ for b in chain)}"
    )
    _backend_chain = chain
    return _backend_chain


def check_translation_backends():
    try:
        chain = _get_backend_chain()
    except RuntimeError:
        return {
            "available": False,
            "backends": [],
            "primary_model": None,
        }
    primary = chain[0]
    return {
        "available": True,
        "backends": [b.__class__.__name__ for b in chain],
        "primary_model": primary._model,
    }


def get_primary_model_name():
    try:
        chain = _get_backend_chain()
        return chain[0]._model
    except RuntimeError:
        return settings.translation_model


def get_current_model_name():
    return _current_model_name or get_primary_model_name()


def batch_translate(segments, batch_size=10, progress_callback=None):
    global _current_model_name
    chain = _get_backend_chain()

    for i, backend in enumerate(chain):
        try:
            result = backend.translate(segments, batch_size=batch_size,
                                       progress_callback=progress_callback)
            _current_model_name = backend._model
            if i > 0:
                logger.info(f"已切换到 fallback: {backend.__class__.__name__}")
            return result
        except Exception as e:
            if i == len(chain) - 1:
                raise
            logger.warning(
                f"backend {backend.__class__.__name__} 失败: {e}，尝试下一个"
            )
            continue

    raise RuntimeError("所有翻译后端均失败")
