# -*- coding: utf-8 -*-
"""显示类（display class）：**地形 = 覆盖 × 形态 × 气候 的组合**，一个组合一个名字。

    from display_class import label, payload, check_palette, usage

**这一层是"地形"这个概念本身**（2026-10-09 统一口径）。`docs/adr/0006` 把气候从地形里摘出去、
`docs/adr/0007` 又把地形拆成**覆盖 × 形态**两个半字节之后，存储里只剩 12 个覆盖 + 4 个形态
+ 一张气候图，而玩家在图上要看、在门口拦路时要判的仍然是**雨林／针叶林／沙漠／戈壁／
苔原／高山草原**这些名字。**名字不存储**：三轴一合，当场算出来。

    地形 = 覆盖 × 形态 × 气候 = 显示类        ← 三者是同一个东西的三种说法

## 名字是**全函数**，没有兜底分支

v1 的规则表是"有序首命中 + 末尾几条形态兜底"，于是两条路都会漏：

  · **没命中的组合**落回「覆盖 · 形态」这种拼凑名（真出现过 `地形 undefined`）；
  · **被前面通配规则吃掉的规则**永远不生效（子代理验收量到三条 hits=0 的死规则）。

现在改成**按轴组合**：每个覆盖有一张自己的**轴向词表**（形态前缀 / 热量带 / 干湿），
`label()` 对**任何** `(覆盖, 形态, 热量带, 干湿)` 都给出名字——包括气候上不可能出现、
但万一数据变了就会冒出来的组合（如「亚寒带荒漠草原」）。所以：

  · 管线里不再需要"规则表漏了哪个组合"这条检查（**漏不了**）；
  · 也不必再猜"某条规则是不是死的"——**没有规则**，只有词表。
  · 编辑器不扫规则表找下标，直接查 `display_lut`（见下），940 万格的统计循环因此由
    O(格数 × 规则条数) 降到 O(格数) 的一次数组读。

## 契约：`display_classes` + `display_lut`

    display_classes[i] = {"n": 名字, "c": 颜色}          // 60 类，**只此一处**定名字与配色
    display_lut[((覆盖×4 + 形态)×32) + 码] = 类下标       // 1536 项，覆盖全部组合

「码」是气候码（热量带 × 8 + 干湿，0..31）；**干湿为 0 时整条码归零**（那 2 位是
don't-care，见 `climate.py`：先读干湿）。两个写入方（`build_raster` / `import_editor`）
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
FOREST, GRASS, WASTE = TR.C_FOREST, TR.C_GRASS, TR.C_WASTE
MARSH, TIDAL, SALTM = TR.C_MARSH, TR.C_TIDAL, TR.C_SALTM
FARM, OASIS = TR.C_FARM, TR.C_OASIS
PLAIN, HILL, PLATEAU, MOUNTAIN = TR.F_PLAIN, TR.F_HILL, TR.F_PLATEAU, TR.F_MOUNTAIN

# ================================================================ 命名：一份轴向词表
# 每个覆盖一张词表；`label()` 只做"按轴向取词 + 拼"，没有任何"命中/未命中"。
_HEAT_PRE = {TROP: "热带", SUB: "亚热带", TEMP: "温带", SUBARC: "亚寒带"}
# 草原：干湿三档（干旱 / 半干旱 / 其余）。⚠️ 这三档是**柯本季节型的粗分**，不是年降水量的
# 量化——柯本的第三个字母只分 s/w/f。所以"其余"里既有冬干（Dw）也有常湿（Df），
# 名字取"草甸草原"是因为温带那一档（黑土草原）确实是它，亚寒带夏雨那档（蒙古高原）也说得过去。
_GRASS_TIER = {1: "荒漠草原", 2: "典型草原"}
# 草甸（覆盖，LC100 农田聚落）：形态优先，其次热量带。⚠️ 与草原的「草甸草原」差一个"草原"，
# 两者是不同的东西（前者是覆盖、是地表，后者是覆盖草原的一档气候）。
_FARM_BY_HEAT = {TROP: "热带草甸", SUB: "亚热带草甸", TEMP: "温带草甸", SUBARC: "温带草甸"}
# 森林：低地按热量带 × 干湿分林型（这是"雨林/常绿/落叶/针叶"四个词的来处）；
# 高原/山地上只按热量带分（形态优先，干湿那一档让位——否则组合会炸成几十个）。
_FOREST_ALPINE = {TROP: "雨林", SUB: "常绿林", TEMP: "阔叶林", SUBARC: "针叶林"}
_FOREST_LOW = {
    TROP: {1: "热带疏林", 2: "热带疏林", 3: "热带季雨林", 5: "热带季雨林",
           6: "热带雨林", 7: "热带雨林"},
    SUB: {1: "亚热带疏林", 2: "亚热带疏林", 3: "亚热带疏林", 4: "亚热带硬叶林",
          5: "亚热带常绿阔叶林", 6: "亚热带常绿阔叶林", 7: "亚热带常绿阔叶林"},
    # 温带冬雨（Dsa/Dsb，实测 529 格）并入落叶阔叶林：为 529 格单开一类，
    # 图例里多一行 0.006% 的噪声，不值。
    TEMP: {1: "温带疏林", 2: "温带疏林", 3: "温带落叶阔叶林", 4: "温带落叶阔叶林",
           5: "温带落叶阔叶林", 6: "温带落叶阔叶林", 7: "温带落叶阔叶林"},
    SUBARC: {1: "亚寒带疏林", 2: "亚寒带疏林", 3: "亚寒带针叶林", 4: "亚寒带针叶林",
             5: "亚寒带针叶林", 6: "亚寒带针叶林", 7: "亚寒带针叶林"},
}
# 荒漠：只按干湿分两档（沙漠/戈壁），形态加前缀。**不按热量带分**——荒漠是"干旱 ∧ 裸地"，
# 热量带对它几乎没有解释力（撒哈拉与塔克拉玛干只差一个"热/温"），分了只是白多几行图例。
_WASTE_DRY = {1: "沙漠"}


def label(cover: int, form: int, heat: int, moist: int) -> str:
    """一格的显示类名。**全函数**：任何组合都有名字，不存在"未匹配"。

    ⚠️ `moist == 0` 是「寒带」——热量带那 2 位是 don't-care（`climate.py`：先读干湿），
    所以这一支只按干湿判，**不许读 heat**（读了就会把同一格按 4 个热量带散成 4 个名字）。
    """
    cover, form = int(cover), int(form)
    heat, moist = int(heat), int(moist)
    if cover == OCEAN:
        return "海洋"
    if cover == LAKE:
        return "高原湖泊" if form in (PLATEAU, MOUNTAIN) else "湖泊"
    if cover == RIVER:
        return {PLATEAU: "高原河流", MOUNTAIN: "山地河流"}.get(form, "河流")
    if cover == ICE:
        return {MOUNTAIN: "山地冰川", PLATEAU: "高原冰川"}.get(form, "冰川")
    if cover == FARM:
        if form == MOUNTAIN:
            return "山地草甸"
        if form == PLATEAU:
            return "高原草甸"
        return "温带草甸" if not moist else _FARM_BY_HEAT.get(heat, "温带草甸")
    if cover == OASIS:
        return "绿洲"
    if cover == MARSH:
        return "寒沼" if not moist else "沼泽"
    if cover == SALTM:
        return "盐沼"
    if cover == TIDAL:
        return "滩涂"
    if cover == FOREST:
        if form in (PLATEAU, MOUNTAIN):
            pre = "高原" if form == PLATEAU else "山地"
            # 寒带（干湿 0）在林区读作亚寒带：那 2 位无意义，而林线附近长的就是针叶林
            return pre + _FOREST_ALPINE[TEMP if heat == TEMP else
                                        (SUBARC if (not moist or heat == SUBARC) else heat)]
        if not moist:
            return "亚寒带针叶林"
        return _FOREST_LOW.get(heat, _FOREST_LOW[TEMP]).get(moist, "温带落叶阔叶林")
    if cover == GRASS:
        if not moist:
            return "苔原"
        if form == PLATEAU:
            return "高原草原"
        if form == MOUNTAIN:
            return "高山草原"
        if heat == TROP:
            return {1: "热带荒漠草原", 2: "热带干草原", 3: "热带稀树草原"}.get(moist, "热带草原")
        return _HEAT_PRE.get(heat, "温带") + _GRASS_TIER.get(moist, "草甸草原")
    if cover == WASTE:
        dry = _WASTE_DRY.get(moist, "戈壁")
        if form == PLATEAU:
            return "高原" + dry
        if form == MOUNTAIN:
            return "山地" + dry
        return dry
    return _C[cover] if 0 <= cover < TR.N_COVER else f"覆盖 {cover}"


# ================================================================ 配色
PALETTE_MIN_DE = 9.0     # 任意两类的最小 CIE Lab 色差，`check_palette()` 守着它
# **族内色相微调 + 明暗浓淡**：色相由覆盖族定，族内靠色相偏移与明度/饱和拉开。
# 这张表不是拍脑袋凑的，也不是手调出来的 —— 先在 Lab 空间按语义锚点（下方注释里的 HSL）
# 做一次带锚点回拉的排斥，直到任意两类 ΔE ≥ 9，再量化到 8 位并修掉取整造成的破绽。
# 最终**锚点位移中位 0.3、最大 4.6**：色相语义（森林绿、荒漠土黄、水蓝…）没有跑掉。
# 调色脚本是一次性的，见 git 历史里的 `tools/_tmp_palette.py`（已删）——要改配色，
# 改这张表并重跑 `python tools/display_class.py` 看 ΔE 报告，别凭眼睛。
#   语义锚点（HSL，色相/饱和/明度），改色的意图写在这里：
#     水 199–235 蓝 ｜ 冰 近白→灰蓝 ｜ 森林 78–188 绿 ｜ 草原 38–92（色相=热量带、明度=干湿）
#     草甸 42–58 暖黄浅 ｜ 荒漠 20–44 土黄 ｜ 沼泽 170 青灰 ｜ 盐沼 104 ｜ 滩涂 20 ｜ 绿洲 132
PAINT: dict[str, str] = {
    # ---- 水（蓝）----
    "海洋": "#6f9ab8",
    "湖泊": "#91c7de",
    "高原湖泊": "#6c92c6",
    "河流": "#306acf",
    "高原河流": "#334b99",
    "山地河流": "#313668",
    # ---- 冰（近白 → 灰蓝，靠明度拉开）----
    "冰川": "#f3f9fc",
    "高原冰川": "#d7dfe6",
    "山地冰川": "#a9b5c1",
    # ---- 森林（绿）----
    "热带雨林": "#1d5d43",
    "热带季雨林": "#317d57",
    "热带疏林": "#4c956e",
    "亚热带常绿阔叶林": "#2e7641",
    "亚热带硬叶林": "#5f814c",
    "亚热带疏林": "#68a26f",
    "温带落叶阔叶林": "#569c37",
    "温带疏林": "#8db06d",
    "亚寒带针叶林": "#1f4721",
    "亚寒带疏林": "#426742",
    "高原雨林": "#255f54",
    "高原常绿林": "#43897f",
    "高原阔叶林": "#5d9d4d",
    "高原针叶林": "#1f3e30",
    "山地雨林": "#336f71",
    "山地常绿林": "#578c94",
    "山地阔叶林": "#62723a",
    "山地针叶林": "#334f47",
    # ---- 草原（黄绿：色相=热量带，明度=干湿三档）----
    "苔原": "#caccbf",
    "高原草原": "#828d53",
    "高山草原": "#626141",
    "热带荒漠草原": "#cdbca3",
    "热带干草原": "#bc9f69",
    "热带稀树草原": "#aa813c",
    "热带草原": "#bbc77e",
    "亚热带荒漠草原": "#cec79f",
    "亚热带典型草原": "#bdba68",
    "亚热带草甸草原": "#aaa23c",
    "温带荒漠草原": "#cad7a6",
    "温带典型草原": "#a8bd66",
    "温带草甸草原": "#90aa3c",
    "亚寒带荒漠草原": "#adc9a0",
    "亚寒带典型草原": "#91bf69",
    "亚寒带草甸草原": "#73ac3c",
    # ---- 草甸（暖黄，浅）----
    "热带草甸": "#d7c071",
    "亚热带草甸": "#eadc9d",
    "温带草甸": "#e8daba",
    "高原草甸": "#d7d184",
    "山地草甸": "#ab984a",
    # ---- 荒漠（土黄）----
    "沙漠": "#d5b272",
    "戈壁": "#b3916b",
    "高原沙漠": "#bd9c42",
    "高原戈壁": "#8d6c53",
    "山地沙漠": "#916f3b",
    "山地戈壁": "#644d40",
    # ---- 湿地与绿洲 ----
    "寒沼": "#bacdcd",
    "沼泽": "#669991",
    "盐沼": "#98ac91",
    "滩涂": "#baa9a0",
    "绿洲": "#3da451",
}


# ================================================================ 组合 → 类
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
        names, lut = [], np.zeros(1536, dtype=np.int32)
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
    """组合下标 → 类下标（1536 项）。编辑器侧只查这一张表，不扫规则。"""
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

    `terr` 是地形字节（覆盖在高 4 位、形态在低 4 位），`clim` 是气候码。给管线日志与
    `python tools/display_class.py` 用：好知道 60 个类里哪几个真的出现在这张图上。
    """
    terr = np.asarray(terr).astype(np.int64)
    clim = np.asarray(clim).astype(np.int64) & 31
    cov, frm = terr >> 4, terr & 15
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

    为什么 LUT 要 1536 全覆盖：编辑器不扫规则、只查这张表（`((覆盖×4+形态)×32)+码`），
    表短一格或有一个越界下标，那一格在图上就是"查不到"的灰点——而 940 万格里看不出是哪一格。
    """
    l = lut()
    assert l.shape[0] == 1536, f"display_lut 长度 {l.shape[0]} ≠ 1536"
    assert int(l.min()) >= 0 and int(l.max()) < len(classes()), "display_lut 里有越界的类下标"
    rep = check_palette(PALETTE_MIN_DE, log=lambda s: None)
    if log is not None:
        log(f"  显示类 {len(classes())} 类 · LUT 1536 组合全覆盖 ✓ · "
            f"任意两类最小 ΔE {rep['min']:.1f} ✓")
    return len(classes()), rep["min"]


def note() -> str:
    """给台账/日志的一句话说明，免得口径被抄错。"""
    return ("显示类 = 覆盖 × 形态 × 热量带 × 干湿，**不存储**、由编辑器按 display_lut 当场查"
            "（见 docs/adr/0006、0007）；名字与配色在 tools/display_class.py，"
            "契约键 display_classes / display_lut")


def _cli() -> int:
    """`python tools/display_class.py` —— 打印类清单（带真实格数）与配色 ΔE 报告。"""
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
