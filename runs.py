"""运行历史：JSONL 追加写，超过上限自动裁旧。

为什么用 JSONL 而不是把历史塞进任务对象：追加写不用重写整个文件，
任务多、执行频繁时也不会因为一次写失败丢掉全部历史。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

MAX_RECORDS = 1000


class RunLog:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict) -> None:
        with self._lock:
            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                return
            self._trim()

    def _trim(self) -> None:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) <= MAX_RECORDS:
            return
        try:
            self._path.write_text(
                "\n".join(lines[-MAX_RECORDS:]) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    def list(self, task_id: str | None = None, limit: int = 50) -> list[dict]:
        """按时间倒序返回，最新的在前。"""
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

        records: list[dict] = []
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if task_id and record.get("task_id") != task_id:
                continue
            records.append(record)
            if len(records) >= limit:
                break
        return records

    def stats(self, task_id: str | None = None) -> dict:
        records = self.list(task_id, limit=MAX_RECORDS)
        total = len(records)
        ok = sum(1 for r in records if r.get("ok"))
        return {
            "total": total,
            "ok": ok,
            "failed": total - ok,
            "success_rate": round(ok / total * 100, 1) if total else None,
        }
