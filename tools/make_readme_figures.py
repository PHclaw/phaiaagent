"""生成 README 用的两张图（纯静态 SVG，GitHub 可直接渲染）。

  assets/flow.svg     一条消息从触发到送达的完整链路
  assets/compare.svg  「普通提醒」与 PHAiagent 的产出对比

改配色或文案只动本文件，重跑即可。
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets"

INK = "#0f172a"
BLUE = "#2563eb"
SKY = "#0ea5e9"
GRAY = "#64748b"
MUTED = "#94a3b8"
LINE = "#e2e8f0"
WASH = "#f8fafc"
GREEN = "#16a34a"
AMBER = "#f59e0b"
RED = "#dc2626"

FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
    "'Microsoft YaHei',sans-serif"
)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=13, color=INK, weight=400, anchor="start", family=None):
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
        f'font-weight="{weight}" text-anchor="{anchor}" '
        f'font-family="{family or FONT}">{esc(s)}</text>'
    )


def rect(x, y, w, h, fill=WASH, stroke=LINE, r=12, sw=1.5, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'
    )


def arrow(x1, y1, x2, y2, color=BLUE, w=1.8):
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
        f'stroke-width="{w}" marker-end="url(#head)"/>'
    )


# ------------------------------------------------------------------ flow.svg

def build_flow() -> str:
    W, H = 1040, 502
    s: list[str] = []

    s.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="PHAiagent 工作链路">')
    s.append("<title>PHAiagent · 一条内容从触发到送达</title>")
    s.append(
        "<defs>"
        f'<marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{BLUE}"/></marker>'
        "</defs>"
    )
    s.append(rect(0, 0, W, H, fill="#ffffff", stroke="#ffffff", r=0))

    # 标题
    s.append(text(40, 54, "一条内容从触发到送达", 24, INK, 700))
    s.append(text(40, 82, "五段都是可配置的，换一份数据就换一个场景", 13, GRAY))

    stages = [
        ("TRIGGER", "触发", "定时到点", "事件 webhook", "手动点一下"),
        ("INPUTS", "取数", "本地 CSV / 日志", "事件正文", "不碰云端账号"),
        ("REASONING", "判断", "算金额、排优先级", "判断能否发布", "合并归纳"),
        ("GATE", "把关", "没风险不出声", "内容命中才推", "要发先问你"),
        ("DELIVER", "交付", "邮件 · 企微", "钉钉 · 飞书", "自定义 webhook"),
    ]

    # 5 个框 × 160 + 4 个间隙 × 38 = 952，左边距 40，右边距 48，不溢出
    bw, gap, top = 160, 38, 118
    bh = 168
    for i, (tag, name, l1, l2, l3) in enumerate(stages):
        x = 40 + i * (bw + gap)
        accent = BLUE if i < 4 else GREEN
        s.append(rect(x, top, bw, bh, fill="#ffffff", stroke=LINE, r=14))
        s.append(rect(x, top, bw, 5, fill=accent, stroke=accent, r=2))
        s.append(text(x + 18, top + 32, tag, 10, MUTED, 700))
        s.append(text(x + 18, top + 60, name, 19, INK, 700))
        for j, line in enumerate((l1, l2, l3)):
            s.append(text(x + 18, top + 92 + j * 23, line, 12, GRAY))

        if i < len(stages) - 1:
            ax1 = x + bw + 6
            ax2 = x + bw + gap - 6
            mid = top + bh // 2
            s.append(arrow(ax1, mid, ax2, mid))

    # 底部基础层
    infra_y = top + bh + 46
    s.append(text(40, infra_y - 12, "底下一直开着的", 11, MUTED, 700))
    chips = ["调度器 30s", "运行历史", "失败重试", "按 TZ 判断日期", "待确认队列"]
    cx = 40
    for chip in chips:
        w = 22 + len(chip) * 12
        s.append(rect(cx, infra_y, w, 34, fill=WASH, stroke=LINE, r=17))
        s.append(text(cx + w / 2, infra_y + 22, chip, 12, GRAY, 500, "middle"))
        cx += w + 12

    # 结论条
    bar_y = infra_y + 62
    s.append(rect(40, bar_y, W - 80, 56, fill="#eff6ff", stroke="#bfdbfe", r=12))
    s.append(text(62, bar_y + 24, "不申请邮箱、日历、网盘任何 OAuth", 14, "#1e3a8a", 600))
    s.append(text(62, bar_y + 44, "只读你放在本机的文件 —— 数据不出机器，每一行都能改", 12, BLUE))

    s.append("</svg>")
    return "\n".join(s)


# --------------------------------------------------------------- compare.svg

def build_compare() -> str:
    W, H = 940, 462
    s: list[str] = []

    s.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="普通提醒与 PHAiagent 的对比">')
    s.append("<title>同一个 09:00，产出不一样</title>")
    s.append(
        "<defs>"
        f'<marker id="head2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
        f'markerHeight="8" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{BLUE}"/></marker>'
        "</defs>"
    )
    s.append(rect(0, 0, W, H, fill="#ffffff", stroke="#ffffff", r=0))

    s.append(text(W / 2, 50, "同一个 09:00，产出不一样", 24, INK, 700, "middle"))
    s.append(text(W / 2, 76, "左边是提醒，右边是替你做完了一步", 13, GRAY, 400, "middle"))

    # 左：普通提醒
    lx, ly, lw, lh = 40, 110, 350, 300
    s.append(rect(lx, ly, lw, lh, fill=WASH, stroke=LINE, r=16))
    s.append(text(lx + 24, ly + 36, "普通提醒软件", 15, GRAY, 600))
    s.append(rect(lx + 24, ly + 54, lw - 48, 168, fill="#ffffff", stroke=LINE, r=10))
    s.append(text(lx + 44, ly + 86, "09:00", 11, MUTED, 600))
    s.append(text(lx + 44, ly + 116, "记得看项目进度", 16, "#475569", 600))
    s.append(text(lx + 44, ly + 148, "（这句话是上周你自己写的）", 11, MUTED))
    s.append(text(lx + 24, ly + 252, "· 到点必响，内容不会变", 12, GRAY))
    s.append(text(lx + 24, ly + 276, "· 不知道你手头有什么", 12, GRAY))

    # 箭头
    s.append(f'<line x1="410" y1="260" x2="520" y2="260" stroke="{BLUE}" stroke-width="2" marker-end="url(#head2)"/>')
    s.append(text(465, 246, "换成", 11, BLUE, 600, "middle"))

    # 右：PHAiagent
    rx, ry, rw, rh = 540, 110, 360, 300
    s.append(rect(rx, ry, rw, rh, fill="#ffffff", stroke="#bfdbfe", r=16))
    s.append(rect(rx, ry, rw, 5, fill=BLUE, stroke=BLUE, r=3))
    s.append(text(rx + 24, ry + 36, "PHAiagent", 15, BLUE, 700))

    rows = [
        (RED, "[今天到期]", "客户演示材料 · 15:00 评审"),
        (AMBER, "[1 天内]", "服务器续费 · 卡号快过期"),
        (SKY, "[2 天内]", "API 文档 · 等前端确认字段"),
    ]
    for i, (color, tag, body) in enumerate(rows):
        y = ry + 58 + i * 44
        s.append(rect(rx + 24, y, rw - 48, 36, fill=WASH, stroke=LINE, r=9))
        s.append(rect(rx + 24, y, 4, 36, fill=color, stroke=color, r=2))
        s.append(text(rx + 38, y + 23, tag, 11, color, 700))
        s.append(text(rx + 108, y + 23, body, 12, "#334155"))

    s.append(rect(rx + 24, ry + 198, rw - 48, 56, fill="#eff6ff", stroke="#bfdbfe", r=10))
    s.append(text(rx + 38, ry + 220, "读的是 deadlines.csv，不是猜的", 12, "#1e3a8a", 600))
    s.append(text(rx + 38, ry + 240, "已完成项自动略过，剩几天它自己算", 11, BLUE))

    s.append(text(rx + 24, ry + 276, "· 有风险才响，没风险只记账", 12, GRAY))

    s.append("</svg>")
    return "\n".join(s)


# ---------------------------------------------------------------- banner.svg

PIXELS = [
    "................",
    "...##########...",
    "..############..",
    ".##############.",
    ".##############.",
    ".######pppp####.",
    ".######p##p####.",
    ".######p##p####.",
    ".######pppp####.",
    ".######p#######.",
    ".######p#######.",
    ".######p#######.",
    ".##############.",
    "..############..",
    "...###..........",
    "..###...........",
]


def build_banner() -> str:
    W, H = 1200, 300
    s: list[str] = []

    s.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="PHAiagent">')
    s.append("<title>PHAiagent · Personal Help AI Agent</title>")
    s.append(
        "<defs>"
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#0b1220"/>'
        '<stop offset="0.55" stop-color="#0f172a"/>'
        '<stop offset="1" stop-color="#111f3a"/>'
        "</linearGradient>"
        '<linearGradient id="mark" gradientUnits="userSpaceOnUse" x1="570" y1="42" x2="630" y2="102">'
        '<stop offset="0" stop-color="#1d4ed8"/>'
        '<stop offset="1" stop-color="#22d3ee"/>'
        "</linearGradient>"
        "</defs>"
    )
    s.append(rect(0, 0, W, H, fill="url(#bg)", stroke="url(#bg)", r=0))

    # 背景点阵，像素味的氛围
    for gx in range(24, W, 28):
        for gy in range(22, H, 28):
            s.append(f'<circle cx="{gx}" cy="{gy}" r="1.1" fill="#1e293b"/>')

    # 像素 logo
    cell, side = 5, 80
    ox, oy = (W - side) / 2, 30
    for y, row in enumerate(PIXELS):
        for x, ch in enumerate(row):
            fill = "#ffffff" if ch == "#" else "url(#mark)" if ch == "p" else None
            if fill:
                s.append(
                    f'<rect x="{ox + x * cell}" y="{oy + y * cell}" '
                    f'width="{cell}" height="{cell}" fill="{fill}"/>'
                )

    s.append(text(W / 2, 152, "PHAiagent", 46, "#f8fafc", 700, "middle"))
    s.append(text(W / 2, 180, "PERSONAL HELP AI AGENT", 12, "#60a5fa", 600, "middle"))

    # 三个关键词 chips
    chips = ["读你的数据", "自己判断", "要发先问你"]
    widths = [len(c) * 13 + 34 for c in chips]
    total = sum(widths) + 12 * (len(chips) - 1)
    cx = (W - total) / 2
    for chip, w in zip(chips, widths):
        s.append(
            f'<rect x="{cx}" y="206" width="{w}" height="30" rx="15" '
            f'fill="rgba(96,165,250,0.12)" stroke="rgba(96,165,250,0.35)" stroke-width="1"/>'
        )
        s.append(text(cx + w / 2, 226, chip, 12, "#93c5fd", 500, "middle"))
        cx += w + 12

    s.append(text(W / 2, 268, "定时 · 事件 · 人工确认 · 全本地运行", 12, "#64748b", 400, "middle"))

    s.append("</svg>")
    return "\n".join(s)


OUT.mkdir(parents=True, exist_ok=True)
figures = (
    ("banner.svg", build_banner()),
    ("flow.svg", build_flow()),
    ("compare.svg", build_compare()),
)
for name, content in figures:
    path = OUT / name
    path.write_text(content, encoding="utf-8")
    print(f"{path} : {len(content)} 字符")

# 校验
import xml.etree.ElementTree as ET

for name in ("flow.svg", "compare.svg"):
    path = OUT / name
    root = ET.parse(path).getroot()
    text_nodes = len([e for e in root.iter() if e.tag.endswith("text")])
    print(f"{name}: XML OK, viewBox={root.attrib.get('viewBox')}, text={text_nodes}")
