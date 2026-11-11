"""待确认动作（人在回路）。

任务配了 require_approval 时，内容生成后不直接推送，而是先挂起、发一条
带确认链接的通知；人点「确认发送」才真正投递，点「丢弃」就作废。

链接里带一次性 token，防止别人猜到 id 就能替你群发。
"""
from __future__ import annotations

import json
import secrets
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class ApprovalStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            self._write([])

    def _read(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8")) or []
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, items: list[dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def create(
        self,
        *,
        task: dict[str, Any],
        text: str,
        subject: str,
        webhook_url: str,
        webhook_kind: str,
    ) -> dict[str, Any]:
        with self._lock:
            items = self._read()
            record = {
                "id": uuid.uuid4().hex[:12],
                "token": secrets.token_urlsafe(18),
                "task_id": task["id"],
                "task_name": task.get("name"),
                "text": text,
                "subject": subject,
                "webhook_url": webhook_url,
                "webhook_kind": webhook_kind,
                "status": "pending",          # pending / approved / rejected
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "resolved_at": None,
                "error": None,
            }
            items.append(record)
            # 只留最近 200 条，避免文件无限增长
            self._write(items[-200:])
            return record

    def get(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((x for x in self._read() if x["id"] == approval_id), None)

    def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = self._read()
        if status:
            items = [x for x in items if x["status"] == status]
        return list(reversed(items))[:limit]

    def resolve(self, approval_id: str, status: str, error: str | None = None) -> dict | None:
        with self._lock:
            items = self._read()
            for item in items:
                if item["id"] != approval_id:
                    continue
                item["status"] = status
                item["resolved_at"] = datetime.now().isoformat(timespec="seconds")
                item["error"] = error
                self._write(items)
                return item
            return None
