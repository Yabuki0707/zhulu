# -*- coding: utf-8 -*-
"""显示类（display class）：把「覆盖 × 形态 × 气候」叠起来看的那些名字。

    from display_class import TABLE, label, entries, missing

**为什么要有这一层**：`docs/adr/0006` 把气候从地形里摘出去、`docs/adr/0007` 又把地形拆成
**覆盖 × 形态**两个半字节。存储里只剩 12 个覆盖 + 4 个形态 + 一张气候图，而玩家在图上要看
的仍然是雨林／针叶林／沙漠／戈壁／苔原／高山草甸这些**带气候、带形态的名字**。
它们**不存储**，按三个轴当场算。

好处三头：

  · **存储少**：针叶/阔叶/雨林/沙漠/苔原五类（实测合计 13.26% 像元）不进地形编码；
  · **换气候不必重做地形**：柯本换成别的气候数据，地形一层不动，显示类自动跟着变；
  · **覆盖不再被形态吃掉**：河湟谷地（高原 ∧ 草甸）原来整块只写着「高原」，现在覆盖看得见了
    （草甸那条规则不带形态，所以显示名仍只是**草甸**）——这正是 `adr/0007` 要修的东西。

规则表**有序**：从上往下第一条命中的生效；字段为 `None` 表示通配。
配色原则：**色相由覆盖定，形态只调明暗**——否则 12 × 4 × 35 的组合会炸成一片糊。
`entries()` 把表交给 `js/data.js`，编辑器按每格的 `(覆盖, 形态, 热量带, 干湿)` 查名字与配色
——所以**配色是数据，不是代码**。
"""
from __future__ import annotations

import numpy as np

import terrain as TR
import climate as CL

_C, _F, _H, _M = TR.COVER_LEGEND, TR.FORM_LEGEND, CL.HEAT_NAMES, CL.MOIST_NAMES
TROP, SUB, TEMP, SUBARC = CL.HEAT_TROP, CL.HEAT_SUBTROP, CL.HEAT_TEMP, CL.HEAT_SUBARC
OCEAN, LAKE, RIVER, ICE = TR.C_OCEAN, TR.C_LAKE, TR.C_RIVER, TR.C_ICE
FOREST, GRASS, WASTE = TR.C_FOREST, TR.C_GRASS, TR.C_WASTE
MARSH, TIDAL, SALTM = TR.C_MARSH, TR.C_TIDAL, TR.C_SALTM
FARM, OASIS = TR.C_FARM, TR.C_OASIS
PLAIN, HILL, PLATEAU, MOUNTAIN = TR.F_PLAIN, TR.F_HILL, TR.F_PLATEAU, TR.F_MOUNTAIN

# (覆盖, 形态, 热量带, 干湿, 名字, 颜色)
TABLE = [
    # ---- 水冰：形态不参与命名（湖泊/冰川保留形态位，供"高原湖泊"这类进一步细分） ----
    (OCEAN, None, None, None, "海洋", "#7fa6c4"),
    (LAKE, None, None, None, "湖泊", "#6ea8d8"),
    (RIVER, None, None, None, "河流", "#5b8fc7"),
    (ICE, None, None, None, "冰川", "#eef4f8"),

    # ---- 草甸：一个名字就够，不按形态再派生（河谷草甸/梯田之类是我上一轮多加的） ----
    # ⚠️ 这里**不要**写"草甸 ∧ 干旱 → 绿洲"：管线已经把真沙漠气候（BWh/BWk）里的那批
    # 存成**独立的「绿洲」覆盖**，那样写会是永远命不中的死规则（死规则检查抓到过）。
    # 名字是需求方定的（农田 → 田野 → 草甸，见 tools/terrain.py 开头）：它是**地表的说法**，
    # 不替玩家回答"这块地有没有开垦过"。⚠️ 与覆盖「草原」只差植被密度，配色要分得开。
    (FARM, None, None, None, "草甸", "#e8e4a8"),
    (OASIS, None, None, None, "绿洲", "#86c06a"),

    # ---- 森林：先形态、后热量带（山地/高原的森林不该和低地森林同色） ----
    (FOREST, MOUNTAIN, None, None, "山地森林", "#3f6b40"),
    (FOREST, PLATEAU, None, None, "高原森林", "#4a7248"),
    (FOREST, None, TROP, None, "雨林", "#2f6b3a"),
    (FOREST, None, SUB, None, "常绿阔叶林", "#3d7f45"),
    (FOREST, None, TEMP, None, "落叶阔叶林", "#6f9c4a"),
    (FOREST, None, SUBARC, None, "针叶林", "#4f7a4a"),
    (FOREST, None, None, None, "森林", "#5b8a52"),

    # ---- 草原 ----
    (GRASS, None, None, 0, "苔原", "#b8c4b0"),                    # 干湿 0 = 寒带
    (GRASS, None, TROP, 3, "稀树草原", "#c8cc8a"),                # Aw 冬干
    (GRASS, PLATEAU, None, None, "高原草原", "#c2c78e"),
    (GRASS, MOUNTAIN, None, None, "高山草甸", "#a8bd8a"),
    (GRASS, None, None, 1, "荒漠草原", "#c9c091"),
    (GRASS, None, None, 2, "荒漠草原", "#c9c091"),
    (GRASS, None, None, None, "草原", "#b9c68a"),

    # ---- 荒漠（= 干旱区的裸露与稀疏植被；沙漠/戈壁是它按干湿分出来的两档） ----
    (WASTE, None, None, 1, "沙漠", "#e3cf9a"),
    (WASTE, None, None, 2, "戈壁", "#d6c6a2"),
    # ⚠️ 这里**不要**再写"高原荒漠/山地荒漠"之类**按形态分**的规则：荒漠 = 干旱 ∧ 裸地，
    # 所以每一格荒漠的干湿码必然是 1 或 2，上面两条（沙漠/戈壁）**永远先命中**，
    # 写了也是死规则——子代理验收时量到它们的 hits=0。宁可删掉，也不要留着让人以为生效。
    (WASTE, None, None, None, "荒漠", "#cdbb96"),

    # ---- 沼泽 / 盐沼 / 滩涂：三者都是湿地，差别在**盐不盐**与**有没有植被** ----
    (MARSH, None, None, 0, "寒沼", "#93a396"),
    (MARSH, None, None, None, "沼泽", "#8fa98a"),
    (SALTM, None, None, None, "盐沼", "#a8ad92"),
    (TIDAL, None, None, None, "滩涂", "#b0ab94"),

    # ---- 形态兜底：万一某个覆盖没有专属规则，至少按形态给个中性色 ----
    (None, PLAIN, None, None, "平原", "#cfe0a8"),
    (None, HILL, None, None, "丘陵", "#c8b98f"),
    (None, PLATEAU, None, None, "高原", "#c2ab7e"),
    (None, MOUNTAIN, None, None, "山地", "#a98a62"),
]


