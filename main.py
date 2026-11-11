"""AgentFlow · 常驻日报（daily-briefing）

独立扩展服务：不 import 主项目任何模块，只通过 HTTP 使用主后端的
「登录 + PiAgent 同步执行」两个能力。所以它能单独拷走、单独部署、单独开源。

启动：
    python -m uvicorn main:app --host 127.0.0.1 --port 8010
或：
    python main.py
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html as html_mod
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from approvals import ApprovalStore
from client import AgentFlowClient, AgentFlowError
from config import settings
from events import format_event, match_tasks
from notifier import KINDS, NotifyError, send
from runs import RunLog
from scheduler import execute_task, loop
from store import TaskStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("daily-briefing")

store = TaskStore(settings.tasks_file)
runlog = RunLog(settings.runs_file)
approvals = ApprovalStore(settings.approvals_file)
client = AgentFlowClient(settings.base_url, settings.email, settings.password)
stop_event = asyncio.Event()


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = asyncio.create_task(
        loop(store, client, runlog, approvals, stop_event, settings.tick_seconds)
    )
    logger.info("daily-briefing ready (agent=%s, base=%s)", settings.agent_id or "-", settings.base_url)
    try:
        yield
    finally:
        stop_event.set()
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        await client.aclose()


app = FastAPI(
    title="PHAiagent · Personal Help AI Agent",
    description="个人助理智能体：按你的时间点让 Agent 自己干活，结果推到邮件或 IM。独立扩展，不侵入核心代码。",
    version="0.1.0",
    lifespan=lifespan,
)

# 自带管理界面：/ui/。整个 static 目录跟着扩展走，拷走就能用，不依赖主项目前端
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    return RedirectResponse("/ui/")


# ---------------------------- 数据模型 ----------------------------


class TaskIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    agent_id: str | None = None
    schedule: str = Field(..., pattern=r"^\d{1,2}:\d{2}$", description="每天执行时间 HH:MM")
    prompt: str | None = None
    inputs: list[str] | None = Field(default=None, description="本地输入文件，相对扩展目录")
    skills: list[str] | None = None
    webhook_url: str | None = None
    webhook_kind: str | None = Field(default=None, description="generic / wecom / dingtalk / feishu")
    enabled: bool = True
    timeout: int = Field(default=180, ge=30, le=900)
    catch_up: bool = Field(default=True, description="服务晚启动时是否补跑当天")
    retry: int = Field(default=0, ge=0, le=5, description="失败重试次数")
    push_if: str | None = Field(default=None, description="内容匹配该正则才推送，留空总是推送")
    trigger: str = Field(default="cron", pattern=r"^(cron|event)$", description="cron 定时 / event 事件驱动")
    event_source: str | None = Field(default=None, description="限定事件来源，如 github")
    event_filter: str | None = Field(default=None, description="事件正文正则，匹配才触发")
    require_approval: bool = Field(default=False, description="生成后先挂起，等人确认再推送")


class TaskPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    agent_id: str | None = None
    schedule: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")
    prompt: str | None = None
    inputs: list[str] | None = None
    skills: list[str] | None = None
    webhook_url: str | None = None
    webhook_kind: str | None = None
    enabled: bool | None = None
    timeout: int | None = Field(default=None, ge=30, le=900)
    catch_up: bool | None = None
    retry: int | None = Field(default=None, ge=0, le=5)
    push_if: str | None = None
    trigger: str | None = Field(default=None, pattern=r"^(cron|event)$")
    event_source: str | None = None
    event_filter: str | None = None
    require_approval: bool | None = None


# ---------------------------- 接口 ----------------------------


@app.get("/health")
async def health() -> dict:
    """自身状态 + 主后端连通性（不阻塞：主后端异常只体现在 pi.error 里）。"""
    info: dict = {
        "service": "PHAiagent",
        "configured": settings.configured,
        "base_url": settings.base_url,
        "agent_id": settings.agent_id or None,
        "tasks": len(store.list()),
        "webhook_kinds": list(KINDS),
        "tz": settings.tz_name,
    }
    try:
        status = await client.pi_status()
        info["pi"] = {"enabled": status.get("enabled"), "available": status.get("available")}
    except AgentFlowError as exc:
        info["pi"] = {"error": str(exc)}
    return info


@app.get("/tasks")
async def list_tasks() -> list[dict]:
    return store.list()


@app.post("/tasks", status_code=201)
async def create_task(payload: TaskIn) -> dict:
    data = payload.model_dump()
    data["agent_id"] = data.get("agent_id") or settings.agent_id
    data["webhook_url"] = data.get("webhook_url") or settings.webhook_url
    data["webhook_kind"] = data.get("webhook_kind") or settings.webhook_kind
    if not data["agent_id"]:
        raise HTTPException(400, "缺少 agent_id：请在 .env 设置 AGENTFLOW_AGENT_ID，或在任务里指定")
    return store.create(data)


@app.patch("/tasks/{task_id}")
async def patch_task(task_id: str, payload: TaskPatch) -> dict:
    task = store.update(task_id, payload.model_dump(exclude_unset=True))
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@app.delete("/tasks/{task_id}")
async def remove_task(task_id: str) -> dict:
    if not store.delete(task_id):
        raise HTTPException(404, "任务不存在")
    return {"deleted": task_id}


@app.post("/tasks/{task_id}/run")
async def run_task(task_id: str, push: bool = False) -> dict:
    """立即执行一次。``push=true`` 时同时推送（用来测 webhook 是否通）。"""
    task = store.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    ok, text, push_error = await execute_task(task, store, client, runlog, approvals, push=push)
    if not ok:
        raise HTTPException(502, push_error or "执行失败")
    return {"ok": True, "text": text, "push_error": push_error}


@app.get("/runs")
async def list_runs(task_id: str | None = None, limit: int = 50) -> dict:
    """运行历史，最新的在前；同时返回成功率统计。"""
    limit = max(1, min(limit, 200))
    return {
        "records": runlog.list(task_id, limit),
        "stats": runlog.stats(task_id),
    }


# ---------------------------- 事件触发 ----------------------------


@app.post("/events/{source}")
async def receive_event(source: str, request: Request) -> dict:
    """接收外部事件（GitHub webhook / 自建回调），匹配到任务后立即执行。

    任务需设 ``trigger="event"``；``event_source`` / ``event_filter`` 可进一步收窄。
    """
    raw = await request.body()

    if settings.webhook_secret:
        signature = request.headers.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(
            settings.webhook_secret.encode(), raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(401, "签名校验失败")

    payload_text = raw.decode("utf-8", errors="replace")
    tasks = match_tasks(store.list(), source, payload_text)
    if not tasks:
        logger.info("事件 %s 未匹配到任何任务", source)
        return {"source": source, "matched": [], "results": []}

    event_text = format_event(source, payload_text)
    results: list[dict] = []
    for task in tasks:
        ok, _, push_error = await execute_task(
            task, store, client, runlog, approvals, push=True, event_text=event_text
        )
        results.append({"task": task.get("name"), "ok": ok, "error": push_error})
    return {
        "source": source,
        "matched": [t.get("name") for t in tasks],
        "results": results,
    }


# ---------------------------- 审批确认 ----------------------------


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_mod.escape(title)}</title></head>
<body style="margin:0;padding:24px;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif">
<div style="max-width:640px;margin:0 auto;background:#fff;border-radius:16px;padding:26px;box-shadow:0 10px 30px rgba(15,23,42,.08)">
<h1 style="margin:0 0 16px;font-size:18px;color:#0f172a">{html_mod.escape(title)}</h1>
{body}
</div></body></html>"""


