from modules.translator.backends.ollama_backend import OllamaBackend


class TestParseTranslatedLines:
    def test_standard_numbered_lines(self):
        text = "[01] 你好\n[02] 世界\n[03] 测试"
        result = OllamaBackend._parse_translated_lines(text)
        assert result == ["你好", "世界", "测试"]

    def test_empty_text_returns_empty_list(self):
        assert OllamaBackend._parse_translated_lines("") == []

    def test_skips_blank_lines(self):
        text = "[01] 第一行\n\n[02] 第二行"
        result = OllamaBackend._parse_translated_lines(text)
        assert result == ["第一行", "第二行"]

    def test_lines_without_numbers_preserved(self):
        text = "无编号行1\n无编号行2"
        result = OllamaBackend._parse_translated_lines(text)
        assert result == ["无编号行1", "无编号行2"]


class TestFallbackParse:
    def test_numbered_lines_across_lines(self):
        text = "[01] 第一行\n[02] 第二行"
        result = OllamaBackend._fallback_parse(text, 2)
        assert result == ["第一行", "第二行"]

    def test_exact_plain_lines(self):
        text = "第一行\n第二行\n第三行"
        result = OllamaBackend._fallback_parse(text, 3)
        assert result == ["第一行", "第二行", "第三行"]

    def test_truncates_extra_lines(self):
        text = "a\nb\nc\nd\ne"
        result = OllamaBackend._fallback_parse(text, 3)
        assert result == ["a", "b", "c"]

    def test_pads_missing_lines(self):
        text = "a\nb"
        result = OllamaBackend._fallback_parse(text, 4)
        assert result == ["a", "b", "", ""]

    def test_empty_text_returns_empty(self):
        result = OllamaBackend._fallback_parse("", 3)
        assert result == []