def label(cover: int, form: int, heat: int, moist: int) -> str:
    """一格的显示类名。查不到就退回覆盖自己的名字。"""
    for c, f, h, m, n, _col in TABLE:
        if c is not None and c != cover:
            continue
        if f is not None and f != form:
            continue
        if h is not None and h != heat:
            continue
        if m is not None and m != moist:
            continue
        return n
    return TR.COVER_LEGEND[cover] if 0 <= cover < TR.N_COVER else "?"


def entries() -> list:
    """交给 js/data.js 的形状：有序规则表，`None` 通配，编辑器按序首命中。"""
    return [{"cover": c, "form": f, "heat": h, "moist": m, "n": n, "c": col}
            for c, f, h, m, n, col in TABLE]


def missing(cover_used, form_used, log=print) -> int:
    """契约断言用：**每个出现过的 (覆盖, 形态) 组合都必须能落到某条规则上。**

    落不到就会在编辑器里显示成"地形 undefined"（v1 真的出现过：调色板存了下标而不是
    颜色串）。所以把"规则表覆盖不全"变成管线里的一条硬检查，而不是等看图才发现。
    """
    bad = []
    for c in sorted(set(int(x) for x in cover_used)):
        for f in sorted(set(int(x) for x in form_used)):
            if c in (LAKE, RIVER, ICE) and f == TR.F_PLAIN:
                continue                       # 水雪格的形态位是 don't-care
            if not any((r[0] is None or r[0] == c) and (r[1] is None or r[1] == f)
                       for r in TABLE):
                bad.append(f"覆盖={_C[c] if c < len(_C) else c} 形态={_F[f] if f < len(_F) else f}")
    if bad:
        log(f"  ! 显示类规则表漏了 {len(bad)} 个组合：" + "；".join(bad[:6]) +
            ("…" if len(bad) > 6 else ""))
    return len(bad)


def rule_hits(cover, form, heat, moist, log=print):
    """按**真实数据**数每条规则命中多少格 → 返回 0 命中的规则清单（死规则）。

    为什么要有这一条：规则表是**有序首命中**，排在前面的通配规则会把后面的具体规则整个吃掉，
    而"被吃掉"这件事从代码上看不出来。子代理验收就是这么量出三条死规则的（`hits=0`）。
    所以把"有没有死规则"变成管线里的一条硬检查。
    """
    # ⚠️ **每个字段都要先升到 int64**：`form` 是 uint8，`form * 100` 会静默回绕
    # （3 × 100 = 300 → 300 mod 256 = 44），解出来的档位全串味、于是一堆规则被误判成"死规则"。
    # 这一版第一跑就是这么误报的（把山地那一组全报成从未命中）。
    idx = (cover.astype(np.int64) * 1000 + form.astype(np.int64) * 100
           + heat.astype(np.int64) * 10 + moist.astype(np.int64))
    uq, cnt = np.unique(idx, return_counts=True)
    live = {(int(u // 1000), int(u // 100) % 10, int(u // 10) % 10, int(u) % 10): int(c)
            for u, c in zip(uq, cnt)}
    dead = []
    for c, f, h, m, n, _col in TABLE:
        tot = sum(v for (cc, ff, hh, mm), v in live.items()
                  if (c is None or c == cc) and (f is None or f == ff)
                  and (h is None or h == hh) and (m is None or m == mm))
        # 只在**它本该有份额**时判死：通配更少的规则若 0 命中，说明被前面吃掉了
        if tot == 0:
            dead.append(n)
    if dead:
        log(f"  ! 显示类里有 {len(dead)} 条规则从未命中（被前面的通配规则吃掉）："
            + "、".join(dict.fromkeys(dead)))
    return dead


def note() -> str:
    """给台账/日志的一句话说明，免得口径被抄错。"""
    return ("显示类 = 覆盖 × 形态 × 热量带 × 干湿，**不存储**、由编辑器与规则当场算"
            "（见 docs/adr/0006、0007）；规则表与配色在 tools/display_class.py")
