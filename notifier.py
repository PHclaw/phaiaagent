"""推送适配：generic / 企业微信 / 钉钉 / 飞书 / 邮件。

前四种都是「POST 一个 JSON、看 HTTP 状态」，用映射表覆盖；邮件走标准库
smtplib，不引第三方依赖。

邮件通道的 SMTP 配置与主项目同名（``MAIL_*``）也能直接复用：扩展内优先读
``SMTP_*``，没有就回退到 ``MAIL_*``，这样已经在主项目配好发信的部署不用重配。

HTML 排版只用了 table + 内联样式：Gmail 会剥掉 ``<style>`` 和 class，
flex/grid 在 Outlook 上基本不认，所以视觉全部压在 table 和内联样式上。
"""
from __future__ import annotations

import asyncio
import html as html_mod
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import httpx

from config import settings

KINDS = ("generic", "wecom", "dingtalk", "feishu", "email")

_WEEKDAYS = "一二三四五六日"

# 邮件里的品牌动画：GIF 是主流邮箱唯一普遍支持的动图，首帧是静态 logo，
# 只显示首帧的客户端（如 Outlook 桌面版）也不会出现空白。
MORPH_GIF = Path(__file__).resolve().parent / "static" / "phaiaagent-morph.gif"


class NotifyError(RuntimeError):
    """推送失败。"""


# ---------------------------------------------------------------- HTTP 渠道


def build_payload(kind: str, text: str) -> dict:
    kind = (kind or "generic").lower()
    if kind in ("wecom", "dingtalk"):
        return {"msgtype": "text", "text": {"content": text}}
    if kind == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    return {"text": text}


async def _send_http(url: str, kind: str, text: str) -> str:
    payload = build_payload(kind, text)
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise NotifyError(f"推送请求失败：{exc}") from exc

    if r.status_code >= 300:
        raise NotifyError(f"推送失败 HTTP {r.status_code}：{r.text[:200]}")

    body = (r.text or "")[:200]
    # 企业微信/钉钉/飞书都用 200 + errcode 表达业务失败
    lowered = body.lower()
    if '"errcode":0' not in lowered and any(
        key in lowered for key in ('"errcode"', '"code"')
    ):
        if '"errcode":0' not in lowered and '"code":0' not in lowered:
            raise NotifyError(f"推送被拒：{body}")
    return body


# ---------------------------------------------------------------- 邮件渠道


def _parse_subject(subject: str) -> tuple[str, str]:
    """``【每日简报】2026-11-10`` → (``每日简报``, ``2026-11-10``)。"""
    match = re.match(r"^[【\[](.+?)[】\]]\s*(.*)$", (subject or "").strip())
    if match:
        return match.group(1).strip() or "每日简报", match.group(2).strip()
    return (subject or "每日简报").strip(), ""


def _with_weekday(date_label: str) -> str:
    try:
        day = datetime.strptime(date_label, "%Y-%m-%d")
    except ValueError:
        return date_label
    return f"{date_label} 星期{_WEEKDAYS[day.weekday()]}"


def _inline(raw: str) -> str:
    """转义 + 只保留加粗，避免邮件里出现未闭合标签。"""
    escaped = html_mod.escape(raw)
    return re.sub(r"\*\*(.+?)\*\*", r'<strong style="color:#0f172a">\1</strong>', escaped)