@app.get("/approvals")
async def list_approvals(status: str | None = None, limit: int = 20) -> dict:
    return {"records": approvals.list(status, max(1, min(limit, 100)))}


@app.get("/approvals/{approval_id}", response_class=HTMLResponse)
async def approval_page(approval_id: str, token: str = "") -> HTMLResponse:
    record = approvals.get(approval_id)
    if not record:
        raise HTTPException(404, "确认项不存在")
    if not hmac.compare_digest(record.get("token", ""), token):
        raise HTTPException(403, "链接无效")

    if record["status"] != "pending":
        return HTMLResponse(_page(
            "已处理",
            f'<p style="color:#64748b">状态：{record["status"]}'
            f'（{record.get("resolved_at") or "-"}）</p>',
        ))

    body = f"""
      <div style="color:#94a3b8;font-size:12px;margin-bottom:10px">
        {html_mod.escape(record.get("task_name") or "")} · {html_mod.escape(record.get("created_at") or "")}
      </div>
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px;
                  font-size:14px;line-height:1.8;color:#334155;max-height:420px;overflow:auto">
        {html_mod.escape(record["text"]).replace(chr(10), "<br>")}
      </div>
      <div style="margin-top:20px;display:flex;gap:10px">
        <form method="post" action="/approvals/{approval_id}/approve?token={token}" style="margin:0">
          <button type="submit" style="background:#2563eb;color:#fff;border:0;border-radius:8px;
                  padding:9px 18px;font-size:14px;cursor:pointer">确认发送</button>
        </form>
        <form method="post" action="/approvals/{approval_id}/reject?token={token}" style="margin:0">
          <button type="submit" style="background:#fff;color:#475569;border:1px solid #e2e8f0;
                  border-radius:8px;padding:9px 18px;font-size:14px;cursor:pointer">丢弃</button>
        </form>
      </div>"""
    return HTMLResponse(_page("确认后发送", body))


