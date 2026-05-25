from main import _remove_hallucination_segments


def _seg(text, start, end):
    return {"text": text, "start": start, "end": end}


def test_normal_segments_not_removed():
    segments = [
        _seg("Hello world", "00:00:01,000", "00:00:03,000"),
        _seg("Goodbye world", "00:00:04,000", "00:00:06,000"),
    ]
    result = _remove_hallucination_segments(segments)
    assert len(result) == 2


def test_prefix_match_within_3s_removes_first():
    segments = [
        _seg("Hello world", "00:00:01,000", "00:00:02,000"),
        _seg("Hello world and more", "00:00:03,000", "00:00:05,000"),
    ]
    result = _remove_hallucination_segments(segments)
    assert len(result) == 1
    assert result[0]["text"] == "Hello world and more"


def test_prefix_match_over_3s_keeps_both():
    segments = [
        _seg("Hello world", "00:00:01,000", "00:00:02,000"),
        _seg("Hello world and more", "00:00:06,000", "00:00:08,000"),
    ]
    result = _remove_hallucination_segments(segments)
    assert len(result) == 2


def test_empty_list_returns_empty():
    result = _remove_hallucination_segments([])
    assert result == []


def test_single_segment_returns_unchanged():
    segments = [_seg("Hello", "00:00:01,000", "00:00:02,000")]
    result = _remove_hallucination_segments(segments)
    assert len(result) == 1


def test_non_prefix_match_keeps_both():
    segments = [
        _seg("Hello world", "00:00:01,000", "00:00:02,000"),
        _seg("Goodbye world", "00:00:02,500", "00:00:04,000"),
    ]
    result = _remove_hallucination_segments(segments)
    assert len(result) == 2
