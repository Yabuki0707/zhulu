# -*- coding: utf-8 -*-
"""显示类（display class）：**地形 = 覆盖 × 形态 × 气候 的组合**，一个组合一个名字。

    from display_class import label, payload, check_palette, usage

**这一层是"地形"这个概念本身**（2026-10-09 统一口径）。`docs/adr/0006` 把气候从地形里摘出去、
`docs/adr/0007` 又把地形拆成**覆盖 × 形态**两个半字节之后，存储里只剩 12 个覆盖 + 4 个形态
+ 一张气候图，而玩家在图上要看、在门口拦路时要判的仍然是**雨林／针叶林／沙漠／戈壁／
苔原／高山草原**这些名字。**名字不存储**：三轴一合，当场算出来。

    地形 = 覆盖 × 形态 × 气候 = 显示类        ← 三者是同一个东西的三种说法

## 「苔原」只有一个来源（`adr/0011`）

**覆盖 = 苔原**（LC100 100 苔藓/地衣，实测约 1.2 万格）。**仅此一支。**
v6 及之前还有第二支 `草原 ∧ 干湿 0 → 苔原`，两个后果都不对：①青藏高原/羌塘/帕米尔（柯本 ET，
实测 4.5 万格）被叫成苔原 —— 按中国地理那批是**高寒草原**；②一个名字两个来源（违反"一名一源"）。
现在 ET 气候上的草地按形态读作 **寒地草原／高寒草原／高山苔原**。

## 名字是**全函数**，没有兜底分支

v1 的规则表是"有序首命中 + 末尾几条形态兜底"，于是两条路都会漏：

  · **没命中的组合**落回「覆盖 · 形态」这种拼凑名（真出现过 `地形 undefined`）；
  · **被前面通配规则吃掉的规则**永远不生效（子代理验收量到三条 hits=0 的死规则）。

现在改成**按轴组合**：每个覆盖有一张自己的**轴向词表**（形态前缀 / 热量带 / 干湿），
`label()` 对**任何** `(覆盖, 形态, 热量带, 干湿)` 都给出名字——包括气候上不可能出现、
但万一数据变了就会冒出来的组合（如 `(冰川, 平原, 热带, 夏雨)` 照样给名字）。所以：

  · 管线里不再需要"规则表漏了哪个组合"这条检查（**漏不了**）；
  · 也不必再猜"某条规则是不是死的"——**没有规则**，只有词表。
  · 编辑器不扫规则表找下标，直接查 `display_lut`（见下），940 万格的统计循环因此由
    O(格数 × 规则条数) 降到 O(格数) 的一次数组读。

## 契约：`display_classes` + `display_lut`

    display_classes[i] = {"n": 名字, "c": 颜色}          // 81 类，**只此一处**定名字与配色
    display_lut[((覆盖×4 + 形态)×32) + 码] = 类下标       // 2048 项（16 覆盖 × 4 形态 × 32 码），全覆盖

「码」是气候码（热量带 × 8 + 干湿，0..31）；**干湿为 0 时整条码归零**（那 2 位是
don't-care，见 `climate.py`：先读干湿）。两个写入方（`生成.py` / `import_editor`）
都只调 `payload()`，不许各自拼这两个键——旧账里 base_tag 就是这么分叉的。

## 配色：族内色相微调 + 明暗浓淡

**色相由覆盖族定**（水=蓝、森林=绿、草原=黄绿、草甸=暖黄、荒漠=土黄、沼泽=青灰…），
族内靠**色相微调 + 明度/饱和**拉开。`check_palette()` 用 CIE Lab 的 ΔE 量**任意两类
的最小色差**，并把它做成管线的硬检查——"每个显示类都有独特色"不能只靠肉眼。
（旧表 24 类里有好几对 ΔE < 8，缩到全图就分不出来。）
"""
from __future__ import annotations

import itertools
import json
import math

import numpy as np

import terrain as TR
import climate as CL

