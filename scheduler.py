"""调度：一个 asyncio 循环，按 tick 检查到点任务。

不用 APScheduler：多一个依赖就多一处版本冲突，而这里只需要「每 30 秒看一眼
有没有到点的任务」，asyncio.wait_for 就够。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any

from approvals import ApprovalStore
from briefing import build_message, excerpt, format_push_text
from client import AgentFlowClient, AgentFlowError
from config import settings
from inputs import attach_inputs
from notifier import NotifyError, send
from runs import RunLog
from store import TaskStore

logger = logging.getLogger("daily-briefing")


def _matches(text: str, pattern: str) -> bool:
    """push_if 正则匹配。

    正则写错时按「命中」处理 —— 宁可多推一次，也不要因为配置笔误静默丢消息。
    """
    pattern = (pattern or "").strip()
    if not pattern:
        return True
    try:
        return re.search(pattern, text) is not None
    except re.error:
        logger.warning("push_if 不是合法正则：%s，按命中处理", pattern)
        return True


async def execute_task(
    task: dict[str, Any],
    store: TaskStore,
    client: AgentFlowClient,
    runlog: RunLog,
    approvals: ApprovalStore,
    *,
    push: bool = True,
    event_text: str | None = None,
) -> tuple[bool, str, str | None]:
    """执行一次任务，返回 ``(是否成功, 简报正文, 推送错误)``。

    执行失败不抛异常 —— 调度器要能继续跑下一个任务；只有手动触发时
    ``/tasks/{id}/run`` 才会把错误转成 HTTP 502。
    """
    message = attach_inputs(build_message(task), task.get("inputs"))
    if event_text:
        message += "\n\n以下是触发本次任务的事件内容，请据此处理：\n" + event_text
    retry = max(0, int(task.get("retry") or 0))
    attempts = retry + 1
    started_at = datetime.now(settings.tz)
    started = time.monotonic()

    logger.info(
        "task %s (%s) -> agent %s, inputs=%d, attempts=%d",
        task["id"], task["name"], task["agent_id"],
        len(task.get("inputs") or []), attempts,
    )

    result = None
    error: str | None = None
    used = 0

    for attempt in range(attempts):
        used = attempt + 1
        try:
            result = await client.run_agent(
                task["agent_id"],
                message,
                skills=task.get("skills") or None,
                timeout=int(task.get("timeout") or 180),
            )
            break
        except AgentFlowError as exc:
            error = str(exc)
            logger.warning("task %s 第 %d/%d 次失败：%s", task["id"], used, attempts, exc)
            if used < attempts:
                await asyncio.sleep(min(8, 2 ** attempt))  # 2s / 4s / 8s

    duration_ms = int((time.monotonic() - started) * 1000)

    if result is None:
        store.mark_run(task["id"], ok=False, error=error, today=started_at.date().isoformat())
        runlog.append({
            "task_id": task["id"],
            "task_name": task.get("name"),
            "started_at": started_at.isoformat(timespec="seconds"),
            "duration_ms": duration_ms,
            "ok": False,
            "attempts": used,
            "push": "none",
            "error": error,
            "excerpt": None,
        })
        return False, "", error

    text = format_push_text(task, result)
    push_error: str | None = None
    push_state = "none"

    if push and task.get("webhook_url"):
        if not _matches(text, task.get("push_if")):
            push_state = "skipped"
            logger.info("task %s 未命中 push_if，跳过推送", task["id"])
        elif task.get("require_approval"):
            # 人在回路：内容先挂起，只发一条带确认链接的通知
            push_state = "pending_approval"
            try:
                approval = approvals.create(
                    task=task,
                    text=text,
                    subject=f"【{task.get('name') or '日报'}】{started_at:%Y-%m-%d}",
                    webhook_url=task["webhook_url"],
                    webhook_kind=task.get("webhook_kind") or "generic",
                )
                link = (
                    f"{settings.public_base_url.rstrip('/')}"
                    f"/approvals/{approval['id']}?token={approval['token']}"
                )
                await send(
                    task["webhook_url"],
                    task.get("webhook_kind") or "generic",
                    f"【待确认】{task.get('name')}\n\n内容已生成，确认后才发送：\n{link}",
                    subject=f"【待确认】{task.get('name')} {started_at:%Y-%m-%d}",
                )
            except (NotifyError, OSError) as exc:
                push_error = str(exc)
                push_state = "failed"
                logger.warning("task %s 待确认通知失败：%s", task["id"], exc)
        else:
            try:
                await send(
                    task["webhook_url"],
                    task.get("webhook_kind") or "generic",
                    text,
                    subject=f"【{task.get('name') or '日报'}】{started_at:%Y-%m-%d}",
                )
                push_state = "ok"
            except NotifyError as exc:
                push_error = str(exc)
                push_state = "failed"
                logger.warning("task %s 推送失败：%s", task["id"], exc)

    store.mark_run(
        task["id"], ok=True, error=push_error, excerpt=excerpt(text),
        today=started_at.date().isoformat(),
    )
    runlog.append({
        "task_id": task["id"],
        "task_name": task.get("name"),
        "started_at": started_at.isoformat(timespec="seconds"),
        "duration_ms": duration_ms,
        "ok": True,
        "attempts": used,
        "push": push_state,
        "error": push_error,
        "excerpt": excerpt(text, 120),
        "chars": len(text),
    })
    return True, text, push_error


async def loop(
    store: TaskStore,
    client: AgentFlowClient,
    runlog: RunLog,
    approvals: ApprovalStore,
    stop_event: asyncio.Event,
    tick_seconds: int = 30,
) -> None:
    logger.info("scheduler started (tick=%ss, tz=%s)", tick_seconds, settings.tz_name)
    while not stop_event.is_set():
        try:
            for task in store.due_tasks(datetime.now(settings.tz)):
                await execute_task(task, store, client, runlog, approvals)
        except Exception:  # 单次 tick 出错不能拖死整个循环
            logger.exception("scheduler tick failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=tick_seconds)
        except asyncio.TimeoutError:
            continue
    logger.info("scheduler stopped")
