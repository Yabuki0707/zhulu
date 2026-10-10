# -*- coding: utf-8 -*-
"""附录C.py —— 从 `附录C-世界地域清单.md` 读出**地理区 → 地域**的对照表。

**为什么单独一个模块**（2026-10-10）：这张表被**三处**要用，而三处原来各写一份或隔着一层：
`tools/build_editor.py`（写进 `基础单元.json` 的 palette）、编辑器侧 `data.js`（`editor_data`）、
以及 `import_editor`（合入时重写 data.js）。表本身只有一个真源（附录C 那个 markdown），
但"读它的代码"以前长在 `build_editor.py` 里 —— 于是**生成器要反过来 import 行政侧的工具**。
搬进生成器之后依赖方向就顺了：行政侧的工具反过来 import 它。
"""
from __future__ import annotations

import os
import re

from mapdata import ROOT

APPENDIX_C = os.path.join(ROOT, "附录C-世界地域清单.md")


def load_palette() -> list[dict]:
    """→ `[{"geo": 地理区, "domains": [地域…]}, …]`（按附录C 里出现的顺序）。

    解析的是那份 markdown 的两个层级：`## C7. 河中（…）` 起一个地理区，
    表格里每行的第一个"…域"是该地理区下的一个地域。附录C 是**设计层**的东西
    （`设计笔记` 那一系），所以这里只读不写；改地域清单要改那份 md，然后重跑
    `build_editor.py --dump-units`（它会带着新 palette 重出 基础单元.json）。
    """
    with open(APPENDIX_C, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, cur = [], None
    for ln in lines:
        m = re.match(r"^##\s*C\d+\.\s*(.+?)（", ln)
        if m:
            cur = {"geo": m.group(1).strip(), "domains": []}
            out.append(cur)
            continue
        m = re.match(r"^\|?\s*([^\s|]+域)\s*\|", ln)
        if m and cur is not None and m.group(1) not in cur["domains"]:
            cur["domains"].append(m.group(1))
    return [g for g in out if g["domains"]]
