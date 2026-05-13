import pytest
from unittest.mock import patch, MagicMock
from modules.translator import batch_translate


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
        "Thanks for watching, see you next time!"
    ]


@patch('modules.translator.translator.OpenAI')
def test_batch_translate_success(mock_openai, sample_segments):
    # Mock the OpenAI client and response
    mock_client = MagicMock()
    mock_openai.return_value = mock_client

    # Mock successful response with correct line count
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "\n".join([
        "[01] 大家好，欢迎来到我的频道！😊",
        "[02] 今天我们要探索这座城市。",
        "[03] 我喜欢发现新地方。",
        "[04] 让我们从这家神奇的咖啡店开始。",
        "[05] 这里的咖啡太棒了！☕",
        "[06] 看看这个美丽的景色！🌟",
        "[07] 我迫不及待想和你们分享更多。",
        "[08] 感谢观看，下次见！👋"
    ])
    mock_client.chat.completions.create.return_value = mock_response

    result = batch_translate(sample_segments, batch_size=10)

    assert len(result) == len(sample_segments)
    assert "[01]" in result[0]
    assert "大家好" in result[0]
    mock_client.chat.completions.create.assert_called_once()


@patch('modules.translator.translator.OpenAI')
def test_batch_translate_line_count_mismatch_retry(mock_openai, sample_segments):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client

    # First call returns wrong line count, second succeeds
    mock_response1 = MagicMock()
    mock_response1.choices[0].message.content = "[01] 翻译1\n[02] 翻译2"  # Only 2 lines

    mock_response2 = MagicMock()
    mock_response2.choices[0].message.content = "\n".join([
        "[01] 大家好，欢迎来到我的频道！😊",
        "[02] 今天我们要探索这座城市。",
        "[03] 我喜欢发现新地方。",
        "[04] 让我们从这家神奇的咖啡店开始。",
        "[05] 这里的咖啡太棒了！☕",
        "[06] 看看这个美丽的景色！🌟",
        "[07] 我迫不及待想和你们分享更多。",
        "[08] 感谢观看，下次见！👋"
    ])

    mock_client.chat.completions.create.side_effect = [mock_response1, mock_response2]

    result = batch_translate(sample_segments, batch_size=10)

    assert len(result) == len(sample_segments)
    assert mock_client.chat.completions.create.call_count == 2


@patch('modules.translator.translator.OpenAI')
def test_batch_translate_max_retries_exceeded(mock_openai, sample_segments):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client

    # Always return wrong line count
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "[01] 翻译1"
    mock_client.chat.completions.create.return_value = mock_response

    with pytest.raises(ValueError, match="Translation failed after 3 retries"):
        batch_translate(sample_segments, batch_size=10)

    assert mock_client.chat.completions.create.call_count == 3


@patch('modules.translator.translator.OpenAI')
def test_batch_translate_exception_handling(mock_openai, sample_segments):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client

    # Simulate connection error
    mock_client.chat.completions.create.side_effect = Exception("Connection timeout")

    with pytest.raises(Exception, match="Connection timeout"):
        batch_translate(sample_segments, batch_size=10)

    assert mock_client.chat.completions.create.call_count == 3  # Max retries