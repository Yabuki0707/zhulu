# -*- coding: utf-8 -*-
"""底图指纹 `base_tag` —— `生成.py` 与 `import_editor.py` 的**共用**实现。

为什么必须共用（工单 §3.3）：这张指纹是"本地增量存档还作不作数"的判据，也是
`import_editor.py` 拒绝旧草稿的依据（草稿的 `based_on` 必须等于真源当前指纹）。
两处各写一份，一旦有一处改了拼接方式，指纹就对不上——而它对不上的表现是
"存档悄悄失效"或"草稿被误判为基于旧底图"，都不报错。

公式：

    name_tag   = "zh" + sha1(地块名按 id 升序以 "|" 连接)[:6]
    legend_tag = "t"  + sha1(LEGEND 以 "|" 连接)[:4]      # v3 起 LEGEND = 覆盖名 + 形态名
    base_tag   = f"{cell}-{W}x{H}-{地块数}-{有像元的地块覆盖的格数}-{name_tag}-{legend_tag}"

- `地块数` 取**台账里的地块数**，不是种子数：编辑器会新建地块，数量不再等于种子数。
- `name_tag` 里带地块名，所以换一批中文名就会让旧存档自动作废。
"""
from __future__ import annotations

import hashlib


def name_tag(plot_names) -> str:
    h = hashlib.sha1("|".join(plot_names).encode("utf-8")).hexdigest()
    return "zh" + h[:6]


def legend_tag(legend) -> str:
    h = hashlib.sha1("|".join(legend).encode("utf-8")).hexdigest()
    return "t" + h[:4]


def base_tag(cell, w: int, h: int, n_plots: int, covered: int, plot_names, legend) -> str:
    return (f"{cell}-{w}x{h}-{n_plots}-{covered}"
            f"-{name_tag(plot_names)}-{legend_tag(legend)}")