_C, _F, _H, _M = TR.COVER_LEGEND, TR.FORM_LEGEND, CL.HEAT_NAMES, CL.MOIST_NAMES
TROP, SUB, TEMP, SUBARC = CL.HEAT_TROP, CL.HEAT_SUBTROP, CL.HEAT_TEMP, CL.HEAT_SUBARC
OCEAN, LAKE, RIVER, ICE = TR.C_OCEAN, TR.C_LAKE, TR.C_RIVER, TR.C_ICE
MARSH, TIDAL, SALTM = TR.C_MARSH, TR.C_TIDAL, TR.C_SALTM
FARM, OASIS, TUNDRA, GRASS = TR.C_FARM, TR.C_OASIS, TR.C_TUNDRA, TR.C_GRASS
DENSE, OPENF, SHRUB, SAND, GRAVEL = TR.C_DENSE, TR.C_OPEN, TR.C_SHRUB, TR.C_SAND, TR.C_GRAVEL
SEAICE, SALTLAKE, SALTPAN, VOLCANO = TR.C_SEAICE, TR.C_SALTLAKE, TR.C_SALTPAN, TR.C_VOLCANO
PLAIN, HILL, PLATEAU, MOUNTAIN = TR.F_PLAIN, TR.F_HILL, TR.F_PLATEAU, TR.F_MOUNTAIN

# ================================================================ 命名：一份轴向词表
# 每个覆盖一张词表；`label()` 只做"按轴向取词 + 拼"，没有任何"命中/未命中"。
_HEAT_PRE = {TROP: "热带", SUB: "亚热带", TEMP: "温带", SUBARC: "亚寒带"}
# ⚠️ **没有叶型表**：针叶／阔叶／雨林那套词已删除（2026-10-09）—— 叶型在本设计里是热量带的
# 函数，与热量带写在一起就是同一件事写两遍。林名 = [形态前缀?] + 热量带 + 密/疏林。
# 草原的三档（干旱 → 荒漠草原、半干旱 → 典型草原、其余 → 第三档）**写在 `label()` 里**，
# 因为第三档的词**要按热量带换**：温带是「草甸草原」（黑土草原，确实是它），亚热带必须换
# （"草甸草原"是温带概念，`adr/0011`）。三档本身是柯本季节型的粗分，不是年降水量的量化——
# 柯本的第三个字母只分 s/w/f。
# 草甸（覆盖，LC100 耕地/建成区）：形态优先，其次热量带。⚠️ 与草原的「草甸草原」差一个"草原"，
# 两者是不同的东西（前者是覆盖、是地表，后者是覆盖草原的一档气候）。
_FARM_BY_HEAT = {TROP: "热带草甸", SUB: "亚热带草甸", TEMP: "温带草甸", SUBARC: "温带草甸"}