def _markdown_to_html(text: str, title: str, date_label: str) -> str:
    blocks: list[str] = []
    table_rows: list[str] = []

    def flush_table() -> str:
        """连续的 | 行渲染成 table（邮件客户端只认 table + 内联样式）。"""
        rows: list[list[str]] = []
        for row in table_rows:
            if re.match(r"^\|[\s:\-|]+\|$", row):  # 跳过 |---|---| 分隔行
                continue
            rows.append([c.strip() for c in row.strip().strip("|").split("|")])
        table_rows.clear()
        if not rows:
            return ""

        parts = [
            '<table role="presentation" cellpadding="0" cellspacing="0" width="100%"'
            ' style="margin:10px 0 16px;border-collapse:collapse;font-size:13px">'
        ]
        parts.append(
            "<tr>"
            + "".join(
                '<th style="background:#f1f5f9;color:#0f172a;text-align:left;'
                'padding:8px 10px;border:1px solid #e2e8f0;font-weight:600">'
                f"{_inline(c)}</th>"
                for c in rows[0]
            )
            + "</tr>"
        )
        for row in rows[1:]:
            parts.append(
                "<tr>"
                + "".join(
                    '<td style="color:#334155;padding:8px 10px;border:1px solid #e2e8f0;'
                    f'line-height:1.6">{_inline(c)}</td>'
                    for c in row
                )
                + "</tr>"
            )
        parts.append("</table>")
        return "".join(parts)

    for raw in text.split("\n"):
        line = raw.rstrip()

        # 表格行先攒着，遇到非表格行再一次性渲染
        if line.startswith("|") and line.endswith("|"):
            table_rows.append(line)
            continue
        if table_rows:
            blocks.append(flush_table())

        if not line:
            continue

        # 二级标题 = 分节小标题
        if line.startswith("## "):
            blocks.append(
                '<div style="margin:20px 0 10px;color:#0f172a;font-size:15px;'
                f'font-weight:600">{_inline(line[3:])}</div>'
            )
            continue

        # 无序列表：table 两列，圆点在邮件客户端里比 ::before 可靠
        if line.startswith("- "):
            blocks.append(
                '<table role="presentation" cellpadding="0" cellspacing="0" width="100%"'
                ' style="margin:0 0 10px">'
                "<tr>"
                '<td width="14" valign="top"'
                ' style="color:#2563eb;font-size:14px;line-height:1.8">&#8226;</td>'
                f'<td style="color:#334155;font-size:14px;line-height:1.8">{_inline(line[2:])}</td>'
                "</tr></table>"
            )
            continue

        # 整行加粗 = 结论，做成高亮块
        if line.startswith("**") and line.endswith("**") and len(line) > 4:
            blocks.append(
                '<div style="margin:18px 0;padding:12px 14px;background:#eff6ff;'
                "border-left:3px solid #2563eb;border-radius:6px;color:#1e3a8a;"
                'font-size:14px;line-height:1.75;font-weight:600">'
                f"{_inline(line[2:-2])}</div>"
            )
            continue

        # 引用块 = 备注说明，左边细线 + 灰字
        if line.startswith("> "):
            blocks.append(
                '<p style="margin:14px 0 0;padding-left:10px;border-left:2px solid #e2e8f0;'
                f'color:#94a3b8;font-size:12px;line-height:1.7">{_inline(line[2:])}</p>'
            )
            continue

        # 括号备注 = 免责说明，压成灰色小字
        if line.startswith(("（", "(")) and line.endswith(("）", ")")):
            blocks.append(
                '<p style="margin:14px 0 0;color:#94a3b8;font-size:12px;'
                f'line-height:1.7">{_inline(line)}</p>'
            )
            continue

        blocks.append(
            '<p style="margin:0 0 10px;color:#334155;font-size:14px;'
            f'line-height:1.8">{_inline(line)}</p>'
        )

    if table_rows:  # 正文以表格结尾时也要收尾
        blocks.append(flush_table())

    body = "\n".join(blocks)

    return f"""\
<div style="margin:0;padding:28px 12px;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:600px;margin:0 auto">
    <tr>
      <td style="background:#0f172a;border-radius:14px 14px 0 0;padding:22px 26px">
        <img src="cid:phaiaagent-morph" width="160" height="48" alt="PHAiagent" style="display:block;border:0;outline:none;text-decoration:none">
        <div style="color:#f8fafc;font-size:18px;font-weight:600;letter-spacing:0.2px;margin-top:12px">{html_mod.escape(title)}</div>
        <div style="color:#94a3b8;font-size:12px;margin-top:6px">{html_mod.escape(date_label)}</div>
      </td>
    </tr>
    <tr>
      <td style="background:#ffffff;padding:26px;border-radius:0 0 14px 14px">
{body}
      </td>
    </tr>
    <tr>
      <td style="padding:16px 10px 0;color:#94a3b8;font-size:11px;line-height:1.7;text-align:center">
        PHAiagent · Personal Help AI Agent<br>
        自动生成，调整时间或内容请改任务配置
      </td>
    </tr>
  </table>
</div>"""


