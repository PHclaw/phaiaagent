"""任务存储：一个 JSON 文件 + 进程内锁。

为什么不接数据库：这个扩展要能被单独拷走部署，SQLite 迁移、Alembic、连接池
都会把它和主项目重新绑在一起。任务数量在个位数到几十条，JSON 完全够用。
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().date().isoformat()


class TaskStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write([])

    # ---- 底层读写 ----

    def _read(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8")) or []
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, tasks: list[dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)  # 原子替换，避免写一半被调度器读到

    # ---- 对外接口 ----

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read()

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((t for t in self._read() if t["id"] == task_id), None)

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            tasks = self._read()
            task = {
                "id": uuid.uuid4().hex[:12],
                "name": data["name"],
                "agent_id": data["agent_id"],
                "schedule": data["schedule"],          # "HH:MM"
                "prompt": data.get("prompt") or "",
                "inputs": data.get("inputs") or [],   # 本地输入文件（相对扩展目录）
                "skills": data.get("skills") or [],
                "webhook_url": data.get("webhook_url") or "",
                "webhook_kind": data.get("webhook_kind") or "generic",
                "enabled": bool(data.get("enabled", True)),
                "timeout": int(data.get("timeout") or 180),
                "catch_up": bool(data.get("catch_up", True)),
                "retry": max(0, int(data.get("retry") or 0)),      # 失败重试次数
                "push_if": data.get("push_if") or "",               # 内容命中才推送（正则）
                "trigger": data.get("trigger") or "cron",           # cron / event
                "event_source": data.get("event_source") or "",     # 限定事件来源
                "event_filter": data.get("event_filter") or "",     # 事件正文正则
                "require_approval": bool(data.get("require_approval", False)),

                "created_at": _now_iso(),
                "last_run_at": None,
                "last_run_date": None,
                "last_status": None,                  # ok / error
                "last_error": None,
                "last_excerpt": None,
            }
            tasks.append(task)
            self._write(tasks)
            return task

    def update(self, task_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task["id"] != task_id:
                    continue
                for key in (
                    "name", "agent_id", "schedule", "prompt", "inputs", "skills",
                    "webhook_url", "webhook_kind", "enabled", "timeout", "catch_up",
                    "retry", "push_if", "trigger", "event_source", "event_filter",
                    "require_approval",
                ):
                    if key in patch and patch[key] is not None:
                        task[key] = patch[key]
                self._write(tasks)
                return task
            return None

    def delete(self, task_id: str) -> bool:
        with self._lock:
            tasks = self._read()
            kept = [t for t in tasks if t["id"] != task_id]
            if len(kept) == len(tasks):
                return False
            self._write(kept)
            return True

    def mark_run(self, task_id: str, *, ok: bool, error: str | None = None,
                 excerpt: str | None = None, today: str | None = None) -> None:
        with self._lock:
            tasks = self._read()
            for task in tasks:
                if task["id"] != task_id:
                    continue
                task["last_run_at"] = _now_iso()
                # 用调用方给的日期（调度器按配置时区算），避免服务器时区不同导致误判
                task["last_run_date"] = today or _today()
                task["last_status"] = "ok" if ok else "error"
                task["last_error"] = error
                task["last_excerpt"] = (excerpt or "")[:400]
                break
            self._write(tasks)

    def due_tasks(self, now: datetime) -> list[dict[str, Any]]:
        """到点且今天还没跑过的任务。

        ``catch_up`` 打开时，服务重启晚了也会补跑当天这一班；关掉则只在
        命中那一分钟内执行。
        """
        due: list[dict[str, Any]] = []
        today = now.date().isoformat()
        for task in self._read():
            if not task.get("enabled", True):
                continue
            if task.get("last_run_date") == today:
                continue
            try:
                hour, minute = (int(x) for x in str(task["schedule"]).split(":"))
            except (ValueError, KeyError):
                continue
            scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if task.get("catch_up", True):
                if now >= scheduled:
                    due.append(task)
            elif now.hour == hour and now.minute == minute:
                due.append(task)
        return due