def label(cover: int, form: int, heat: int, moist: int) -> str:
    """一格的显示类名。**全函数**：任何组合都有名字，不存在"未匹配"。

    ⚠️ `moist == 0` 是「寒带」——热量带那 2 位是 don't-care（`climate.py`：先读干湿），
    所以那一支只按干湿判、**不许读 heat**（读了会把同一格按 4 个热量带散成 4 个名字）。

    ⚠️ **一根轴只说自己的话**（`docs/地形覆盖判定规格.md` §0）：名字里的叶型（雨林/常绿/
    落叶/针叶）与裸地的干湿档（沙漠/戈壁/寒漠）是**气候**说的；密/疏、草/灌/水是**覆盖**
    说的；高原/山地是**形态**说的。不越界 —— 拿气候猜"树密不密"正是 v5 之前的真错。
    """
    cover, form = int(cover), int(form)
    heat, moist = int(heat), int(moist)
    if cover == OCEAN:
        return "海洋"
    if cover == LAKE:
        # v9 起叫「淡湖」——有了「咸湖」就得有它的对应词（需求方定）。
        return "高原淡湖" if form in (PLATEAU, MOUNTAIN) else "淡湖"
    if cover == SALTLAKE:
        # **咸湖**（v9）：GLWD-1 的 `MGLD_TYPE = closed/closedx`（**内流闭合盆地**，盐分只积不排）。
        # 实测 12/13 对：里海/咸海/青海湖/乌布苏/呼伦湖/死海＝闭合（真是咸）、贝加尔/斋桑＝开放（真是淡）。
        return "高原咸湖" if form in (PLATEAU, MOUNTAIN) else "咸湖"
    if cover == RIVER:
        return {PLATEAU: "高原河流", MOUNTAIN: "山地河流"}.get(form, "河流")
    if cover == ICE:
        return {MOUNTAIN: "山地冰川", PLATEAU: "高原冰川"}.get(form, "冰川")
    if cover == SEAICE:
        # **海冰**（v9，`adr/0014`）：数据自带判据 —— NSIDC 的 30 个 3 月范围面里，
        # ≥50% 的年份把这一格盖住。恒名，不分形态（冰面没有"高原/山地"可言）。
        return "海冰"
    # ---- 森林：**林名 = [形态前缀?] + 热量带 + 密/疏林** ----
    # 刻意**不写叶型**（针叶／阔叶／雨林）：叶型在本设计里就是热量带的函数（热带→雨林、
    # 亚热带→常绿阔叶、温带→落叶阔叶、亚寒带→针叶），写它等于同一件事写两遍。
    # 热量带负责冷暖、密疏负责郁闭度 —— 两者各说各的，**没有冗余、也没有例外**。
    if cover in (DENSE, OPENF):
        pre = "高原" if form == PLATEAU else ("山地" if form == MOUNTAIN else "")
        # 干湿 0（寒带）那 2 位是 don't-care，热量带按亚寒带算
        hw = "亚寒带" if not moist else _HEAT_PRE.get(heat, "温带")
        return pre + hw + ("密林" if cover == DENSE else "疏林")
    if cover == SHRUB:
        # **真沙漠气候（干湿 = 1，BWh/BWk）里的灌丛读作「沙漠」** —— 这是 v5 定下的判据：
        # *连灌木都稀、气候又是真沙漠的地方才算沙漠*（半干旱区 BSh/BSk 有草有灌木的仍是灌丛/草原）。
        # v6 把灌丛独立成覆盖类时这条**一度掉了**（那 4.7 万格又读回「热带灌丛」），这里补回来。
        # ⚠️ 「沙漠」因此有**两个来源**（裸地 ∧ 干湿 1、灌丛 ∧ 干湿 1），是**声明合并**。
        if moist == 1:
            # ⚠️ 名字必须与**裸地 ∧ 真沙漠**区分开——v6 时两个覆盖都叫「沙漠」，
            # 那是"一个显示名两个来源"，`adr/0011` 拆掉：灌丛那支叫**沙漠灌丛**。
            pre = "高原" if form == PLATEAU else ("山地" if form == MOUNTAIN else "")
            return pre + "沙漠灌丛"
        if form in (PLATEAU, MOUNTAIN):
            return ("高原" if form == PLATEAU else "山地") + "灌丛"
        return (_HEAT_PRE.get(heat, "温带") + "灌丛") if moist else "亚寒带灌丛"
    if cover == GRASS:
        if form == PLATEAU:
            return "高原草原"
        if form == MOUNTAIN:
            return "高山草原"
        # ⚠️ **不要给"气候极冷的草地"单独一个名字**（`adr/0011`）。v6.1 之前那条
        #    `草原 ∧ 干湿 0 → 苔原/高寒草原/高山苔原` 已**整条删除**，理由有两条：
        #    ①按总则，气候管冷暖、不该给地表起名——它已经惹过一次祸（青藏高原被它弄成苔原）；
        #    ②那三个名字里「高山苔原」带"苔原"二字，与**覆盖 = 苔原**（LC100 苔藓/地衣）
        #      撞脸，看了让人以为是同一回事。现在「苔原」在整个图例里**只有一个来源**。
        # 干湿 0（柯本 ET/EF）时热量带那 2 位是 don't-care，按亚寒带算。
        h = SUBARC if not moist else heat
        if h == SUBARC:
            return "亚寒带草原"
        if h == TROP:
            return {1: "热带荒漠草原", 2: "热带干草原", 3: "热带稀树草原"}.get(moist, "热带草原")
        unit = _HEAT_PRE.get(h, "温带")
        if moist == 1:
            return unit + "荒漠草原"
        if moist == 2:
            return unit + "典型草原"
        # 第三档的词按热量带换：温带是「草甸草原」（黑土草原，确实是它）；
        # **亚热带不能用"草甸草原"**——那是温带概念（`adr/0011`）。
        return unit + ("草丛" if h == SUB else "草甸草原")
    if cover == FARM:
        if form == MOUNTAIN:
            return "山地草甸"
        if form == PLATEAU:
            return "高原草甸"
        return "温带草甸" if not moist else _FARM_BY_HEAT.get(heat, "温带草甸")
    if cover == MARSH:
        return "寒沼" if not moist else "沼泽"
    if cover == TUNDRA:
        # 覆盖「苔原」= LC100 苔藓/地衣。**恒名**，不按形态/热量带分：苔原带的地表就是苔原。
        # ⚠️ **这个名字只归这一支**（`adr/0011` 一名一源）——`草原 ∧ 干湿 0` 那支已删，
        # 改读 寒地草原／高寒草原／高山苔原。
        return "苔原"
    if cover == SALTM:
        return "盐沼"
    if cover == TIDAL:
        return "滩涂"
    if cover in (SAND, GRAVEL):
        # **沙质裸地 / 砾质裸地**（v7，`adr/0012`）。三根轴各说各的：
        #   · **材质**（沙／砾）来自**覆盖** —— 由 GSDP30 的「有沙占比」定（`地图/栅格地形数据生成器/sanddunes.py`）；
        #   · **冷暖**（热带／亚热带／温带）来自**气候**；
        #   · **平陡**（高原／山地）来自**形态**。
        # v6 及之前「沙漠／戈壁」这两个词是由**干湿**定的（干旱→沙漠、半干旱→戈壁）—— 那是
        # 拿气候猜材质，实测两头都反：**塔克拉玛干与蒙古戈壁在柯本分类里同属 BWk**，于是
        # 沙海被叫成"戈壁"、真正的砾质戈壁被叫成"沙漠"。沙是与不是沙，只有遥感看得见。
        pre = "高原" if form == PLATEAU else ("山地" if form == MOUNTAIN else "")
        desert = "沙漠" if cover == SAND else "戈壁"
        if pre:
            return pre + desert                       # 海拔上不再分热量带（与森林同理）
        if moist == 0:
            # 寒带（柯本 ET/EF）：热量带那 2 位是 don't-care。砾质用「寒漠」—— 极地/极高山的
            # 裸岩就叫这个，**只有砾质裸地才有**这个名字（南极干谷、羌塘的裸岩都不长沙）。
            # 沙质在寒带没有定名的词，按森林那条老规矩一律算亚寒带。
            return "寒漠" if cover == GRAVEL else "亚寒带沙漠"
        if moist >= 3:
            # **湿润区里光秃秃的地面不是荒漠**（高山碎石坡、河滩砾石、沙洲），不借沙漠/戈壁的词，
            # 直接读覆盖名。这类合计约 7 千格，主要在天山、帕米尔、青藏与几条大河滩。
            return _C[cover]
        return _HEAT_PRE.get(heat, "温带") + desert
    if cover == SALTPAN:
        # **盐漠**（v9）：GLWD-3 的「Pan, brackish/saline wetland（盐盘／咸水湿地）」。
        # 与沙漠/戈壁同族（都是无植被地表），所以也带形态前缀。
        pre = "高原" if form == PLATEAU else ("山地" if form == MOUNTAIN else "")
        return pre + "盐漠"
    if cover == VOLCANO:
        # **火山**（v9）：GVP 全新世火山**点**，一座一格，恒名。⚠️ 是点不是面 ——
        # 成片的熔岩台地要岩性数据，见 `adr/0014` 的"明确不做"。
        return "火山"
    if cover == OASIS:
        return "绿洲"
    return _C[cover] if 0 <= cover < TR.N_COVER else f"覆盖 {cover}"


