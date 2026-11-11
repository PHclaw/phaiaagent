"""任务输入：把本地文件内容拼进提示词。

这是「场景包」的关键一层 —— PHAiagent 不用申请邮箱 / 日历 OAuth，
只读你放在扩展目录里的文件就能拿到「我的」数据。

目前支持本地文件；后续 URL / API 读取器接在这里即可，任务模型不用改。
"""
from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAX_BYTES = 200_000  # 单个文件最多读 200KB，避免把提示词撑爆


def _read_one(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""

    path = (BASE_DIR / raw).resolve()

    # 目录穿越防护：只允许读扩展目录内的文件。
    # 绝对路径会在 resolve 后落到别处，同样被拦下。
    if path != BASE_DIR and BASE_DIR not in path.parents:
        return f"--- {raw} ---\n[已跳过：路径超出扩展目录]"
    if not path.is_file():
        return f"--- {raw} ---\n[文件不存在]"

    try:
        text = path.read_bytes()[:MAX_BYTES].decode("utf-8", errors="replace")
    except OSError as exc:
        return f"--- {raw} ---\n[读取失败：{exc}]"
    return f"--- {raw} ---\n{text.strip()}"


def attach_inputs(message: str, paths: list[str] | None) -> str:
    """把输入资料接在提示词后面；没有 inputs 时原样返回（旧任务零影响）。"""
    if not paths:
        return message

    blocks = [block for block in (_read_one(p) for p in paths) if block]
    if not blocks:
        return message

    return (
        message.rstrip()
        + "\n\n以下是本次输入资料。只依据这些资料作答，不要编造清单以外的任务、日期或数字：\n\n"
        + "\n\n".join(blocks)
    )
