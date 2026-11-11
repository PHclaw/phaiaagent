"""生成 PHAiagent 邮件用的像素变形 GIF。

运行：python tools/make_morph_gif.py
改下面两个常量就能调整流畅度与循环时长；输出会同步到三处：
  - static/            （邮件 cid 内联用的那份）
  - public/assets/     （开源仓库素材）
  - 主项目 assets/     （本地素材）
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---- 可调参数 ----
FRAME_MS = 50        # 变形阶段每帧毫秒数（20fps）
HOLD_MS = 1500       # logo / 文字各停留 1.5 秒
MORPH_MS = 1200      # 单程变形 1.2 秒
W, H = 320, 96       # 画布
# ------------------

BG = (15, 23, 42)
WHITE = (255, 255, 255)
LOGO_BLUE = (56, 189, 248)
TEXT_BLUE = (96, 165, 250)

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

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
THIS = Path(__file__).resolve()
EXT_STATIC = THIS.parents[1] / "static"           # .../daily-briefing/static
PUBLIC_ROOT = THIS.parents[3]                     # .../public
MAIN_ROOT = THIS.parents[4]                       # .../agentflow

random.seed(42)


def pick_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def logo_points() -> list[tuple[float, float, tuple[int, int, int]]]:
    s = 4
    side = 16 * s
    ox, oy = (W - side) // 2, (H - side) // 2
    points = []
    for y, row in enumerate(PIXELS):
        for x, ch in enumerate(row):
            color = WHITE if ch == "#" else LOGO_BLUE if ch == "p" else None
            if color:
                points.append((ox + x * s + s / 2, oy + y * s + s / 2, color))
    return points


def text_points() -> list[tuple[int, int, tuple[int, int, int]]]:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    font = pick_font(30)
    box = draw.textbbox((0, 0), "PHAiagent", font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text(
        ((W - tw) / 2 - box[0], (H - th) / 2 - box[1]),
        "PHAiagent",
        font=font,
        fill=TEXT_BLUE,
    )
    px = img.load()
    points = []
    for y in range(0, H, 3):
        for x in range(0, W, 3):
            if px[x, y][2] > 120:  # 蓝色笔画，排除深色底
                points.append((x, y, TEXT_BLUE))
    return points


A = logo_points()
B = text_points()
random.shuffle(B)  # 打散映射，避免整体平移
count = max(len(A), len(B))

particles = []
for i in range(count):
    a = A[i % len(A)]
    b = B[i % len(B)]
    particles.append({
        "ax": a[0], "ay": a[1],
        "bx": b[0] + random.uniform(-1.5, 1.5),
        "by": b[1] + random.uniform(-1.5, 1.5),
        "ca": a[2], "cb": b[2],
        "jx": random.uniform(-1, 1), "jy": random.uniform(-1, 1),
    })


def ease(x: float) -> float:
    return 4 * x * x * x if x < 0.5 else 1 - math.pow(-2 * x + 2, 3) / 2


def render(e: float) -> Image.Image:
    """e=0 是 logo，e=1 是文字，中间是打散重组。"""
    chaos = math.sin(math.pi * e) * 11
    frame = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(frame)
    for p in particles:
        x = p["ax"] + (p["bx"] - p["ax"]) * e + p["jx"] * chaos
        y = p["ay"] + (p["by"] - p["ay"]) * e + p["jy"] * chaos
        color = tuple(
            int(p["ca"][j] + (p["cb"][j] - p["ca"][j]) * e) for j in range(3)
        )
        draw.rectangle([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=color)
    return frame


morph_n = max(2, MORPH_MS // FRAME_MS)
frames: list[Image.Image] = []
durations: list[int] = []

# 1) logo 停留 —— 首帧也是不支持动画客户端看到的静态标识
frames.append(render(0.0))
durations.append(HOLD_MS)

# 2) logo → 文字
for k in range(1, morph_n + 1):
    frames.append(render(ease(k / morph_n)))
    durations.append(FRAME_MS)

# 3) 文字停留：把变形终点那一帧直接延长，不额外塞重复帧
durations[-1] = HOLD_MS

# 4) 文字 → logo，终点回到 e=0，循环衔接无缝
for k in range(1, morph_n + 1):
    frames.append(render(ease(1 - k / morph_n)))
    durations.append(FRAME_MS)

total_ms = sum(durations)

# 首帧强制为完整 logo：只显示第一帧的客户端（Outlook 桌面版）也能看到标识
targets = [
    EXT_STATIC / "phaiaagent-morph.gif",
    PUBLIC_ROOT / "assets" / "phaiaagent-morph.gif",
    MAIN_ROOT / "assets" / "phaiaagent-morph.gif",
]
seen: set[Path] = set()
for path in targets:
    resolved = path.resolve()
    if resolved in seen:
        continue
    seen.add(resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"{path} : {path.stat().st_size} bytes")

print(
    f"帧数={len(frames)}  两端停留={HOLD_MS}ms  单程变形={MORPH_MS}ms  "
    f"循环={total_ms / 1000:.2f}s  变形帧率={1000 / FRAME_MS:.0f}fps"
)
print(f"粒子: logo={len(A)} 文字={len(B)} 总={count}")