# ================================================================ 配色
PALETTE_MIN_DE = 9.0     # 任意两类的最小 CIE Lab 色差，`check_palette()` 守着它
# **族内色相微调 + 明暗浓淡**：色相由覆盖族定，族内靠色相偏移与明度/饱和拉开。
# 这张表不是拍脑袋凑的，也不是手调出来的 —— 先在 Lab 空间按语义锚点（下方注释里的 HSL）
# 做一次带锚点回拉的排斥，直到任意两类 ΔE ≥ 9，再量化到 8 位并修掉取整造成的破绽。
# 最终**锚点位移中位 0.3、最大 4.6**：色相语义（森林绿、荒漠土黄、水蓝…）没有跑掉。
# 调色脚本是一次性的，见 git 历史里的 `tools/_tmp_palette.py`（已删）——要改配色，
# 改这张表并重跑 `python 地图/栅格地形数据生成器/display_class.py` 看 ΔE 报告，别凭眼睛。
#   语义锚点（HSL，色相/饱和/明度），改色的意图写在这里：
#     水 199–235 蓝 ｜ 冰 近白→灰蓝 ｜ 森林 78–188 绿 ｜ 草原 38–92（色相=热量带、明度=干湿）
#     草甸 42–58 暖黄浅 ｜ 荒漠 20–44 土黄 ｜ 沼泽 170 青灰 ｜ 盐沼 104 ｜ 滩涂 20 ｜ 绿洲 132
PAINT: dict[str, str] = {
    "海洋": "#799dba",
    "淡湖": "#85c4de",
    "高原淡湖": "#6c92c6",
    "河流": "#306acf",
    "高原河流": "#334b99",
    "山地河流": "#313668",
    "冰川": "#f9feff",
    "高原冰川": "#d7dfe6",
    "山地冰川": "#a9b4c3",
    "亚寒带密林": "#18471b",
    "热带密林": "#00573b",
    "亚热带密林": "#277641",
    "温带密林": "#4a8a35",
    "高原亚寒带密林": "#243e21",
    "高原热带密林": "#204f3d",
    "高原亚热带密林": "#2f6e49",
    "高原温带密林": "#4e803c",
    "山地亚寒带密林": "#223b31",
    "山地热带密林": "#1f5150",
    "山地亚热带密林": "#00655b",
    "山地温带密林": "#496e3a",
    "亚寒带疏林": "#3c5731",
    "热带疏林": "#409571",
    "亚热带疏林": "#69a773",
    "温带疏林": "#94bd77",
    "高原亚寒带疏林": "#4b6d50",
    "高原热带疏林": "#357c67",
    "高原亚热带疏林": "#578764",
    "高原温带疏林": "#799e57",
    "山地亚寒带疏林": "#466356",
    "山地热带疏林": "#3b7a7a",
    "山地亚热带疏林": "#5b9984",
    "山地温带疏林": "#618c58",
    "亚寒带灌丛": "#6f805f",
    "沙漠灌丛": "#afa56c",
    "热带灌丛": "#8f9a49",
    "亚热带灌丛": "#7d8e5c",
    "温带灌丛": "#9aaa6c",
    "高原灌丛": "#969871",
    "高原沙漠灌丛": "#988756",
    "山地灌丛": "#5f693d",
    "山地沙漠灌丛": "#7a6f4b",
    "亚寒带草原": "#73ac3c",
    "热带荒漠草原": "#dfbca9",
    "热带干草原": "#c19f70",
    "热带稀树草原": "#aa813b",
    "热带草原": "#bac882",
    "亚热带荒漠草原": "#cdca9d",
    "亚热带典型草原": "#b9b562",
    "亚热带草丛": "#aaa23c",
    "温带荒漠草原": "#cadfab",
    "温带典型草原": "#a5bc63",
    "温带草甸草原": "#90aa3c",
    "高原草原": "#828443",
    "高山草原": "#5b593e",
    "温带草甸": "#eedfbe",
    "热带草甸": "#dbc06d",
    "亚热带草甸": "#eddea2",
    "高原草甸": "#dad586",
    "山地草甸": "#a7974a",
    "寒沼": "#aacac8",
    "沼泽": "#699a96",
    "苔原": "#cad7c6",
    "盐沼": "#94ac91",
    "滩涂": "#c3a7a1",
    "亚寒带沙漠": "#b4a182",
    "热带沙漠": "#e1ad54",
    "沙质裸地": "#d8bb93",
    "亚热带沙漠": "#e0bb7f",
    "温带沙漠": "#c69e5a",
    "高原沙漠": "#bc9b3e",
    "山地沙漠": "#916f3b",
    "寒漠": "#a49e91",
    "热带戈壁": "#b48558",
    "砾质裸地": "#b7b8b4",
    "亚热带戈壁": "#bc9077",
    "温带戈壁": "#9a7a5a",
    "亚寒带戈壁": "#958271",
    "高原戈壁": "#88624d",
    "山地戈壁": "#674f3e",
    "绿洲": "#3da451",
    "海冰": "#b0d9ea",
    "咸湖": "#4691b4",
    "高原咸湖": "#3c7597",
    "盐漠": "#dfcec9",
    "高原盐漠": "#babba1",
    "山地盐漠": "#858e7a",
    "火山": "#5a4846",
}


