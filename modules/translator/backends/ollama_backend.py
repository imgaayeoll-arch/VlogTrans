import logging
import os
import re
import time

import httpx

from config import settings

logger = logging.getLogger(__name__)

_LOCALHOST_MARKERS = ("127.0.0.1", "localhost", "::1")


class NonRetryableError(Exception):
    pass


class OllamaBackend:
    def __init__(self):
        self._model = settings.deepseek_model
        self._base_url = settings.ollama_host.rstrip("/")
        self._max_retries = settings.retry_attempts
        self._base_retry_delay = settings.retry_delay_seconds
        self._disable_proxy = self._should_disable_proxy()
        self._client = self._create_client()

    def _should_disable_proxy(self):
        env_val = os.getenv("OLLAMA_DISABLE_PROXY", "").lower()
        if env_val in ("true", "1", "yes"):
            return True
        if env_val in ("false", "0", "no"):
            return False
        return any(marker in self._base_url for marker in _LOCALHOST_MARKERS)

    def _create_client(self):
        if self._disable_proxy:
            return httpx.Client(
                proxy=None,
                timeout=120.0,
                trust_env=False,
            )
        return httpx.Client(timeout=120.0)

    def health_check(self):
        if self._disable_proxy:
            client = httpx.Client(proxy=None, trust_env=False, timeout=10.0)
        else:
            client = httpx.Client(timeout=10.0)

        try:
            response = client.get(f"{self._base_url}/api/tags")
        except httpx.ConnectError:
            logger.error("=" * 60)
            logger.error("✗ Ollama 服务未运行")
            logger.error(f"  连接地址: {self._base_url}")
            logger.error("")
            logger.error("解决方案：")
            logger.error("  1. 启动 Ollama 服务: ollama serve")
            logger.error("  2. 确认 Ollama 已安装: https://ollama.com/download")
            logger.error("=" * 60)
            return False
        except Exception as e:
            logger.warning(f"Ollama 健康检查异常: {e}")
            return False
        finally:
            client.close()

        if response.status_code != 200:
            logger.error("=" * 60)
            logger.error(f"✗ Ollama 服务返回异常状态码: {response.status_code}")
            logger.error(f"  连接地址: {self._base_url}")
            logger.error("")
            logger.error("可能原因：")
            logger.error("  1. 本地代理拦截了请求（检查系统代理设置）")
            logger.error("  2. Ollama 服务未完全启动")
            logger.error("")
            logger.error("解决方案：")
            logger.error("  关闭系统代理后重试，或在 .env 中设置:")
            logger.error("  OLLAMA_DISABLE_PROXY=true")
            logger.error("=" * 60)
            return False

        data = response.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        logger.info(f"✓ Ollama 服务已连接，已安装 {len(models)} 个模型")

        matched = any(
            self._model in m or m.startswith(self._model)
            for m in models
        )
        if matched:
            logger.info(f"✓ 翻译模型 {self._model} 已就绪")
            return True

        logger.warning(f"✗ 翻译模型 {self._model} 未找到")
        logger.warning(f"  已安装的模型: {', '.join(models) if models else '无'}")
        logger.warning("")
        logger.warning("解决方案：")
        logger.warning(f"  运行: ollama pull {self._model}")
        logger.warning("  或在 .env 中修改 DEESEEK_MODEL 为已安装的模型名称")
        return False

    def translate(self, segments, batch_size=10):
        if not segments:
            return []

        translated_segments = []

        for i in range(0, len(segments), batch_size):
            batch = segments[i:i + batch_size]
            batch_text = "\n".join(
                f"[{j + 1:02d}] {text}" for j, text in enumerate(batch)
            )

            prompt = (
                "你是一位资深小红书博主，擅长将英文Vlog旁白翻译成地道、活泼、充满网感的中文。\n"
                "\n"
                "规则：\n"
                "- 逐行翻译，保持行数完全一致，严禁合并或删减。\n"
                "- 每行必须以 [01]、[02] 等序号开头，序号与输入对应。\n"
                "- 风格：活泼、有趣、网感强，像小红书笔记一样吸引人。\n"
                "- 只输出翻译结果，不要输出任何其他内容。\n"
                "\n"
                "示例：\n"
                "输入：\n"
                "[01] I love this coffee shop so much\n"
                "[02] The weather is beautiful today\n"
                "[03] Let's go for a walk\n"
                "\n"
                "输出：\n"
                "[01] 我超爱这家咖啡店\n"
                "[02] 今天天气也太好了吧\n"
                "[03] 我们出去走走吧\n"
                "\n"
                f"输入：\n{batch_text}\n\n输出："
            )

            result = self._translate_batch_with_retry(prompt, len(batch))
            translated_segments.extend(result)

        return translated_segments

    def _translate_batch_with_retry(self, prompt, expected_count):
        for attempt in range(self._max_retries):
            try:
                response = self._client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "options": {
                            "temperature": 0.7,
                        },
                    },
                    timeout=120.0,
                )

                if response.status_code in (404, 401, 403):
                    raise NonRetryableError(
                        f"不可重试的错误 (HTTP {response.status_code}): {response.text}"
                    )

                if response.status_code != 200:
                    logger.error(
                        f"翻译请求失败 (HTTP {response.status_code})"
                        f" (第 {attempt + 1}/{self._max_retries} 次重试): {response.text}"
                    )
                    if attempt == self._max_retries - 1:
                        raise RuntimeError(
                            f"翻译请求失败，重试 {self._max_retries} 次后仍返回 HTTP {response.status_code}"
                        )
                    self._exponential_backoff(attempt)
                    continue

                data = response.json()
                translated_text = data.get("message", {}).get("content", "").strip()
                if not translated_text:
                    logger.warning(
                        f"Ollama 返回空内容"
                        f" (第 {attempt + 1}/{self._max_retries} 次重试)"
                    )
                    if attempt == self._max_retries - 1:
                        raise RuntimeError("Ollama 返回空内容，重试耗尽")
                    self._exponential_backoff(attempt)
                    continue

                translated_lines = self._parse_translated_lines(translated_text)

                if len(translated_lines) == expected_count:
                    return translated_lines

                if len(translated_lines) > expected_count:
                    logger.warning(
                        f"行数偏多: 期望 {expected_count}, 实际 {len(translated_lines)}，截取前 {expected_count} 行"
                    )
                    return translated_lines[:expected_count]

                if len(translated_lines) > 0 and len(translated_lines) < expected_count:
                    fallback = self._fallback_parse(translated_text, expected_count)
                    if len(fallback) == expected_count:
                        logger.info(f"宽松解析成功，补齐到 {expected_count} 行")
                        return fallback

                logger.warning(
                    f"行数不匹配: 期望 {expected_count}, 实际 {len(translated_lines)}"
                    f" (第 {attempt + 1}/{self._max_retries} 次重试)"
                )
                logger.debug(
                    f"模型原始返回 (前200字): {translated_text[:200]}"
                )
                if attempt == self._max_retries - 1:
                    raise ValueError(
                        f"翻译行数不匹配，重试 {self._max_retries} 次后仍失败"
                    )

            except NonRetryableError:
                raise

            except httpx.ConnectError as e:
                logger.error(
                    f"Ollama 连接失败"
                    f" (第 {attempt + 1}/{self._max_retries} 次重试): {e}"
                )
                if attempt == self._max_retries - 1:
                    raise

            except (httpx.TimeoutException, httpx.ReadTimeout):
                logger.error(
                    f"Ollama 请求超时"
                    f" (第 {attempt + 1}/{self._max_retries} 次重试)"
                )
                if attempt == self._max_retries - 1:
                    raise

            except Exception as e:
                logger.error(
                    f"翻译异常 (第 {attempt + 1}/{self._max_retries} 次重试): {e}"
                )
                if attempt == self._max_retries - 1:
                    raise

            self._exponential_backoff(attempt)

        return []

    def _exponential_backoff(self, attempt):
        delay = self._base_retry_delay * (2 ** attempt)
        logger.info(f"等待 {delay} 秒后重试...")
        time.sleep(delay)

    @staticmethod
    def _parse_translated_lines(text):
        lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            match = re.match(r"^\[\d{2}\]\s*(.*)", stripped)
            if match:
                lines.append(match.group(1).strip())
            else:
                lines.append(stripped)
        return lines

    @staticmethod
    def _fallback_parse(text, expected_count):
        numbered = re.findall(r"\[\d{2}\]\s*(.*)", text)
        if len(numbered) == expected_count:
            return [line.strip() for line in numbered]

        all_lines = [line.strip() for line in text.split("\n") if line.strip()]
        if len(all_lines) == expected_count:
            return all_lines

        if len(all_lines) > expected_count:
            return all_lines[:expected_count]

        if len(all_lines) > 0:
            padded = all_lines + [""] * (expected_count - len(all_lines))
            return padded

        return []