def _send_mail_sync(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    sender: str,
    sender_name: str,
    recipients: list[str],
    subject: str,
    text: str,
    use_ssl: bool,
    timeout: int,
) -> str:
    if not host:
        raise NotifyError("未配置 SMTP：请在 .env 设置 SMTP_HOST（或复用 MAIL_HOST）")
    if not recipients:
        raise NotifyError("未配置收件人：任务的 webhook_url 填邮箱，或设置 MAIL_TO")
    if not sender:
        raise NotifyError("未配置发件人：请设置 SMTP_FROM（或 MAIL_FROM）")

    title, date_label = _parse_subject(subject)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, sender))
    msg["To"] = ", ".join(recipients)

    # 标准嵌套：multipart/related 包住 multipart/alternative，图片和 HTML 同处
    # 一个 related 容器，cid 才能被客户端解析。
    # 顺序不能反 —— email 库不允许 alternative → related 的转换（会抛 ValueError）。
    msg.make_related()
    alternative = EmailMessage()
    alternative.set_content(text)                            # 纯文本兜底
    alternative.add_alternative(
        _markdown_to_html(text, title, _with_weekday(date_label) or datetime.now().strftime("%Y-%m-%d")),
        subtype="html",
    )
    msg.attach(alternative)

    # 内联附件：不依赖公网图片地址，邮箱禁用外链也能显示
    if MORPH_GIF.exists():
        msg.add_related(
            MORPH_GIF.read_bytes(),
            maintype="image",
            subtype="gif",
            cid="<phaiaagent-morph>",
        )

    server: smtplib.SMTP | None = None
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
            server.starttls()
        if user:
            server.login(user, password)
        server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        # 超时 / 连接被拒 / 认证失败都归到推送错误里，让调度器继续跑，
        # 而不是冒泡成 500 把「内容已生成」这个结果也弄丢
        raise NotifyError(f"SMTP 连接或发送失败：{exc}") from exc
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:  # noqa: BLE001  关闭失败不影响"已发送"的结论
                pass

    return f"已发送至 {', '.join(recipients)}"


async def _send_email(url: str, subject: str, text: str) -> str:
    """``url`` 在这里是收件人列表（逗号分隔），为空则用 MAIL_TO。"""
    raw = (url or "").strip() or settings.smtp_to
    recipients = [addr.strip() for addr in re.split(r"[,;]", raw) if addr.strip()]

    return await asyncio.to_thread(
        _send_mail_sync,
        host=settings.smtp_host,
        port=settings.smtp_port,
        user=settings.smtp_user,
        password=settings.smtp_password,
        sender=settings.smtp_from,
        sender_name=settings.smtp_from_name,
        recipients=recipients,
        subject=subject,
        text=text,
        use_ssl=settings.smtp_use_ssl,
        timeout=settings.smtp_timeout,
    )


# ---------------------------------------------------------------- 统一入口


async def send(url: str, kind: str, text: str, *, subject: str = "AgentFlow 日报") -> str:
    """推送一条消息，返回可读的结果说明。

    ``kind="email"`` 时 ``url`` 填收件人邮箱（可逗号分隔多个），
    也可以留空改用 ``MAIL_TO``。
    """
    kind = (kind or "generic").lower()

    if kind == "email":
        return await _send_email(url, subject, text)

    if not url:
        raise NotifyError("未配置 webhook 地址")
    return await _send_http(url, kind, text)