# ================================================================ 组合 → 类
# 组合总数 = 覆盖 × 形态 × 气候码。**由三张轴的长度推出来，不写死**：覆盖 12 → 13（v5 加苔原）时
# 它会自己一路涨到 2048（v7 覆盖 16 值）；写死的话 LUT 会短一截，编辑器查到越界下标（那一格成灰点，
# 而 944 万格里看不出是哪一格）。
N_COMBO = TR.N_COVER * TR.N_FORM * (CL.N_HEAT * CL.N_MOIST)     # = 16 × 4 × 32 = 2048


def combo_key(cover: int, form: int, heat: int, moist: int) -> int:
    """组合 → 0..1535 的下标：`((覆盖×4 + 形态) × 32) + 码`，码 = 热量带 × 8 + 干湿。

    **干湿为 0 时整条码归零**——那 2 位是 don't-care（`climate.py`：先读干湿），
    不归零的话同一种地表会按 4 个热量带散成四个下标，`lut` 也就装不下这个"同"字。
    """
    code = 0 if int(moist) == 0 else (int(heat) * CL.N_MOIST + int(moist))
    return ((int(cover) * 4 + int(form)) * 32) + code


def _order() -> list[tuple[int, int, int, int]]:
    """枚举**全部**组合（不是只枚举出现过的）：名字是全函数，LUT 就必须是全覆盖的 ——
    否则数据一变（多一格极端气候）编辑器就查到一个不存在的下标。"""
    return [(c, f, h, m) for c in range(TR.N_COVER) for f in range(TR.N_FORM)
            for h in range(CL.N_HEAT) for m in range(CL.N_MOIST)]


