"""配置：环境变量优先，其次读同目录 .env。

刻意不引入 pydantic-settings / python-dotenv —— 这个扩展要保持「拷贝目录 +
装两个包就能跑」，少一个依赖就少一处部署失败。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def load_dotenv(path: Path = ENV_FILE) -> None:
    """极简 .env 解析：KEY=VALUE，支持 # 注释与行内引号。

    已存在的真实环境变量优先，不会被 .env 覆盖（部署时用系统环境变量托管密钥）。
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def _str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _int(key: str, default: int) -> int:
    try:
        return int(_str(key, str(default)))
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    raw = _str(key).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass
class Settings:
    """全部配置项。任何一项都能用环境变量覆盖。"""

    # AgentFlow 主后端（默认本机 8001）
    base_url: str = field(default_factory=lambda: _str("AGENTFLOW_BASE_URL", "http://127.0.0.1:8001"))
    email: str = field(default_factory=lambda: _str("AGENTFLOW_EMAIL"))
    password: str = field(default_factory=lambda: _str("AGENTFLOW_PASSWORD"))

    #: 新建任务时的默认 Agent；单个任务也可以自己指定
    agent_id: str = field(default_factory=lambda: _str("AGENTFLOW_AGENT_ID"))

    #: 新建任务时的默认推送地址与渠道（generic / wecom / dingtalk / feishu / email）
    webhook_url: str = field(default_factory=lambda: _str("DEFAULT_WEBHOOK_URL"))
    webhook_kind: str = field(default_factory=lambda: _str("DEFAULT_WEBHOOK_KIND", "generic"))

    # ---- 邮件通道（kind=email）----
    #: SMTP_* 优先，没有则回退到主项目同名的 MAIL_*，配好发信的部署可直接复用
    smtp_host: str = field(default_factory=lambda: _str("SMTP_HOST") or _str("MAIL_HOST"))
    smtp_port: int = field(default_factory=lambda: _int("SMTP_PORT", _int("MAIL_PORT", 465)))
    smtp_user: str = field(default_factory=lambda: _str("SMTP_USER") or _str("MAIL_USER"))
    smtp_password: str = field(
        default_factory=lambda: _str("SMTP_PASSWORD") or _str("MAIL_PASSWORD")
    )
    smtp_from: str = field(
        default_factory=lambda: _str("SMTP_FROM") or _str("MAIL_FROM") or _str("SMTP_USER")
    )
    smtp_from_name: str = field(
        default_factory=lambda: _str("SMTP_FROM_NAME") or _str("MAIL_FROM_NAME", "PHAiagent")
    )
    smtp_use_ssl: bool = field(
        default_factory=lambda: _bool("SMTP_USE_SSL", _bool("MAIL_USE_SSL", True))
    )
    smtp_timeout: int = field(
        default_factory=lambda: _int("SMTP_TIMEOUT", _int("MAIL_TIMEOUT", 20))
    )
    #: 任务的 webhook_url 留空时用的默认收件人（逗号分隔）
    smtp_to: str = field(default_factory=lambda: _str("MAIL_TO"))

    #: 时区：调度按这个时区判断「几点」和「今天跑过没有」，服务器时区不对也不会错点
    tz_name: str = field(default_factory=lambda: _str("TZ", "Asia/Shanghai"))

    #: 扩展自己的对外地址，审批链接用它拼；部署到公网要改成真实域名
    public_base_url: str = field(
        default_factory=lambda: _str("PUBLIC_BASE_URL", "http://127.0.0.1:8010")
    )
    #: 事件来源验签（GitHub 的 X-Hub-Signature-256）；留空表示不校验，仅内网用
    webhook_secret: str = field(default_factory=lambda: _str("WEBHOOK_SECRET"))

    #: 服务自身
    host: str = field(default_factory=lambda: _str("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", 8010))
    tick_seconds: int = field(default_factory=lambda: _int("TICK_SECONDS", 30))

    #: 任务数据目录（JSON 文件，不依赖数据库）
    data_dir: Path = field(default_factory=lambda: BASE_DIR / _str("DATA_DIR", "data"))

    @property
    def tasks_file(self) -> Path:
        return self.data_dir / "tasks.json"

    @property
    def runs_file(self) -> Path:
        return self.data_dir / "runs.jsonl"

    @property
    def approvals_file(self) -> Path:
        return self.data_dir / "approvals.json"

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.tz_name)
        except Exception:  # noqa: BLE001  时区名写错就退回 UTC，别让服务起不来
            return ZoneInfo("UTC")

    @property
    def configured(self) -> bool:
        """账号 + Agent 都配了才算可用。"""
        return bool(self.email and self.password and self.agent_id)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
