"""把 README 渲染成 GitHub 风格 HTML，方便本地预览排版。

运行：python tools/preview_readme.py
产物：_readme_preview.html（已被 .gitignore 忽略）
"""
from __future__ import annotations

import re
from pathlib import Path

EXT = Path(__file__).resolve().parents[1]
md = (EXT / "README.md").read_text(encoding="utf-8")


def inline(s: str) -> str:
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


lines = md.split("\n")
blocks: list[str] = []
i, n = 0, len(md.split("\n"))

while i < n:
    line = lines[i]

    if line.startswith("<"):                       # HTML 块原样保留
        buf = []
        while i < n and (lines[i].startswith("<") or lines[i].strip()):
            buf.append(lines[i])
            i += 1
        blocks.append("\n".join(buf))
        continue

    if line.startswith("```"):                     # 代码块
        i += 1
        buf = []
        while i < n and not lines[i].startswith("```"):
            buf.append(lines[i])
            i += 1
        i += 1
        blocks.append(
            "<pre><code>" + "\n".join(buf).replace("<", "&lt;") + "</code></pre>"
        )
        continue

    if line.startswith("|"):                       # 表格
        buf = []
        while i < n and lines[i].startswith("|"):
            buf.append(lines[i])
            i += 1
        rows = [
            [c.strip() for c in r.strip().strip("|").split("|")]
            for r in buf
            if not re.match(r"^\|[\s:\-|]+\|$", r)
        ]
        html = ["<table>"]
        for idx, row in enumerate(rows):
            tag = "th" if idx == 0 else "td"
            html.append(
                "<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in row) + "</tr>"
            )
        html.append("</table>")
        blocks.append("".join(html))
        continue

    if line.startswith("# "):
        blocks.append(f"<h1>{inline(line[2:])}</h1>")
        i += 1
        continue
    if line.startswith("## "):
        blocks.append(f"<h2>{inline(line[3:])}</h2>")
        i += 1
        continue
    if line.strip() == "---":
        blocks.append("<hr>")
        i += 1
        continue
    if line.startswith("> "):
        blocks.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        i += 1
        continue
    if re.match(r"^[-*] ", line):
        buf = []
        while i < n and re.match(r"^[-*] ", lines[i]):
            buf.append(f"<li>{inline(lines[i][2:])}</li>")
            i += 1
        blocks.append("<ul>" + "".join(buf) + "</ul>")
        continue
    if not line.strip():
        i += 1
        continue

    blocks.append(f"<p>{inline(line)}</p>")
    i += 1

CSS = """
body{max-width:980px;margin:0 auto;padding:36px 24px 80px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;font-size:16px;line-height:1.65;color:#1f2328;background:#fff}
h1,h2{border-bottom:1px solid #d1d9e0;padding-bottom:.3em;font-weight:600}
h1{font-size:2em;margin:.4em 0 .6em}
h2{font-size:1.5em;margin:34px 0 16px}
p{margin:12px 0}
a{color:#0969da;text-decoration:none}
a:hover{text-decoration:underline}
img{max-width:100%}
table{border-collapse:collapse;margin:14px 0;display:block;overflow:auto}
th,td{border:1px solid #d1d9e0;padding:6px 13px;text-align:left}
th{background:#f6f8fa;font-weight:600}
tr:nth-child(2n) td{background:#f6f8fa}
code{background:rgba(175,184,193,.2);padding:.2em .4em;border-radius:6px;font-size:85%;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
pre{background:#f6f8fa;padding:16px;border-radius:8px;overflow:auto;margin:14px 0}
pre code{background:none;padding:0;font-size:85%}
blockquote{margin:12px 0;padding:0 1em;color:#59636e;border-left:.25em solid #d1d9e0}
ul{margin:12px 0;padding-left:26px}
hr{height:.25em;border:0;background:#d1d9e0;margin:26px 0}
sub{color:#59636e;font-size:80%}
"""

html = (
    '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    f"<title>PHAiagent README 预览</title><style>{CSS}</style></head><body>\n"
    + "\n".join(blocks)
    + "\n</body></html>"
)

out = EXT / "_readme_preview.html"
out.write_text(html, encoding="utf-8")
print(f"预览已生成: {out}")
print(f"块数: {len(blocks)}")
print("打开方式：在该目录起一个静态服务，或直接浏览器打开该文件")