_CLASSES: list[dict] | None = None
_LUT: np.ndarray | None = None


def classes() -> list[dict]:
    """全部显示类 `[{"n": 名字, "c": 颜色}]`，按**首次出现的组合顺序**排（稳定、可复现）。

    顺序即下标；`lut` 里的数就是这里的下标。图例只画实际出现过的（0 格的类不出现在面板上）。
    """
    global _CLASSES, _LUT
    if _CLASSES is None:
        names, lut = [], np.zeros(N_COMBO, dtype=np.int32)
        for c, f, h, m in _order():
            n = label(c, f, h, m)
            if n not in names:
                names.append(n)
            lut[combo_key(c, f, h, m)] = names.index(n)
        missing = [n for n in names if n not in PAINT]
        assert not missing, f"配色表缺 {len(missing)} 个显示类：{missing}"
        extra = [n for n in PAINT if n not in names]
        assert not extra, f"配色表多了 {len(extra)} 个用不上的显示类：{extra}"
        _CLASSES = [{"n": n, "c": PAINT[n]} for n in names]
        _LUT = lut
    return _CLASSES


def lut() -> np.ndarray:
    """组合下标 → 类下标（2048 项）。编辑器侧只查这一张表，不扫规则。"""
    classes()
    return _LUT


def index_of(cover: int, form: int, heat: int, moist: int) -> int:
    """组合 → 类下标。给测试与统计用（编辑器走 `lut()`）。"""
    return int(lut()[combo_key(cover, form, heat, moist)])


