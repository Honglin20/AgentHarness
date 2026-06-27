"""stream-json → harness event 翻译层（Phase B）。

Public API:
  - ``TranslateContext``: 翻译所需的节点路由元数据
  - ``TranslatedEvent``: 翻译产物（type + payload）
  - ``translate``: 纯函数主入口
"""
from harness.translator.stream_json import TranslateContext, TranslatedEvent, translate

__all__ = ["TranslateContext", "TranslatedEvent", "translate"]
