"""从 claude result 文本提取结构化 JSON + schema 校验（Phase E）。

claude 的 result.result 字段是 plain text，但 harness 期望 agent 输出符合
``agent_def.result_type`` 的结构化数据。本模块负责：
  1. 从 text 中提取出 JSON（容忍 ```json fence、前后说明文字、空白）
  2. 用 pydantic 模型校验（agent_def.result_type 必须是 BaseModel 子类）

失败时抛 SchemaValidationError，被 ClaudeCodeExecutor.run() 抛出，
execute_with_retry 接管重试逻辑。

设计参考: docs/plans/2026-06-25-claude-code-executor/detailed-design.md §8
"""
from __future__ import annotations

import json
import re
from typing import Any, Type

from pydantic import BaseModel, ValidationError


class SchemaValidationError(Exception):
    """结果提取或 schema 校验失败的统一异常类型。

    被execute_with_retry 当作可重试错误处理。携带原始 text + 失败原因，方便
    Phase E.2 的 --resume feedback 注入把信息回喂给 claude。
    """

    def __init__(self, reason: str, *, raw_text: str | None = None, details: Any = None):
        self.reason = reason
        self.raw_text = raw_text
        self.details = details
        super().__init__(f"{reason}: details={details!r}")


# ---------------------------------------------------------------------------
# JSON 提取（容忍各种格式）
# ---------------------------------------------------------------------------

# 匹配 ```json ... ``` 或 ``` ... ``` 围栏
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)


def extract_json_text(text: str) -> str:
    """从 text 中提取出 JSON 字符串。

    支持的输入形式（按优先级）:
      1. 整个 text 就是合法 JSON（trim 后直接返回）
      2. ```json ... ``` 围栏
      3. ``` ... ``` 围栏（无 json 标签）
      4. 第一个平衡的 {...} 或 [...] 块（brace matching，正确处理嵌套 + 字符串内的括号）

    Raises:
        SchemaValidationError: 找不到任何 JSON 候选
    """
    if not text or not text.strip():
        raise SchemaValidationError("empty result text", raw_text=text)

    stripped = text.strip()

    # 1. 整体是 JSON
    if _looks_like_json(stripped):
        return stripped

    # 2/3. 围栏
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        candidate = fence_match.group(1).strip()
        if candidate:
            return candidate

    # 4. 第一个平衡 {...} 或 [...] 块（brace counting）
    brace_block = _find_first_balanced_block(text)
    if brace_block:
        return brace_block.strip()

    raise SchemaValidationError(
        "no JSON candidate found in result text",
        raw_text=text,
    )


def _find_first_balanced_block(text: str) -> str | None:
    """找第一个平衡的 {...} 或 [...] 块。

    正确处理:
      - 嵌套（如 ``{"a": {"b": 1}}``）
      - 字符串内的括号（如 ``{"x": "} not closing"}``）
      - 转义字符（如 ``{"x": "\\"}"}``）

    Returns:
        第一个平衡块的子字符串（含外层括号）；找不到返回 None。
    """
    start = -1
    open_ch = ""
    close_ch = ""
    depth = 0
    in_string = False
    escape = False

    for i, c in enumerate(text):
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c in "{[":
            if depth == 0:
                # 记录第一个开括号
                start = i
                open_ch = c
                close_ch = "}" if c == "{" else "]"
            depth += 1
        elif c in "}]":
            if depth > 0 and c == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
            # 不匹配的闭括号（如开了 { 但遇到 ]）— 跳过，让算法继续找下一个块
    return None


def _looks_like_json(s: str) -> bool:
    """快速判断字符串是否可能是 JSON（首尾是 {} 或 []）。"""
    if not s:
        return False
    first = s[0]
    last = s[-1]
    return (first == "{" and last == "}") or (first == "[" and last == "]")


# ---------------------------------------------------------------------------
# Schema 校验
# ---------------------------------------------------------------------------


def extract_and_validate(
    text: str,
    result_type: Type[BaseModel] | None,
) -> BaseModel | str:
    """提取 JSON + 用 result_type 校验。

    Args:
        text: claude result.result 文本
        result_type: 期望的 pydantic 模型类；None 表示 free text（不校验，直接返回 str）

    Returns:
        - 如果 result_type is None: 返回原始 text（str）
        - 否则: 返回 result_type 实例（pydantic 校验过的 BaseModel）

    Raises:
        SchemaValidationError: 提取失败 / JSON parse 失败 / pydantic 校验失败
    """
    if result_type is None:
        return text

    json_text = extract_json_text(text)

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise SchemaValidationError(
            f"invalid JSON: {e}",
            raw_text=text,
            details={"json_text": json_text, "json_error": str(e)},
        ) from e

    try:
        return result_type.model_validate(parsed)
    except ValidationError as e:
        raise SchemaValidationError(
            f"schema validation failed: {e}",
            raw_text=text,
            details={"parsed": parsed, "validation_error": e.errors()},
        ) from e