def payload() -> dict:
    """交给 `js/data.js` 的三个键。**两个写入方都只调它**（写各自的版本必然分叉）。"""
    classes()
    return {"display_classes": _CLASSES, "display_lut": [int(x) for x in _LUT],
            "display_encoding": "显示类下标 = display_lut[((覆盖×4 + 形态)×32) + 码]，"
                                "码 = 热量带×8+干湿（干湿 0 时整条码归零）"}


# ================================================================ 配色检查（CIE Lab ΔE）
def _lab(hex_str: str) -> tuple[float, float, float]:
    """#rrggbb → CIE L*a*b*（D65）。用 sRGB 的标准矩阵，不做色彩管理。"""
    r, g, b = (int(hex_str[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    lin = [(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) for v in (r, g, b)]
    x = lin[0] * 0.4124564 + lin[1] * 0.3575761 + lin[2] * 0.1804375
    y = lin[0] * 0.2126729 + lin[1] * 0.7151522 + lin[2] * 0.0721750
    z = lin[0] * 0.0193339 + lin[1] * 0.1191920 + lin[2] * 0.9503041
    x, y, z = x / 0.95047, y / 1.0, z / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t + 16 / 116)
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a: str, b: str) -> float:
    """CIE76 色差。够用：这里只关心"两块的色相/明度差得开不开"。"""
    la, lb = _lab(a), _lab(b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb)))


def check_palette(target: float = 9.0, only=None, log=print) -> dict:
    """**任意两类的最小 ΔE** —— 这是"每个显示类都有独特色"的硬口径。

    `only` 传类名集合时只量这些类之间（用于"只保证实际出现过的类分得开"）。
    返回 {"min", "pairs", "bad"}；`bad` 是 ΔE < target 的那些对。
    """
    cs = [c for c in classes() if only is None or c["n"] in only]
    worst, pairs = 1e9, []
    for a, b in itertools.combinations(cs, 2):
        d = delta_e(a["c"], b["c"])
        pairs.append((d, a["n"], b["n"]))
        if d < worst:
            worst = d
    pairs.sort()
    bad = [p for p in pairs if p[0] < target]
    if bad:
        log(f"  ! 显示类配色有 {len(bad)} 对 ΔE < {target}（最近的一对 "
            f"{bad[0][1]}／{bad[0][2]} ΔE={bad[0][0]:.1f}）")
    else:
        log(f"  显示类配色 {len(cs)} 类，任意两类最小 ΔE = {worst:.1f} ≥ {target} ✓")
    return {"min": worst, "pairs": pairs[:8], "bad": bad, "n": len(cs)}


def usage(terr, clim, form=None, log=print) -> dict:
    """按**真实栅格**数每个显示类多少格 → (计数, 从没出现过的类)。

    `terr` 是地形字节（**覆盖在高 5 位、形态在低 3 位**，v9 起；见 `terrain.pack/unpack`），
    `clim` 是气候码。给管线日志与 `python 地图/栅格地形数据生成器/display_class.py` 用：好知道 88 个类里哪几个
    真的出现在这张图上。
    ⚠️ 这两个移位量是**契约**（`adr/0014`）：v9 之前是 `>> 4 / & 15`，写成旧的会把每一格
    都解错 —— 而这里**不报错**，只会数出一堆不存在的组合（这张表本来就允许 29 类"从没出现"）。
    """
    terr = np.asarray(terr).astype(np.int64)
    clim = np.asarray(clim).astype(np.int64) & 31
    cov, frm = terr >> 3, terr & 7
    code = np.where((clim & 7) == 0, 0, clim)
    idx = ((cov * 4 + frm) * 32 + code).ravel()
    cnt = np.bincount(lut()[idx], minlength=len(classes()))
    out = {c["n"]: int(cnt[i]) for i, c in enumerate(classes())}
    unused = [n for i, n in enumerate(c["n"] for c in classes()) if cnt[i] == 0]
    if log:
        log(f"  显示类 {len(classes())} 类，出现在这张图上的 {int((cnt > 0).sum())} 类；"
            f"从未出现 {len(unused)} 类（气候上不可能的组合，名字照样全函数）")
    return {"counts": out, "unused": unused}


