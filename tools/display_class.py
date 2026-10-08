# -*- coding: utf-8 -*-
"""显示类（display class）：把「覆盖 × 气候」叠起来看的那些名字。

    from display_class import TABLE, label, entries

**为什么要有这一层**：`docs/adr/0006` 把气候从地形表里摘出去之后，地形只剩 14 类
（水冰 4 ＋ 覆盖 6 ＋ 形态 4），而玩家在图上要看的仍然是雨林／针叶林／沙漠／戈壁／
苔原／稀树草原这些**带气候的名字**。它们**不存储**——存储的是那 14 类加一张气候图，
显示类按 `覆盖 × 热量带 × 干湿` 当场算出来。

好处有两头：

  · **存储少**：原来的针叶林/阔叶林/雨林/沙漠/苔原五类（实测合计 13.26% 像元）不再进
    地形编码，四位的覆盖字段就装得下；
  · **换气候不必重做地形**：柯本换成别的气候数据时，地形一层不动，显示类自动跟着变。

规则表是**有序**的：从上往下第一条命中的生效；字段为 `None` 表示通配。
`entries()` 把这张表交给 `js/data.js`，编辑器据此按每格的 `(覆盖, 热量带, 干湿)`
查名字与配色——所以**配色是数据，不是代码**，改色只需改这里。
"""
from __future__ import annotations

import terrain as TR
import climate as CL

# (覆盖, 热量带, 干湿, 名字, 颜色)
# 覆盖用 terrain 的类码；热量带/干湿用 climate 的码；None = 通配。
# 颜色沿用 v1 那套自然色（雨林 #2f6b3a、阔叶 #6f9c4a、针叶 #4f7a4a、沙漠 #e3cf9a…），
# 这样换成派生显示之后，图**看起来**和 v1 是连续的。
TABLE = [
    # ---- 森林（= 原来的针叶林/阔叶林/雨林/混交，按热量带分开） ----
    (TR.T_FOREST, CL.HEAT_TROP, None, "雨林", "#2f6b3a"),
    (TR.T_FOREST, CL.HEAT_SUBTROP, None, "常绿阔叶林", "#3d7f45"),
    (TR.T_FOREST, CL.HEAT_TEMP, None, "落叶阔叶林", "#6f9c4a"),
    (TR.T_FOREST, CL.HEAT_SUBARC, None, "针叶林", "#4f7a4a"),
    (TR.T_FOREST, None, None, "森林", "#5b8a52"),

    # ---- 草原 ----
    (TR.T_GRASS, None, 0, "苔原", "#b8c4b0"),                    # 干湿 0 = 寒带
    (TR.T_GRASS, CL.HEAT_TROP, 3, "稀树草原", "#c8cc8a"),         # Aw 冬干
    (TR.T_GRASS, None, 1, "荒漠草原", "#c9c091"),                 # 干旱
    (TR.T_GRASS, None, 2, "荒漠草原", "#c9c091"),                 # 半干旱
    (TR.T_GRASS, None, None, "草原", "#b9c68a"),

    # ---- 荒漠（= 原「裸地」的语义 + 干旱区的稀疏植被） ----
    (TR.T_WASTE, None, 1, "沙漠", "#e3cf9a"),                     # 干旱 = 真沙漠
    (TR.T_WASTE, None, 2, "戈壁", "#d6c6a2"),                     # 半干旱 = 砾漠
    (TR.T_WASTE, None, 0, "寒漠", "#cfc7b4"),                     # 寒带
    (TR.T_WASTE, None, None, "荒漠", "#cdbb96"),

    # ---- 沼泽 / 滩涂 / 绿洲 ----
    (TR.T_MARSH, None, 0, "寒沼", "#93a396"),
    (TR.T_MARSH, None, None, "沼泽", "#8fa98a"),
    (TR.T_TIDAL, None, None, "滩涂", "#b0ab94"),
    (TR.T_OASIS, None, None, "绿洲", "#86c06a"),

    # ---- 形态与水冰：气候不参与命名，直接照搬 ----
    (TR.T_PLAIN, None, None, "平原", "#cfe0a8"),
    (TR.T_HILL, None, None, "丘陵", "#c8b98f"),
    (TR.T_PLATEAU, None, None, "高原", "#c2ab7e"),
    (TR.T_MOUNTAIN, None, None, "山地", "#a98a62"),
    (TR.T_OCEAN, None, None, "海洋", "#7fa6c4"),
    (TR.T_LAKE, None, None, "湖泊", "#6ea8d8"),
    (TR.T_RIVER, None, None, "河流", "#5b8fc7"),
    (TR.T_ICE, None, None, "冰川", "#eef4f8"),
]


def label(cover: int, heat: int, moist: int) -> str:
    """一格的显示类名。查不到就退回覆盖自己的名字。"""
    for c, h, m, n, _col in TABLE:
        if c == cover and (h is None or h == heat) and (m is None or m == moist):
            return n
    return TR.LEGEND[cover] if 0 <= cover < TR.N_CLASS else "?"


def entries() -> list:
    """交给 js/data.js 的形状：有序规则表，`None` 通配，编辑器按序首命中。"""
    return [{"cover": c, "heat": h, "moist": m, "n": n, "c": col}
            for c, h, m, n, col in TABLE]


def note() -> str:
    """给台账/日志的一句话说明，免得口径被抄错。"""
    return ("显示类 = 覆盖 × 热量带 × 干湿，**不存储**、由编辑器与规则当场算"
            "（见 docs/adr/0006）；规则表与配色在 tools/display_class.py")