@app.post("/approvals/{approval_id}/approve", response_class=HTMLResponse)
async def approve(approval_id: str, token: str = "") -> HTMLResponse:
    record = approvals.get(approval_id)
    if not record:
        raise HTTPException(404, "确认项不存在")
    if not hmac.compare_digest(record.get("token", ""), token):
        raise HTTPException(403, "链接无效")
    if record["status"] != "pending":
        return HTMLResponse(_page(
            "已处理", f'<p style="color:#64748b">状态：{record["status"]}</p>'
        ))

    try:
        await send(
            record["webhook_url"],
            record["webhook_kind"],
            record["text"],
            subject=record["subject"],
        )
    except NotifyError as exc:
        approvals.resolve(approval_id, "approved", error=str(exc))
        return HTMLResponse(_page(
            "发送失败", f'<p style="color:#b91c1c">{html_mod.escape(str(exc))}</p>'
        ))
    approvals.resolve(approval_id, "approved")
    return HTMLResponse(_page("已发送", '<p style="color:#16a34a">内容已投递。</p>'))


@app.post("/approvals/{approval_id}/reject", response_class=HTMLResponse)
async def reject(approval_id: str, token: str = "") -> HTMLResponse:
    record = approvals.get(approval_id)
    if not record:
        raise HTTPException(404, "确认项不存在")
    if not hmac.compare_digest(record.get("token", ""), token):
        raise HTTPException(403, "链接无效")
    if record["status"] == "pending":
        approvals.resolve(approval_id, "rejected")
    return HTMLResponse(_page("已丢弃", '<p style="color:#64748b">这条内容不会被发送。</p>'))


@app.post("/tasks/{task_id}/test-webhook")
async def test_webhook(task_id: str) -> dict:
    """只测推送通道，不跑 Agent。"""
    task = store.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    try:
        body = await send(
            task.get("webhook_url") or "",
            task.get("webhook_kind") or "generic",
            f"【{task.get('name') or '日报'}】推送通道测试成功",
        )
    except NotifyError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "response": body}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)
