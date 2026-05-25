import pytest
from unittest.mock import MagicMock, patch

import modules.translator.translator as translator_module


@pytest.fixture(autouse=True)
def reset_backend_singleton():
    translator_module._backend_instance = None
    yield
    translator_module._backend_instance = None


@pytest.fixture
def sample_segments():
    return [
        "Hello everyone, welcome to my channel!",
        "Today we're going to explore the city.",
        "I love discovering new places.",
        "Let's start with this amazing cafe.",
        "The coffee here is incredible.",
        "Look at this beautiful view!",
        "I can't wait to share more with you.",
        "Thanks for watching, see you next time!",
    ]


def _make_mock_response(content):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": content},
    }
    return mock_resp


def _full_translation_output():
    return "\n".join([
        "[01] 大家好，欢迎来到我的频道！",
        "[02] 今天我们要探索这座城市。",
        "[03] 我喜欢发现新地方。",
        "[04] 让我们从这家神奇的咖啡店开始。",
        "[05] 这里的咖啡太棒了！",
        "[06] 看看这个美丽的景色！",
        "[07] 我迫不及待想和你们分享更多。",
        "[08] 感谢观看，下次见！",
    ])


@patch("httpx.Client")
def test_batch_translate_success(mock_httpx_client, sample_segments):
    client = MagicMock()
    client.post.return_value = _make_mock_response(_full_translation_output())
    mock_httpx_client.return_value = client

    result = translator_module.batch_translate(sample_segments, batch_size=10)

    assert len(result) == len(sample_segments)
    assert "大家好" in result[0]


@patch("httpx.Client")
def test_batch_translate_line_count_mismatch_retry(mock_httpx_client, sample_segments):
    client = MagicMock()
    mock_httpx_client.return_value = client

    # First call returns empty content (triggers retry), second succeeds
    client.post.side_effect = [
        _make_mock_response(""),
        _make_mock_response(_full_translation_output()),
    ]

    result = translator_module.batch_translate(sample_segments, batch_size=10)

    assert len(result) == len(sample_segments)
    assert client.post.call_count >= 2


@patch("httpx.Client")
def test_batch_translate_max_retries_exceeded(mock_httpx_client, sample_segments):
    client = MagicMock()
    mock_httpx_client.return_value = client
    # Empty content on every attempt — cannot be padded by fallback
    client.post.return_value = _make_mock_response("")

    with pytest.raises((ValueError, RuntimeError)):
        translator_module.batch_translate(sample_segments, batch_size=10)



@patch("httpx.Client")
def test_batch_translate_exception_handling(mock_httpx_client, sample_segments):
    import httpx

    client = MagicMock()
    mock_httpx_client.return_value = client
    client.post.side_effect = httpx.ConnectError("Connection refused")

    with pytest.raises((httpx.ConnectError, RuntimeError)):
        translator_module.batch_translate(sample_segments, batch_size=10)
