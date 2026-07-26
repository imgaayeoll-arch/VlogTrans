import logging
import re
import time

import httpx

from config import settings

logger = logging.getLogger(__name__)


class NonRetryableError(Exception):
    pass


class DeepSeekBackend:
    def __init__(self):
        self._api_key = settings.deepseek_api_key
        self._base_url = settings.deepseek_base_url.rstrip("/")
        self._model = settings.deepseek_model
        self._max_retries = settings.retry_attempts
        self._base_retry_delay = settings.retry_delay_seconds
        self._client = httpx.Client(
            timeout=120.0,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    def health_check(self):
        if not self._api_key:
            logger.info("DeepSeek API Key 未配置，跳过该 backend")
            return False
        logger.info(f"✓ DeepSeek backend 已配置（model={self._model}）")
        return True

    def translate(self, segments, batch_size=10, progress_callback=None):
        if not segments:
            return []

        if not self._api_key:
            raise NonRetryableError("DeepSeek API Key 未配置")

        total_batches = (len(segments) + batch_size - 1) // batch_size
        translated_segments = []

        for i in range(0, len(segments), batch_size):
            batch = segments[i:i + batch_size]
            batch_index = i // batch_size + 1
            batch_text = "\n".join(
                f"[{j + 1:02d}] {text}" for j, text in enumerate(batch)
            )

            prompt = (
                "你是一位资深小红书博主，擅长将英文Vlog旁白翻译成地道、活泼的中文。\n"
                "\n"
                "规则：\n"
                "- 逐行翻译，保持行数完全一致，严禁合并或删减。\n"
                "- 每行必须以 [01]、[02] 等序号开头，序号与输入对应。\n"
                "- 风格：活泼、有趣，像小红书笔记一样吸引人。\n"
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

            if progress_callback and total_batches > 1:
                progress_callback(batch_index, total_batches)
            result = self._translate_batch_with_retry(prompt, len(batch))
            translated_segments.extend(result)

        return translated_segments

    def _translate_batch_with_retry(self, prompt, expected_count):
        for attempt in range(self._max_retries):
            try:
                response = self._client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                        "stream": False,
                    },
                    timeout=120.0,
                )

                if response.status_code in (401, 403):
                    raise NonRetryableError(
                        f"DeepSeek 鉴权失败 (HTTP {response.status_code}): {response.text}"
                    )

                if response.status_code == 400:
                    raise NonRetryableError(
                        f"DeepSeek 请求格式错误 (HTTP 400): {response.text}"
                    )

                if response.status_code == 429:
                    logger.warning(
                        f"DeepSeek 限流 (429) (第 {attempt + 1}/{self._max_retries} 次重试)"
                    )
                    if attempt == self._max_retries - 1:
                        raise RuntimeError("DeepSeek 限流，重试耗尽")
                    self._exponential_backoff(attempt)
                    continue

                if response.status_code >= 500:
                    logger.warning(
                        f"DeepSeek 服务异常 (HTTP {response.status_code})"
                        f" (第 {attempt + 1}/{self._max_retries} 次重试)"
                    )
                    if attempt == self._max_retries - 1:
                        raise RuntimeError(
                            f"DeepSeek 服务异常，重试 {self._max_retries} 次后仍失败"
                        )
                    self._exponential_backoff(attempt)
                    continue

                if response.status_code != 200:
                    raise NonRetryableError(
                        f"DeepSeek 异常状态码 (HTTP {response.status_code}): {response.text}"
                    )

                data = response.json()
                choices = data.get("choices", [])
                if not choices:
                    logger.warning(
                        f"DeepSeek 返回空 choices (第 {attempt + 1}/{self._max_retries} 次重试)"
                    )
                    if attempt == self._max_retries - 1:
                        raise RuntimeError("DeepSeek 返回空 choices，重试耗尽")
                    self._exponential_backoff(attempt)
                    continue

                translated_text = (
                    choices[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if not translated_text:
                    logger.warning(
                        f"DeepSeek 返回空内容 (第 {attempt + 1}/{self._max_retries} 次重试)"
                    )
                    if attempt == self._max_retries - 1:
                        raise RuntimeError("DeepSeek 返回空内容，重试耗尽")
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
                    f"DeepSeek 连接失败 (第 {attempt + 1}/{self._max_retries} 次重试): {e}"
                )
                if attempt == self._max_retries - 1:
                    raise

            except (httpx.TimeoutException, httpx.ReadTimeout):
                logger.error(
                    f"DeepSeek 请求超时 (第 {attempt + 1}/{self._max_retries} 次重试)"
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
