"""AgentFlow 主后端客户端。

只依赖 HTTP：登录换 token → 调 PiAgent 同步执行接口。扩展本身不 import 主项目
任何模块，所以能被单独拷走、单独升级。

连接池是**长驻**的：健康检查和调度都会反复打主后端，每次新建 AsyncClient
在 Windows 上要花几秒（连接 + TLS 上下文初始化），会让 /health 看起来像挂了。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx


class AgentFlowError(RuntimeError):
    """调用主后端失败（网络、鉴权、配额或执行错误）。"""


class AgentFlowClient:
    def __init__(self, base_url: str, email: str, password: str):
        self._base = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._token: str | None = None
        self._expires_at: datetime | None = None
        # 连接池复用；超时由每次 request 自己指定
        self._http = httpx.AsyncClient(timeout=30, follow_redirects=True)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---- 鉴权 ----

    async def _login(self) -> str:
        if not self._email or not self._password:
            raise AgentFlowError(
                "未配置账号：请在 .env 里设置 AGENTFLOW_EMAIL 与 AGENTFLOW_PASSWORD"
            )
        try:
            r = await self._http.post(
                f"{self._base}/api/v1/auth/login",
                json={"email": self._email, "password": self._password},
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise AgentFlowError(f"连不上主后端 {self._base}：{exc}") from exc

        if r.status_code != 200:
            raise AgentFlowError(f"登录失败 HTTP {r.status_code}：{r.text[:200]}")
        token = r.json().get("token")
        if not token:
            raise AgentFlowError("登录响应里没有 token")
        self._token = token
        # 主后端 token 默认 7 天，这里按 6 小时主动续一次，避免长期运行时被踢
        self._expires_at = datetime.now() + timedelta(hours=6)
        return token

    async def _headers(self, force_login: bool = False) -> dict[str, str]:
        expired = self._expires_at is None or datetime.now() >= self._expires_at
        if force_login or not self._token or expired:
            await self._login()
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        timeout = kwargs.pop("timeout", 30)
        headers = await self._headers()
        try:
            r = await self._http.request(
                method, f"{self._base}{path}", headers=headers, timeout=timeout, **kwargs
            )
            if r.status_code == 401:  # token 失效就重登一次，不把失败抛给调度器
                headers = await self._headers(force_login=True)
                r = await self._http.request(
                    method, f"{self._base}{path}", headers=headers, timeout=timeout, **kwargs
                )
        except httpx.HTTPError as exc:
            raise AgentFlowError(f"请求 {path} 失败：{exc}") from exc
        return r

    # ---- 能力 ----

    async def pi_status(self, timeout: float = 8) -> dict[str, Any]:
        r = await self._request("GET", "/api/v1/pi/status", timeout=timeout)
        if r.status_code != 200:
            raise AgentFlowError(f"PiAgent 状态查询失败 HTTP {r.status_code}")
        return r.json()

    async def run_agent(
        self,
        agent_id: str,
        message: str,
        *,
        skills: list[str] | None = None,
        timeout: int = 180,
    ) -> dict[str, Any]:
        """同步执行一轮对话，返回 ``{success, content, files, session_id}``。

        固定 ``new_session=True``：每次日报独立成一段会话，避免上下文越滚越大，
        也方便在「对话记录」里按天翻阅。
        """
        payload: dict[str, Any] = {
            "message": message,
            "new_session": True,
            "timeout": timeout,
        }
        if skills:
            payload["skills"] = skills

        r = await self._request(
            "POST",
            f"/api/v1/pi/{agent_id}/run",
            json=payload,
            timeout=timeout + 30,
        )
        if r.status_code == 503:
            raise AgentFlowError(
                "PiAgent 未启用：请在主后端 .env 设置 PIAGENT_ENABLED=true 并重启"
            )
        if r.status_code == 402:
            raise AgentFlowError("消息额度已用完：请调整套餐或清理任务频率")
        if r.status_code != 200:
            raise AgentFlowError(f"执行失败 HTTP {r.status_code}：{r.text[:300]}")

        data = r.json()
        if not data.get("success", False):
            raise AgentFlowError(data.get("error") or "Agent 执行返回失败")
        return data
