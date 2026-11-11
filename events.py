"""事件触发：把外部推来的事件匹配到任务上。

任务侧三个字段决定它接不接某个事件：
  trigger       —— "cron"（默认，定时）或 "event"（事件驱动）
  event_source  —— 限定来源，如 "github"；留空表示任何来源
  event_filter  —— 正则，对事件正文匹配；留空表示全部接收
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("daily-briefing")


def match_tasks(tasks: list[dict[str, Any]], source: str, payload_text: str) -> list[dict]:
    matched: list[dict] = []
    for task in tasks:
        if not task.get("enabled", True):
            continue
        if (task.get("trigger") or "cron") != "event":
            continue

        expected_source = (task.get("event_source") or "").strip()
        if expected_source and expected_source != source:
            continue

        pattern = (task.get("event_filter") or "").strip()
        if pattern:
            try:
                if re.search(pattern, payload_text, re.I) is None:
                    continue
            except re.error:
                logger.warning("任务 %s 的 event_filter 不是合法正则：%s", task["id"], pattern)
                continue

        matched.append(task)
    return matched


def format_event(source: str, payload_text: str, limit: int = 6000) -> str:
    """事件正文注入提示词时用的包装，避免内容过长把上下文撑爆。"""
    body = payload_text.strip()
    if len(body) > limit:
        body = body[:limit] + f"\n…（已截断，原长 {len(payload_text)} 字符）"
    return f"事件来源：{source}\n\n{body}"
