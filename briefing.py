"""简报内容：提示词模板与推送文本整理。

模板里的 ``{date}`` / ``{name}`` 会被替换，用户可在任务里覆盖整段 prompt。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

DEFAULT_PROMPT = """今天是 {date}。请为我生成今天的简报：

1. 用三到五条要点概括今天值得关注的事（没有输入数据时，基于你已知的
   通用信息给一份「今日提示」，不要编造具体数字）
2. 每条要点后给一句可执行的建议
3. 最后用一句话总结今天该优先做的一件事

输出简体中文，控制在 300 字以内，直接用 Markdown 列表，不要加开场白。"""


def build_message(task: dict[str, Any], now: datetime | None = None) -> str:
    """把任务模板渲染成实际发给 Agent 的文本。"""
    now = now or datetime.now()
    template = (task.get("prompt") or "").strip() or DEFAULT_PROMPT
    return (
        template.replace("{date}", now.strftime("%Y-%m-%d"))
        .replace("{time}", now.strftime("%H:%M"))
        .replace("{name}", task.get("name") or "日报")
    )


def format_push_text(task: dict[str, Any], result: dict[str, Any],
                     now: datetime | None = None) -> str:
    """整理成适合 IM 推送的纯文本。"""
    now = now or datetime.now()
    content = (result.get("content") or "").strip()
    files = result.get("files") or []

    lines = [f"【{task.get('name') or '日报'}】{now.strftime('%Y-%m-%d %H:%M')}", ""]
    lines.append(content or "（本次没有生成正文）")

    if files:
        lines.append("")
        lines.append("产物：")
        for item in files:
            if isinstance(item, dict):
                name = item.get("name") or item.get("path") or "文件"
                url = item.get("url")
                lines.append(f"- {name}" + (f"（{url}）" if url else ""))
            else:
                lines.append(f"- {item}")

    return "\n".join(lines)


def excerpt(text: str, limit: int = 200) -> str:
    """给任务列表展示用的短摘要。"""
    flat = " ".join((text or "").split())
    return flat[:limit] + ("…" if len(flat) > limit else "")