def verify(log=None) -> tuple[int, float]:
    """管线硬检查用：→ (类数, 任意两类最小 ΔE)。顺带断言 `display_lut` 是**全覆盖**的。

    为什么 LUT 要 N_COMBO 全覆盖：编辑器不扫规则、只查这张表（`((覆盖×4+形态)×32)+码`），
    表短一格或有一个越界下标，那一格在图上就是"查不到"的灰点——而 940 万格里看不出是哪一格。
    """
    l = lut()
    assert l.shape[0] == N_COMBO, f"display_lut 长度 {l.shape[0]} ≠ {N_COMBO}"
    assert int(l.min()) >= 0 and int(l.max()) < len(classes()), "display_lut 里有越界的类下标"
    # **铁律：一个显示名只许有一个来源**（`adr/0011`）。同一个名字由两个覆盖产生 = 让
    # "地表长着什么"那个事实消失（裸地与灌丛都叫"沙漠"时，"这里长着灌木"就没了）。
    src: dict[str, set] = {}
    for c, f, h, m in _order():
        src.setdefault(label(c, f, h, m), set()).add(c)
    dup = {n: s for n, s in src.items() if len(s) > 1}
    assert not dup, ("下列显示名由多个覆盖共用，违反「一名一源」（adr/0011）："
                     + "；".join(f"{n} ← {[_C[c] for c in sorted(s)]}" for n, s in dup.items()))
    rep = check_palette(PALETTE_MIN_DE, log=lambda s: None)
    if log is not None:
        log(f"  显示类 {len(classes())} 类 · LUT {N_COMBO} 组合全覆盖 ✓ · "
            f"一名一源 ✓ · 任意两类最小 ΔE {rep['min']:.1f} ✓")
    return len(classes()), rep["min"]


def note() -> str:
    """给台账/日志的一句话说明，免得口径被抄错。"""
    return ("显示类 = 覆盖 × 形态 × 热量带 × 干湿，**不存储**、由编辑器按 display_lut 当场查"
            "（见 docs/adr/0006、0007）；名字与配色在 地图/栅格地形数据生成器/display_class.py，"
            "契约键 display_classes / display_lut")


def _cli() -> int:
    """`python 地图/栅格地形数据生成器/display_class.py` —— 打印类清单（带真实格数）与配色 ΔE 报告。"""
    import os
    from PIL import Image
    from mapdata import GRID_TERRAIN, under
    clim_png = under("栅格", "气候编码.png")
    live = None
    if os.path.exists(GRID_TERRAIN) and os.path.exists(clim_png):
        t = np.asarray(Image.open(GRID_TERRAIN).convert("L"), dtype=np.uint8)
        c = np.asarray(Image.open(clim_png).convert("L"), dtype=np.uint8)
        live = usage(t, c, log=lambda s: None)["counts"]
    print(f"显示类 {len(classes())} 类（名字与配色见 display_class.py 的 PAINT）")
    tot = sum(live.values()) if live else 0
    rows = sorted(classes(), key=lambda x: -(live or {}).get(x["n"], 0))
    for c in rows:
        n = (live or {}).get(c["n"], 0)
        pct = f"{n / tot * 100:7.3f}%" if tot else "      —"
        print(f"  {c['c']}  {c['n']:<10}{pct}  {n:>9,}")
    print()
    rep = check_palette(only=set(live) if live else None)
    if rep["bad"]:
        print("  最差的前 8 对：")
        for d, a, b in rep["pairs"]:
            print(f"    ΔE={d:5.1f}  {a} ／ {b}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
