#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成栅格底图：地块 id 栅格 + 块区 id 栅格 + 地形栅格 + 参考顶点矢量。

栅格是全图唯一几何真源，**一一映射**：每个像元恰好一条记录（地块编码 + 块区编码 + 地形）。

    python tools/build_raster.py                     # 默认 cell 1/19° → 3819 × 2470（窗口见 mapdata.SCOPE_*）
    python tools/build_raster.py --no-veg            # 不读土地覆盖（地形只按高程+掩膜）
    python tools/build_raster.py --raw-lc100         # 裸数组自检通过时用它（否则自动走 TIFF）
    python tools/build_raster.py --no-terrain        # 只出地块层（不等高程）
    python tools/build_raster.py --cell 0.075        # 粗一档（2813 × 1840），体积小约 28%

输入（数据目录：地图/地图数据/）：
  基础单元.json                     由 build_editor.py --dump-units 产出
  原始数据/高程与地表/全球高程_ETOPO_60秒.tif      ETOPO 2022 60s 高程（NOAA，公有领域）
  原始数据/高程与地表/全球土地覆盖_100米.tif       Copernicus LC100 离散分类（森林/雨林等）
  原始数据/气候/koppen_geiger_tif.zip            柯本气候分类（Beck et al. 2023）→ 沙漠判据
  （LC100 的满分辨率裸数组曾在此，2026-10-07 深夜 已删：它是残件。见 #15.3）
  原始数据/自然地球/*.zip                         陆地 / 湖泊 / 冰川 / 具名地貌 / 河流掩膜
  原始数据/唐至明政区/Hartwell_*.zip               参考层的唐 741 州面

输出（地图/地图数据/栅格/）：
  地块编码.png   24 位 RGB，R + G*256 = 地块编码（0 = 无地块）—— 与 P社 province.bmp 同法
  分区编码.png   同上，0 = 无块区；块区隶属于地块 —— 初始全空，由编辑器绘制
  地形编码.png   8 位灰度 = 覆盖(高 4 位) × 16 + 形态(低 4 位)；见 docs/adr/0007
  参考顶点.bin   **矢量顶点**（现代单元边界 + 唐 741 州面）—— 参考层不再是栅格掩膜
  台账.json      网格几何 / 地形图例 / 陆地口径 / 沙漠判据 / 地块台账
  高程/起伏/植被/气候/水体_降采样.npy   中间层（改分类规则时不必重读原图）

**海洋口径只有一处**：陆地 = Natural Earth 10m 陆地 ∪ 湖泊 ∪ 冰川区（格心命中）。
地形层的「海洋」是该掩膜的补集，地块层也被它裁掉 —— 于是「地块不可能落在海洋上」
在数据侧就是恒真的（编辑器侧只按 `地形 == 海洋` 拦笔，不必再存第二张掩膜）。

另出编辑器要的 `地图/地图编辑器/js/data.js`（**只这一件**，生成逻辑在 `tools/editor_data.py`）。
图**不拷给编辑器**：真源只有 `地图/地图数据/栅格/` 一处（`docs/adr/0002`），
编辑器由 `启动编辑器.bat` → `serve.py` 的 `/数据/` 虚拟挂载去读它。单文件版那条线
（editor_pack / build_single / 内联 base64）已按需求方指令整条删除 —— 两份产物必然分叉。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import zipfile

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import MultiPolygon, Polygon, shape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo_wrap import wrap_into, supercover                          # noqa: E402
from mapdata import (ROOT, under, UNITS as UNITS_JSON, RASTER, NE_DIR,      # noqa: E402
                     NE_LAND, NE_LAKES, NE_RIVERS, NE_REGIONS, NE_GLACIATED,
                     ETOPO_TIF, LC100_TIF, LC100_RAW, HARTWELL_ZIP, URL_PREFIX,
                     KOPPEN_ZIP, hydro_rivers, CELL as CELL0,
                     SCOPE_LON0, SCOPE_LON1, SCOPE_LAT0, SCOPE_LAT1)
import terrain as TR                                                    # noqa: E402
import climate as CL                                                    # noqa: E402
import display_class as DC                                              # noqa: E402
import rivers as RV                                                     # noqa: E402
from refvec import build_ref_vector                                     # noqa: E402
from basetag import base_tag as make_base_tag                           # noqa: E402
from basetag import name_tag as _bt_name_tag, legend_tag as _bt_legend_tag   # noqa: E402

UNITS = UNITS_JSON
NE = NE_DIR
ETOPO = ETOPO_TIF
OUT = RASTER

# 栅格层文件名（也中文，见 tools/mapdata.py）
F_PLOT, F_DIST, F_TERRAIN, F_REFV, F_META = (
    "地块编码.png", "分区编码.png", "地形编码.png", "参考顶点.bin", "台账.json")
F_CLIM = "气候编码.png"                    # 产品层（v2 起）：两轴合成一格 = 热量带 × 8 + 干湿
F_ELEV, F_RELIEF, F_VEG = "高程_降采样.npy", "起伏_降采样.npy", "植被_降采样.npy"
# 荒漠的海拔上限。柯本把羌塘/阿里（4700–5300 m）也判成干旱，于是青藏整片成了荒漠。
# 实测：戈壁 p99 2131/max 3024、柴达木 p50 2938、羌塘 p50 4740 —— 线画在 3500 m。
WASTE_MAX_ELEV = 3500.0
# 河段短于这么多格就不画：低于 6.9 km 栅格的分辨能力，画出来是散点（见 cleanup_river_specks）。
RIVER_MIN_CELLS = 4
F_CLIMATE = "气候_降采样.npy"              # 构建期中间层（柯本类栅格），改规则不必重读 130 MB
F_WATER = "水体_降采样.npy"

# 世界窗口与格边长的唯一出处（编辑器筛单元用的是同一份，见 tools/mapdata.py）
LON0, LON1 = SCOPE_LON0, SCOPE_LON1
LAT0, LAT1 = SCOPE_LAT0, SCOPE_LAT1

TERRAIN_LEGEND = TR.COVER_LEGEND      # v3：地形字节的**高 4 位**是「覆盖」（12 值）
FORM_LEGEND = TR.FORM_LEGEND          # 低 4 位是「形态」（4 值，海洋格写 0 当 don't-care）
(T_OCEAN, T_LAKE, T_RIVER, T_ICE, T_FOREST, T_GRASS, T_WASTE, T_MARSH, T_TIDAL, T_SALTM,
 T_FARM, T_OASIS) = range(len(TERRAIN_LEGEND))
(F_PLAIN, F_HILL, F_PLATEAU, F_MOUNTAIN) = range(len(FORM_LEGEND))
# ⚠️ 本文件里那个叫 `terrain` 的数组，v3 起指的是**覆盖那一轴**（不含形态）；形态在 `form`
# 里，两者**只在落盘时**用 `TR.pack()` 合进一个字节。名字没改，是为了让河流那一段
# （烧伤/封缝/对角/去散点/收口）一行都不用动——它们本来只管"这是不是水"。


def assert_contract(terrain, form, plot_id, districts, heat, moist, klim, lat, land, log=print):
    """数据契约断言（`docs/adr/0006` + `0007`）。**红一条就抛，不许静默落盘。**

    为什么值得为它们开一个函数：v3 把覆盖压到 4 位、形态压到 4 位、地块压到 **13** 位、
    块区压到 8 位局部码，余量都不大；而"余量用尽"这件事一旦发生，后果是**静默截断**
    （溢出回绕写进 PNG，图上根本看不出是哪一格坏了）。所以宁可让管线在最后一步红掉。

    第 5 条（无气候洞）最隐蔽：干湿码 0 同时表示「寒带」与「无气候数据」，空洞会被读成
    寒带。**它第一次上线就把这条拦下来了**：原先以为那些洞都在极地（只看过纬度最高的 3 格
    就写了"实测全在 81.7–81.8°N"），实测 11,352 格里有阿拉斯加、波罗的海、堪察加，
    纬度最低到 9.4°N——柯本把水体与冰盖 mask 成 nodata，而 NE 说那是陆。修法是
    `CL.fill_land_nodata` 补洞，这条断言守着它不再长回来。

    第 6 条（显示类覆盖全组合）是 v3 新加的：拆成两轴之后，`(覆盖, 形态)` 的组合数从 14
    涨到 12×5，**规则表漏一个组合**的后果是编辑器里显示 "地形 undefined"（v1 真的发生过：
    调色板里存了下标而不是颜色串）。
    """
    bad = []
    if int(terrain.max()) >= 1 << 4:
        bad.append(f"覆盖码最大 {int(terrain.max())} ≥ 16（高 4 位装不下）")
    if form is not None and int(form.max()) >= 1 << 4:
        bad.append(f"形态码最大 {int(form.max())} ≥ 16（低 4 位装不下）")
    if form is not None and int(form[terrain == T_OCEAN].max(initial=0)) != 0:
        bad.append("海洋格的形态位不是 0（海洋没有形状可言）")
    if int(plot_id.max()) > 8191:
        bad.append(f"地块编号最大 {int(plot_id.max())} > 8,191（13 位装不下）")
    if heat is not None and int(heat.max()) > 3:
        bad.append(f"热量带最大 {int(heat.max())} > 3（2 位装不下）")
    if moist is not None and int(moist.max()) > 7:
        bad.append(f"干湿码最大 {int(moist.max())} > 7（3 位装不下）")
    per_plot = {}
    for d in districts:
        per_plot[d["plot"]] = per_plot.get(d["plot"], 0) + 1
    worst = max(per_plot.values()) if per_plot else 0
    if worst > 255:
        bad.append(f"单个地块下辖块区最多 {worst} > 255（8 位局部码装不下）")
    if klim is not None:
        n, minlat = CL.polar_nodata(klim, lat, land)
        if n:
            bad.append(f"陆地上还有 {n} 格无气候数据（最小 |纬度| {minlat:.1f}°）——"
                       f"干湿码 0 会把它静默读成「寒带」；先补洞（CL.fill_land_nodata）")
    if form is not None:
        cv = np.unique(terrain)
        fv = np.unique(form)
        miss = DC.missing(cv, fv, log=log)
        if miss:
            bad.append(f"显示类规则表漏了 {miss} 个 (覆盖, 形态) 组合")
        if heat is not None and moist is not None:
            dead = DC.rule_hits(terrain, form, heat, moist, log=log)
            if dead:
                bad.append(f"显示类有 {len(dead)} 条规则从未命中（被前面的通配规则吃掉）："
                           + "、".join(dict.fromkeys(dead)))
    log(f"  契约断言：覆盖 <12 ✓  形态 <4 ✓  海洋形态=0 ✓  地块 ≤8,191 ✓  "
        f"热量带 ≤3 / 干湿 ≤7 ✓  每地块块区 ≤255（实测最多 {worst}）✓  "
        f"陆地无气候洞 ✓  显示类覆盖全组合 ✓")
    assert not bad, "数据契约被破坏：\n  · " + "\n  · ".join(bad)


# ---------------------------------------------------------------- 读取

def ne_features(path: str):
    """path：原始件完整路径（文件名见 tools/mapdata.py，都中文）"""
    if not os.path.exists(path):
        print(f"  ! 缺 {os.path.basename(path)}，跳过", file=sys.stderr)
        return []
    import shapefile
    z = zipfile.ZipFile(path)
    shp = [n for n in z.namelist() if n.endswith(".shp")][0]
    sf = shapefile.Reader(shp=io.BytesIO(z.read(shp)), dbf=io.BytesIO(z.read(shp[:-4] + ".dbf")))
    return [(shape(sr.shape.__geo_interface__), sr.record.as_dict()) for sr in sf.iterShapeRecords()]


def unit_polys(u, k):
    polys = []
    for rr in u["g"]:
        rng = lambda r: [(r[i] / k, r[i + 1] / k) for i in range(0, len(r), 2)]
        polys.append(Polygon(rng(rr[0]), [rng(h) for h in rr[1:]]))
    return MultiPolygon(polys) if len(polys) > 1 else polys[0]


def wraps(g):
    """几何在连续经度窗口下的分段：沿窗口两条缝切开再整段平移。
    绝不能逐点折回——那会切穿几何，把它拉成横贯全图的带（本轮色条的根因）。"""
    return wrap_into(g, LON0, LON1)


def bbox_cells(g, cell, W, H):
    x0, y0, x1, y1 = g.bounds
    c0 = max(0, int(np.floor((x0 - LON0) / cell)) - 1)
    c1 = min(W, int(np.ceil((x1 - LON0) / cell)) + 1)
    r0 = max(0, int(np.floor((LAT1 - y1) / cell)) - 1)
    r1 = min(H, int(np.ceil((LAT1 - y0) / cell)) + 1)
    return c0, c1, r0, r1


def encode_id(a: np.ndarray) -> np.ndarray:
    """uint16 编码 → 24 位 RGB（R + G*256）。canvas 会把 16 位灰度降成 8 位，故不用灰度。"""
    rgb = np.zeros((a.shape[0], a.shape[1], 3), dtype=np.uint8)
    rgb[..., 0] = a & 0xFF
    rgb[..., 1] = (a >> 8) & 0xFF
    return rgb



def seal_river_gaps(terrain: np.ndarray, value: int, water, log=print) -> int:
    """把同一条河被**折线端点错位**切出的 ≤3 格缝接上。返回封了几处。

    为什么 `burn_lines` 之后还需要这一步：NE 的 `rivers_lake_centerlines` 是**概化**过的
    线网，它自己在湖泊两端与支流汇口处会把线切断，而两条折线的端点并不重合。实测长江的
    MultiLineString 就分 3 段，淮河入江口那处两端点差 **2 格**（119.56E 32.25N）——
    4 邻接断开，屏幕上就是"断流"。`burn_lines` 只保证**单条折线内部** 4 邻接连通，
    管不了折线与折线之间的缝（修完那一层，全图 4 邻接碎段 6,834 → 265，剩下的 265 里
    有 10 处是这种端点缝）。

    判据取**保守**（宁漏不滥，接错了比断着更难看）：

      · 只在**骨架端点**之间连 —— 端点是"线头"；线的腰部不能当端点用。
      · 只连 ≤3.5 格（≈24 km）的缝；其中 ≤2 格的无条件连，>2 格的**要有一端的朝向
        指着对方**（否则可能把两条本来不相干的河接上）。
      · 每个线头最多用一次（按距离贪心，先近后远）。
      · 桥经过的格子若已是**海洋或湖泊**就不封：海是真正的分隔；湖与河同为蓝色，
        视觉上本来就不算断（把湖改成河反而是改错了东西）。
    """
    from scipy import ndimage
    from skimage.morphology import skeletonize

    H, W = terrain.shape
    riv = terrain == value
    if int(riv.sum()) < 3:
        return 0
    st4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], np.uint8)
    st8 = np.ones((3, 3), np.uint8)
    st8[1, 1] = 0
    lab, n0 = ndimage.label(riv, structure=st4)
    skel = skeletonize(riv)
    ends = np.argwhere(skel & (ndimage.convolve(skel.astype(np.uint8), st8,
                                                mode="constant", cval=0) == 1))

    def out_dir(r, c, steps=4):
        """从线头沿骨架向内走若干格，返回**朝外**的单位方向（(dy, dx)）。"""
        prev, cur, seen = None, (int(r), int(c)), {(int(r), int(c))}
        for _ in range(steps):
            nxt = None
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = cur[0] + dr, cur[1] + dc
                    if 0 <= nr < H and 0 <= nc < W and skel[nr, nc] and (nr, nc) not in seen:
                        nxt = (nr, nc)
                        break
                if nxt:
                    break
            if not nxt:
                break
            seen.add(nxt)
            prev, cur = cur, nxt
        if prev is None:
            return None
        dy, dx = cur[0] - r, cur[1] - c
        n = (dy * dy + dx * dx) ** 0.5
        return (-dy / n, -dx / n) if n else None

    pairs = []
    for i in range(len(ends)):
        ri, ci = ends[i]
        for j in range(i + 1, len(ends)):
            rj, cj = ends[j]
            if lab[ri, ci] == lab[rj, cj]:
                continue                                # 同一段，不用接
            d = float(((ri - rj) ** 2 + (ci - cj) ** 2) ** 0.5)
            if d > 3.5:
                continue
            vy, vx = (rj - ri) / d, (cj - ci) / d
            di, dj = out_dir(ri, ci), out_dir(rj, cj)
            ai = di[0] * vy + di[1] * vx if di else 0.0                # i 是否朝着 j
            aj = dj[0] * -vy + dj[1] * -vx if dj else 0.0              # j 是否朝着 i
            if d <= 2.05 or ai >= 0.5 or aj >= 0.5:
                pairs.append((d, (int(ri), int(ci)), (int(rj), int(cj))))
    # **端点 → 任意河格（T 型汇口）**：上一版只在"端点↔端点"之间接，管不了"支流端点指向
    # 干流腰部"这种最常见的汇口。实测漏出来的缝全属于这一类（如南京段长江 118.63E/32.11N，
    # 两条折线只差 1.41 格、还都是端点，但一条是另一条的"腰"）。做法：沿端点朝外的方向
    # 找一个锥形扇面（±50°）内最近的**别的段**的河格，≤3.5 格就接。
    import math
    erc2 = {}
    for i in range(len(ends)):
        ri, ci = int(ends[i][0]), int(ends[i][1])
        di = out_dir(ri, ci)
        if di is None:
            continue
        best = None
        R = 4
        for dy in range(-R, R + 1):
            for dx in range(-R, R + 1):
                if dy == 0 and dx == 0:
                    continue
                rj, cj = ri + dy, ci + dx
                if not (0 <= rj < H and 0 <= cj < W):
                    continue
                if not riv[rj, cj] or lab[rj, cj] == lab[ri, ci]:
                    continue
                d = math.hypot(dy, dx)
                if d > 3.6:
                    continue
                cos = (di[0] * dy + di[1] * dx) / d          # 是否朝着它
                if cos < 0.5:
                    continue
                if best is None or d < best[0]:
                    best = (d, (rj, cj))
        if best is not None:
            erc2[(ri, ci)] = best
    for a, (d, b) in erc2.items():
        pairs.append((d, a, b))
    pairs.sort(key=lambda t: t[0])

    used, sealed = set(), 0
    for _d, a, b in pairs:
        if a in used or b in used:
            continue
        used.add(a)
        used.add(b)
        cells = [(y, x) for y, x in supercover(a, b) if 0 <= y < H and 0 <= x < W]
        # 跨水面的桥：**只禁长的**。河中间夹 1 格小湖、河口那 1 格，本来就是河自己
        # （不接就是地图上一个亮点，实测需求方看到的就是这个）；而贝加尔那种长水面，
        # 河本来就该在湖岸断掉（进湖—出湖）。所以只允许桥经过 ≤2 格水面。
        if sum(1 for y, x in cells if terrain[y, x] in water) > 2:
            continue
        for y, x in cells:
            terrain[y, x] = value
        sealed += 1
    n1 = int(ndimage.label(terrain == value, structure=st4)[1])
    log(f"  河流封缝：{len(ends)} 个线头 → 封 {sealed} 处（4 邻接碎段 {n0} → {n1}）")
    return sealed


def cleanup_river_specks(terrain, before, value: int, min_cells: int, log=print) -> int:
    """丢掉短于 min_cells 的河段（还原成**烧伤之前**的地形类），返回丢了几格。

    为什么需要：线网是从**分区文件**拼起来的（HydroRIVERS 只下了 as/si/eu/au 四片），
    一条河的链条可能上游落在没下到的那片里，于是只剩孤零零一格插在海岛或海岸上。
    实测这一版有 7,340 个「孤立单格河」，海拔中位 **10 m**、48% 的邻格是海洋 ——
    全是北冰洋小岛与河口处的碎片。一格 6.9 km，画出来就是地图上的蓝色噪点。

    判据只看**连通段大小**（短于栅格分辨能力的不画），不看位置，不挑肥拣瘦。
    `before` 是河烧伤之前的 terrain 快照，丢掉的位置直接还原回去。
    """
    from scipy import ndimage
    st4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    riv = terrain == value
    lab, n = ndimage.label(riv, structure=st4)
    if not n:
        return 0
    sizes = np.bincount(lab.ravel())
    tiny = np.where((sizes > 0) & (sizes < min_cells))[0]
    drop = np.isin(lab, tiny)
    k = int(drop.sum())
    if k:
        terrain[drop] = before[drop]
    log(f"  河段去散点：{n:,} 段里丢掉 {int(tiny.size):,} 段"
        f"（< {min_cells} 格 = 低于栅格分辨能力）→ 还原 {k:,} 格")
    return k


def connect_diagonal_rivers(terrain, value: int, log=print) -> int:
    """把"两个**不同的**河段只靠一个角相连"补成正交相连，返回补了几格。

    为什么还要这一步：`supercover` 保证的是**同一条折线内部** 4 邻接连通；`seal_river_gaps`
    管的是"两个断头离得近"。两者都管不了**段与段之间恰好只用对角相接**——两格共享一个角，
    看着相连、缩小时会散架（地图的规矩是 4 邻接）。实测残留的 17 处全属这一类
    （南京段长江 118.63E/32.11N 就是一处）。

    ⚠️ 只补**跨段**的对角：同一段内部本来就是楼梯状 4 邻接，那些角接触无害；
    一律补会把河"加粗"（实测那样会多补 5.4 万格、河格从 1.45% 涨到 2.06%）。
    """
    from scipy import ndimage
    H, W = terrain.shape
    riv = terrain == value
    st4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    lab = ndimage.label(riv, structure=st4)[0]
    water = np.isin(terrain, (T_OCEAN, T_LAKE, T_RIVER))
    add = np.zeros((H, W), dtype=bool)
    for dy, dx in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        r0, r1 = max(0, -dy), min(H, H - dy)
        c0, c1 = max(0, -dx), min(W, W - dx)
        a = riv[r0:r1, c0:c1]
        b = riv[r0 + dy:r1 + dy, c0 + dx:c1 + dx]
        la = lab[r0:r1, c0:c1]
        lb = lab[r0 + dy:r1 + dy, c0 + dx:c1 + dx]
        cross = a & b & (la != lb) & (la > 0) & (lb > 0)
        if not cross.any():
            continue
        v1 = terrain[r0 + dy:r1 + dy, c0:c1]              # 纵向桥格
        v2 = terrain[r0:r1, c0 + dx:c1 + dx]              # 横向桥格
        use1 = cross & ~water[r0 + dy:r1 + dy, c0:c1]     # 纵向桥是陆地 → 点它
        add[r0 + dy:r1 + dy, c0:c1] |= use1
        use2 = cross & ~use1 & ~water[r0:r1, c0 + dx:c1 + dx]
        add[r0:r1, c0 + dx:c1 + dx] |= use2
    k = int(add.sum())
    if k:
        terrain[add] = value
    log(f"  对角补格：跨段「只靠角相连」的河补成正交 {k:,} 格")
    return k


def name_tag(seeds) -> str:
    """保留这个名字做兼容（旧调用点），实现已挪到 tools/basetag.py 与 import_editor 共用。"""
    return _bt_name_tag([s["n"] for s in seeds])


def legend_tag() -> str:
    """图例摘要：**覆盖与形态都要进**——只改形态同样会让旧草稿失效。"""
    return _bt_legend_tag(list(TERRAIN_LEGEND) + list(FORM_LEGEND))


# ---------------------------------------------------------------- 运行态转储（v3 新增）

def write_runtime(cover, form, plot_id, dist_local, heat, moist, W, H, cell, out_dir, log=print):
    """把四层打包成**一条 32 位记录**，zlib 落成一件给游戏加载的文件。

    契约（`docs/adr/0007`）：

        位 31..28  覆盖 4      位 27..26  形态 2
        位 25..24  热量带 2    位 23..21  干湿 3
        位 20..8   地块 13     位 7..0    块区局部 8
        = 32 位整 → 一个 `Uint32Array` 装完

    地理区（8 位）**将来单独一个 `Uint8Array`**，不进这条记录：它是叠在行政图上的另一类
    信息，不该挤占"每格一条"的热路径。

    为什么值得落这一件：真源那几张 PNG 是给人看、给人单层改的（合计约 0.12 B/格）；而游戏
    要的是"一次随机访问拿到全部字段"。实测原始数组 zlib 压一遍只有约 1 MiB——**比那几张
    PNG 加起来还小**，解出来直接就是数组，不用 canvas、不用调色板。
    """
    import zlib
    z = np.zeros_like(plot_id)
    heat = z if heat is None else heat
    moist = z if moist is None else moist
    rec = ((cover.astype(np.uint32) << 28) | (form.astype(np.uint32) << 26)
           | (heat.astype(np.uint32) << 24) | (moist.astype(np.uint32) << 21)
           | (plot_id.astype(np.uint32) << 8) | dist_local.astype(np.uint32))
    hdr = json.dumps({"magic": "ZLRB1", "w": int(W), "h": int(H), "cell": float(cell),
                      "layout": "cover4|form2|heat2|moist3|plot13|block8",
                      "region": "地理区将来单独一个 Uint8 数组（尚未建）"},
                     ensure_ascii=False).encode("utf-8")
    blob = len(hdr).to_bytes(4, "little") + hdr + zlib.compress(rec.tobytes(), 9)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "底图.bin")
    with open(path, "wb") as f:
        f.write(blob)
    log(f"  运行态 底图.bin：{len(blob) / 1048576:.2f} MiB"
        f"（解出来 {rec.nbytes / 1048576:.1f} MiB 的 Uint32Array / "
        f"每格 4 B；原始压到 {len(blob) / rec.nbytes * 100:.1f}%）")
    return path


def read_runtime(path):
    """读回运行态转储 → (cover, form, heat, moist, plot_id, block_local)。给测试与游戏用。"""
    import zlib
    with open(path, "rb") as f:
        n = int.from_bytes(f.read(4), "little")
        json.loads(f.read(n).decode("utf-8"))
        rec = np.frombuffer(zlib.decompress(f.read()), np.uint32)
    return ((rec >> 28) & 0x0F, (rec >> 26) & 0x03, (rec >> 24) & 0x03, (rec >> 21) & 0x07,
            (rec >> 8) & 0x1FFF, rec & 0xFF)



# ---------------------------------------------------------------- 唐 741 州面（参考层用）

TANG_MEMBER = "v5_Hartwell/v5_0741_chin_chn_0741_p.shp"


def tang_rings(cell: float):
    """唐 741 州面 → 像素坐标的 (外环, [洞环]) 列表。

    上游是 Hartwell 的投影米制面（Xian80 GK19），先反算到 WGS84，再折回本图经度窗口
    （复用 probe_hartwell 的读取与 make_valid）。参考层用它替换汉地的现代县界：
    对着唐州顶点图改地块，比对着 1648 个县级单元的黑网有用得多。
    """
    if not os.path.exists(HARTWELL_ZIP):
        print(f"  ! 缺 {os.path.basename(HARTWELL_ZIP)}，汉地参考层只能沿用现代单元边界",
              file=sys.stderr)
        return []
    from probe_hartwell import load
    with zipfile.ZipFile(HARTWELL_ZIP) as zf:
        if TANG_MEMBER not in zf.namelist():
            print(f"  ! Hartwell 里没有 {TANG_MEMBER}", file=sys.stderr)
            return []
        _proj, wgs, _recs, _bad = load(zf, TANG_MEMBER)

    def to_px(coords):
        return [((x - LON0) / cell, (LAT1 - y) / cell) for x, y in coords]

    out = []
    for g in wgs:
        for piece in wraps(g):
            for p in getattr(piece, "geoms", [piece]):
                if p.geom_type != "Polygon":
                    continue
                out.append((to_px(p.exterior.coords), [to_px(r.coords) for r in p.interiors]))
    return out


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", type=float, default=CELL0,
                    help=f"像元边长（度）；默认 1/19° ≈ 5.86 km（0.075° ≈ 8.3 km 粗一档，"
                         f"1/16° = 0.0625° ≈ 6.9 km 是 2026-10-08 之前的旧值）")
    ap.add_argument("--no-terrain", action="store_true")
    ap.add_argument("--no-veg", action="store_true", help="不读 Copernicus 土地覆盖")
    ap.add_argument("--raw-lc100", action="store_true",
                    help="若裸数组存在且自检通过则用它（那份残件已删，一般用不上）")
    ap.add_argument("--river-min", type=float, default=RV.MIN_CMS, metavar="CMS",
                    help=f"画哪些河：HydroRIVERS 的多年平均流量 ≥ 此值（m³/s，默认 "
                         f"{RV.MIN_CMS:g}）。**河网密度就调这一个旋钮**："
                         f"100 → 全图约 12.9 万格（1.7%%，1.8 倍于上一版）；"
                         f"50 → 15.3 万；20 → 20.5 万（太密，实测像网）；"
                         f"200 → 更疏。见 tools/rivers.py")
    args = ap.parse_args()

    if not os.path.exists(UNITS):
        print("缺 基础单元.json：先跑 python tools/build_editor.py --dump-units", file=sys.stderr)
        return 1
    os.makedirs(OUT, exist_ok=True)

    cell = args.cell
    W = int(round((LON1 - LON0) / cell))
    H = int(round((LAT1 - LAT0) / cell))
    print(f"栅格 {W} × {H} = {W * H / 1e6:.1f} M 像元；像元 {cell}° ≈ {cell * 111:.1f} km")

    lon_c = LON0 + (np.arange(W) + 0.5) * cell
    lat_c = LAT1 - (np.arange(H) + 0.5) * cell
    LON, LAT = np.meshgrid(lon_c, lat_c)

    # ---------------- 陆地掩膜（全管线唯一口径） ----------------
    land_geoms = []
    for path, label in ((NE_LAND, "陆地"), (NE_LAKES, "湖泊"), (NE_GLACIATED, "冰川区")):
        feats = ne_features(path)
        hit = 0
        for g, _rec in feats:
            g = g.buffer(0)
            if g.is_empty:
                continue
            for gg in wraps(g):
                land_geoms.append(gg)
            hit += 1
        print(f"  陆地掩膜·{label}：{hit} 个面")
    land = TR.rasterize_union(LON, LAT, LON0, LAT1, cell, land_geoms)
    print(f"  陆地 {land.sum() / land.size * 100:.1f}% 像元（其余为海洋）")

    # ---------------- 地块 id 层 ----------------
    with open(UNITS, encoding="utf-8") as f:
        d = json.load(f)
    k, units, seeds = d["k"], d["units"], d["seeds"]
    print(f"单元 {len(units)}，种子地块 {len(seeds)}")
    plot_id = np.zeros((H, W), dtype=np.uint16)
    # 块区层（**底稿**）与地块层在**同一个循环**里写：一个单元的像元，地块编码与块区编码
    # 来自同一次 `contains_xy`，天然满足"块区必须落在它声明的地块内"这条硬约束
    # （import_editor 会校验），也省掉第二遍栅格化。这里先写**单元下标**做临时编号，
    # 循环结束后按"有像元的单元"重排成连续的块区编号。
    tmp_dist = np.zeros((H, W), dtype=np.uint16)
    order = sorted(range(len(units)), key=lambda i: -units[i]["a"])   # 大面先画，小面压上
    for n, i in enumerate(order, 1):
        g = unit_polys(units[i], k)
        c0, c1, r0, r1 = bbox_cells(g, cell, W, H)
        if c1 <= c0 or r1 <= r0:
            continue
        xs, ys = LON[r0:r1, c0:c1].ravel(), LAT[r0:r1, c0:c1].ravel()
        from shapely import contains_xy
        m = contains_xy(g, xs, ys).reshape(r1 - r0, c1 - c0)
        plot_id[r0:r1, c0:c1][m] = units[i]["sp"] + 1
        tmp_dist[r0:r1, c0:c1][m] = i + 1
        if n % 800 == 0:
            print(f"    {n}/{len(order)}")
    covered_raw = int((plot_id > 0).sum())
    # 裁掉压在海洋上的像元：单位面是按容差简化过的，沿海会甩出去几格（还有整片海域算进
    # 行政区的，如三沙那种"海上辖区"）。陆地掩膜是唯一口径，这里一次性对齐。
    plot_id[land == 0] = 0
    tmp_dist[plot_id == 0] = 0
    covered = int((plot_id > 0).sum())
    print(f"  覆盖 {covered / plot_id.size * 100:.1f}% 像元（其余为无地块）"
          f"；裁掉压在海上的 {covered_raw - covered:,} 格"
          f"（简化容差甩出海岸 + 行政区含海域）")
    blank = len(seeds) - (int(np.unique(plot_id).size) - 1)     # 台账里有、栅格里一格没落到的地块
    print(f"  零像元地块 {blank} 个（小单元落在格心之间 / 只剩海域；编辑器里会标「空」）")
    Image.fromarray(encode_id(plot_id), "RGB").save(os.path.join(OUT, F_PLOT), optimize=True)

    # ---------------- 块区层（底稿） ----------------
    # 块区 = **地块的下一级行政单元**（GLOSSARY："地块之下再分的一层"）。管线的产出只是
    # **底稿**，定稿由人在编辑器里改（`docs/adr/0001`：行政图 = 地块层 + 块区层）。
    #   · 中华：地块是按地级市归并出来的，所以它的下一级就是**县** —— 2421 个县 = 2421 个块区，
    #     名字全中文（GADM 的 NL_NAME_3）。
    #   · 世界：现在只到一级政区（一个一级政区就是一个地块），下一级还没有数据 → 先给
    #     每个地块 1 个占满它的块区，保证"每个地块都有块区"。
    #     ⚠️ 世界的**真**块区底稿要等 GADM L2 的中文名补齐（18,232 个单元，现在只有约一半
    #     有中文名，灌进去会满屏罗马字）—— 数据已下，见 TODO。
    # 编号：**全局 id 按单元下标顺序发**（台账读起来稳定），另发一个**地块内的局部序号**
    # 写进栅格——块区与地块的像元出自同一次 `contains_xy`，局部序号既省位（8 位够，
    # 实测每地块最多 32 个），又让"块区必落在其声明地块内"从校验变成构造保证。
    # 全局 id 由台账的 `(plot, local)` 确定性重算（编辑器解码时做这一步），
    # 所以 分区编码.png 用 8 位灰度就装得下，不必再上 R+G×256 那套。
    present = np.unique(tmp_dist)
    present = present[present > 0]
    blk_lut = np.zeros(len(units) + 1, dtype=np.uint16)
    districts = []
    seen = {}
    for n, ui in enumerate(present, 1):
        blk_lut[int(ui)] = n
        plot = units[int(ui) - 1]["sp"] + 1
        loc = seen.get(plot, 0) + 1
        seen[plot] = loc
        districts.append({"id": n, "name": units[int(ui) - 1]["n"],
                          "plot": plot, "local": loc})
    dist_id = blk_lut[tmp_dist]
    local_of = np.zeros(len(districts) + 1, np.uint8)
    for dd in districts:
        local_of[dd["id"]] = dd["local"]
    dist_local = local_of[dist_id]
    del tmp_dist
    nogap = int(((plot_id > 0) & (dist_id == 0)).sum())
    print(f"  块区底稿 {len(districts):,} 个（中华＝县；世界＝每地块 1 个占位）"
          f"；有地块却没块区的像元 {nogap}（必须为 0）"
          f"；栅格里的**局部序号** 1..{int(dist_local.max())}")
    assert nogap == 0, "块区必须覆盖每一个有地块的像元"
    # 分区编码.png = 8 位灰度，值 = **地块内的局部序号**（0 = 无块区）。
    Image.fromarray(dist_local, "L").save(os.path.join(OUT, F_DIST), optimize=True)

    # ---------------- 覆盖 × 形态（两个半字节） ----------------
    # v3 起这里有两个数组：`terrain` 是**覆盖**（12 值），`form` 是**形态**（5 值）。
    # 落盘时才 `TR.pack()` 合进一个字节（覆盖在高 4 位）——见 docs/adr/0007。
    terrain = np.full((H, W), T_OCEAN, dtype=np.uint8)
    form = np.zeros((H, W), dtype=np.uint8)
    ratio = {}
    if not args.no_terrain:
        if os.path.exists(ETOPO):
            print("读 ETOPO 高程（一次读取，裁到本图范围）…")
            elev, relief = TR.read_elevation(ETOPO, LON0, LON1, LAT0, LAT1, W, H)
            print(f"  高程 {elev.min():.0f}…{elev.max():.0f} m；起伏 p50/p90 = "
                  f"{np.percentile(relief, 50):.0f}/{np.percentile(relief, 90):.0f} m")
            np.save(os.path.join(OUT, F_ELEV), elev.astype(np.int16))
            np.save(os.path.join(OUT, F_RELIEF), relief.astype(np.int16))
        else:
            print(f"  ! 未找到 {ETOPO}；地形退化到「只有海陆两档」", file=sys.stderr)
            elev = np.where(land, 50.0, -1.0).astype(np.float32)
            relief = np.zeros((H, W), np.float32)
        veg = water = None
        if not args.no_veg:
            veg, water = TR.veg_from_landcover(
                W, H, cell, LON0, LON1, LAT0, LAT1,
                LC100_RAW, LC100_TIF, os.path.join(OUT, F_VEG), use_raw=args.raw_lc100,
                water_path=os.path.join(OUT, F_WATER))
            if veg is not None:
                share = float((veg != TR.VEG_UNKNOWN).mean())
                show = ((T_GRASS, "草原"), (T_FARM, "农田聚落"), (TR.CAND_FOREST, "森林"),
                        (TR.CAND_BARE, "裸地"))
                print(f"  覆盖层覆盖 {share * 100:.1f}% 像元（" +
                      "，".join(f"{nm} {int((veg == t).sum()):,}" for t, nm in show) + "）")
                print(f"  水体占比层：≥{TR.WATER_PCT}% 的格 {int((water >= TR.WATER_PCT).sum()):,}"
                      f"（含海洋与湖泊；不是既有水面的碎水见下面「碎水补面」那行）")
        # v3：classify 出**两张**——覆盖（高 4 位）与形态（低 4 位）。两轴谁也不吃谁，
        # 于是"高原上的草原/农田"第一次存得下来（见 adr/0007）。
        terrain, form = TR.classify(elev, relief, veg, land)

        # 柯本气候类 → 两个轴（热量带 × 干湿），并**出产品层** `气候编码.png`。
        # v1 这里只是中间层（判沙漠用），v2 升格为产品层：地形表把气候那一半交还给了它
        # （沙漠/苔原/雨林/针叶/阔叶都不再存储，改由「覆盖 × 气候」派生，见 ADR 0006）。
        # 码 = 热量带 × 8 + 干湿（0..31）。**海洋格上的气候码无意义**（恒 0），读取方一律
        # 先看覆盖层是不是水。
        klim = heat = moist = None
        if not args.no_veg:
            klim = CL.koppen_from_zip(W, H, cell, LON0, LAT1, KOPPEN_ZIP,
                                      cache_path=os.path.join(OUT, F_CLIMATE),
                                      reuse_cache=True)
            if klim is not None:
                arid = np.isin(klim, CL.ARID)
                # **先补洞**（柯本把水体与冰盖 mask 成 nodata，而 NE 说那是陆；不补就会把
                # 阿拉斯加 58°N 读成寒带——这条是断言第 4 条逼出来的，见 assert_contract）。
                klim, _n_hole = CL.fill_land_nodata(klim, land, log=print)
                heat, moist = CL.axes(klim, LAT)
                kod = CL.pack(heat, moist)
                Image.fromarray(kod, "L").save(os.path.join(OUT, F_CLIM), optimize=True)
                print(f"  气候层（柯本）：{CL.summarise(klim, 4)}")
                print(f"    干旱气候（BWh/BWk/BSh/BSk）{int(arid.sum()):,} 格"
                      f"（占全图 {arid.mean() * 100:.1f}%）")
                print("    热量带：" + "，".join(
                    f"{nm} {int((heat == i).sum()):,}" for i, nm in enumerate(CL.HEAT_NAMES)))
                print("    干湿：" + "，".join(
                    f"{nm} {int((moist == i).sum()):,}"
                    for i, nm in enumerate(CL.MOIST_NAMES) if (moist == i).any()))
                print(f"    {F_CLIM} 已出（码 = 热量带 × 8 + 干湿，0..31）")

        def burn(feats, value, label, buf=0.0, filt=None, only_from=None, only_veg=None):
            """only_from：只允许覆盖这些**既有地形类**；only_veg：只允许覆盖这些**土地覆盖候选**。
            后者才是"形状由 LC100 定"的正解 —— 按 LC100 判形状，不管当前是裸地还是高原
            （戈壁在海拔规则下先是「高原」，若按地形类过滤就轮不到它变沙漠）。"""
            hit = 0
            for g, rec in feats:
                if filt and not filt(rec):
                    continue
                if buf:
                    g = g.buffer(buf)
                g = g.buffer(0)
                if g.is_empty:
                    continue
                for gg in wraps(g):
                    c0, c1, r0, r1 = bbox_cells(gg, cell, W, H)
                    if c1 <= c0 or r1 <= r0:
                        continue
                    xs, ys = LON[r0:r1, c0:c1].ravel(), LAT[r0:r1, c0:c1].ravel()
                    from shapely import contains_xy
                    m = contains_xy(gg, xs, ys).reshape(r1 - r0, c1 - c0)
                    m &= land[r0:r1, c0:c1].astype(bool)      # 掩膜只在陆地上生效
                    if only_from is not None:
                        m &= np.isin(terrain[r0:r1, c0:c1], np.asarray(only_from, np.uint8))
                    if only_veg is not None:
                        m &= np.isin(veg[r0:r1, c0:c1], np.asarray(only_veg, np.uint8))
                    if m.any():
                        terrain[r0:r1, c0:c1][m] = value
                        hit += 1
            print(f"  {label}：命中 {hit} 个面")

        def burn_lines(feats, value, label):
            """把**折线**按格点燃（河这类线状要素用这个，不要用上面的 burn）。

            为什么不能用 burn：`contains_xy` 只测**格心**，而 `buf=cell*0.55` 只有约一格宽，
            于是河线在栅格里是一串"只靠对角相连"的单格。实测（修之前）：全图 64,900 个
            河流格，按 **4 邻接碎成 6,834 段**，允许对角才 260 段——差 26 倍。屏幕上就是断流：
            对角相邻的两格在缩小后会被点采样整个丢掉（`render.js` 的地形层是最近邻）。

            这里改成沿折线走 **supercover**：相邻顶点之间按 ≤1 格的步长采样，
            遇到"横纵同时跨一格"的对角步就补一格正交格。于是结果**保证 4 邻接连通**，
            而宽度仍是 1 格——只把断口接上，不改河的粗细。
            """
            mask = np.zeros((H, W), dtype=bool)

            def walk(x0, y0, x1, y1):
                dx, dy = x1 - x0, y1 - y0
                n = int(np.ceil(max(abs(dx), abs(dy)))) + 1
                px = py = None
                for i in range(n + 1):
                    t = i / n
                    cx, cy = int(np.floor(x0 + dx * t)), int(np.floor(y0 + dy * t))
                    if 0 <= cx < W and 0 <= cy < H:
                        mask[cy, cx] = True
                        if px is not None and abs(cx - px) == 1 and abs(cy - py) == 1:
                            mask[py, cx] = True        # 对角步补一格 → 4 邻接
                    px, py = cx, cy

            nline = 0
            for g, rec in feats:
                for gg in wraps(g):
                    for part in getattr(gg, "geoms", [gg]):
                        if part.geom_type != "LineString":
                            continue
                        co = list(part.coords)
                        nline += 1
                        for (ax, ay), (bx, by) in zip(co, co[1:]):
                            walk((ax - LON0) / cell, (LAT1 - ay) / cell,
                                 (bx - LON0) / cell, (LAT1 - by) / cell)
            # **不裁陆地掩膜**：河口（长江江阴以下）在 NE 陆地面与 LC100 里都被判成海，
            # 一裁就把入海段抹掉。河线的两端本来就在海岸/河口，不需要这层保护；
            # 真正该防的是"整段跑到外海"，那条由 T_RIVER 与海洋收口的配合兜（见下面 ocean 收口）。
            terrain[mask] = value
            print(f"  {label}：{nline} 条折线 → {int(mask.sum())} 格")

        # Natural Earth 在这条管线里现在只剩一件事：**水与冰**（湖泊 / 河流 / 冰川）——
        # 那是物理事实，土地覆盖产品分不了这么细。
        #   · **高原与山脉不再烧**：那是地理区划的手绘椭圆块（一条条褐色团），形态交给
        #     高程 + 格内极差（terrain.landform），出来的是真实山系。
        #   · **荒漠不再用 NE 的手绘沙漠面**（2026-10-08 改，需求方报"沙漠边界太平滑"）。
        #     老做法是「NE 沙漠面内 ∧ LC100 裸地 → 沙漠」，可那个面**仍是掩膜**：面内的边
        #     是 LC100 的，**外轮廓与交界仍是 NE 的**。实测那条缝外侧 25.5% 仍是 LC100 裸地
        #     （同一片裸地被切成两半），最长一段 207 km 笔直。改用**气候**当判据之后，
        #     荒漠/绿洲的每一条边都来自数据（100 m 土地覆盖 或 1 km 气候分类）。
        #   · **苔原整段删除**（v2）：它是 `草原 ∧ 寒带`，在显示层派生，不再存储
        #     ——`设计笔记03` §14.12 那个"苔原走 NE 手绘面还是柯本 ET"的悬案随之结案。
        # 详见 tools/climate.py、tools/display_class.py 与 `设计笔记03` §14.11。
        REG = ne_features(NE_REGIONS)
        # **覆盖里那三类要靠气候与海岸才判得出来**：荒漠 / 绿洲 / 滩涂。
        if klim is not None and veg is not None:
            arid = np.isin(klim, CL.ARID)
            # 荒漠 = 干旱气候 ∧ LC100 裸地（码 60）∧ 海拔上限。
            # **海拔上限**是踩出来的：柯本把羌塘/阿里（4700–5300 m）也判成 BWk/BSk，于是
            # 整片青藏高原成了荒漠——需求方看图报的正是这个。实测各荒漠区的海拔：戈壁
            # p99 2131 / max 3024、塔里木盆底 ~1200、撒哈拉 319、阿拉伯 519、伊朗 1125；
            # 羌塘 p50 4740。中间 3200–4300 m 是空的，所以这条线画在 3500 m：戈壁/柴达木
            # （p50 2938）留得住，羌塘/昆仑（3600+）留给「高原/山地」。
            dry = arid & (veg == TR.CAND_BARE) & land.astype(bool) & (elev < WASTE_MAX_ELEV)
            terrain[dry] = T_WASTE
            # 绿洲 = 干旱气候 ∧ LC100 可耕地（40/50）。现代灌溉带的形状就是古绿洲带：
            # 实测 73,749 格，落在印度河、尼罗河、两河、塔里木南缘、河西走廊。
            # 绿洲 = **真沙漠气候**（BWh/BWk）∧ LC100 可耕地（40/50）。
            # ⚠️ 这里只能用 DESERT，不能用 ARID：华北平原在柯本里是 **BSk**（冬干、年降水
            # 约 550 mm），用 ARID 就会把中国最著名的一片农田判成「绿洲」——`check_terrain`
            # 的华北平原那一条第一次跑就抓到了这个。改成"真沙漠气候"之后，留下的正是
            # 需要灌溉才种得活的地方：印度河下游、尼罗河、两河、塔里木南缘、河西走廊。
            oasis = np.isin(klim, CL.DESERT) & (veg == T_FARM) & land.astype(bool)
            terrain[oasis] = T_OASIS
            print(f"  荒漠（LC100 裸地 ∧ 柯本干旱 ∧ 海拔 < {WASTE_MAX_ELEV:.0f} m）："
                  f"{int(dry.sum()):,} 格")
            print(f"  绿洲（LC100 农田 ∧ 柯本真沙漠 BWh/BWk）：{int(oasis.sum()):,} 格")
        elif veg is not None:
            print("  ! 无柯本气候：荒漠/绿洲跳过（否则会把草原盖成荒漠）")
        burn(ne_features(NE_GLACIATED), T_ICE, "冰川")
        burn(ne_features(NE_LAKES), T_LAKE, "湖泊")
        # ⚠️ 「盐沼 / 滩涂」**不在这里**判：它们必须等河流那一段跑完（否则会把河口
        # 抢走），见下面 `cleanup_river_specks` 之后的那一段。
        was_lake = terrain == T_LAKE
        # 河流：**HydroRIVERS（主）+ Natural Earth（兜）取并集**。
        # 为什么换：NE 的河流层全库 1,473 个要素，长江入海段（江阴→崇明，约 230 km）
        # 一条线都没有（最近的 NE 河线离江阴 81 km）——需求方看到的"还是断的"就是这处。
        # 那是**覆盖度**问题，缩小像元救不了：空的地方再细也是空的。
        # HydroRIVERS 光亚洲片就 1,428,959 条河段，上下游共用节点，天然接得上。
        # NE 留着兜非洲/阿拉伯/美洲（本管线只下了四片 HydroRIVERS，见 rivers.REGIONS）。
        before_rivers = terrain.copy()          # 去散点时还原用（覆盖 12 类，9.4 MB，便宜）
        hr_files = [hydro_rivers(z) for z in RV.REGIONS]
        if any(os.path.exists(p) for p in hr_files):
            RV.burn_hydrorivers(terrain, T_RIVER, cell, LON0, LAT1, hr_files,
                                min_cms=args.river_min, log=print)
        else:
            print(f"  ! 没有 HydroRIVERS（{RV.REGIONS}），河流退回只有 NE 那一层", file=sys.stderr)
        # NE 用"按折线点燃"而不是 burn：折线要**保证 4 邻接连通**，否则缩小时断流（见 burn_lines）
        burn_lines(ne_features(NE_RIVERS), T_RIVER, "NE 河流（兜底并集）")
        # 碎水补面：**逐格取众数会把"碎成几块的水"藏起来**。实测长江口有格 45% 是水像素
        # （80/200 各占一部分），可单一类最多的是农田（LC100 40），取众数就记成「平原」——
        # 于是河到 119.6°E 就"断"了，之后 230 km 的入海段整片是陆地色。
        # 修法：水体占比 ≥ WATER_PCT 且**与既有水面 4 邻接**的格补成水面（河流）。
        # 加"邻接"是为了不动海岸线：孤立的 30% 水格（滩涂、灌溉水田）不该变成河。
        # 做法是"只灌与既有水相连的那一部分"——先按候选 ∪ 既有水做 4 邻接连通块，
        # 丢掉不含既有水的块，再把剩下的候选格点亮。
        if water is not None:
            from scipy import ndimage
            is_water = np.isin(terrain, (T_OCEAN, T_LAKE, T_RIVER))
            # **只灌"离真河 ≤3 格"的碎水格**（v3 收紧）。原先的条件是"与任何水面 4 邻接"，
            # 海也算——于是整条海岸线被镶了一圈假河、小岛整块变河（实测补出 23,166 格里
            # 16,105 格 8 邻接海洋、13,907 格 LC100 明说那是开阔海）。改成按到真河的**距离**
            # 之后：三角洲与河口照样连通（它们本来就紧贴河道），海岸光晕消失——那批格改判
            # 「盐沼/滩涂」（见下面那一段）。
            near_riv = ndimage.distance_transform_edt(terrain != T_RIVER) <= 3.5
            cand = (water >= TR.WATER_PCT) & ~is_water & near_riv
            if cand.any():
                seed = is_water | cand
                lab = ndimage.label(seed, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))[0]
                keep = np.unique(lab[is_water & (lab > 0)])
                fill = cand & np.isin(lab, keep)
                terrain[fill] = T_RIVER
                print(f"  碎水补面：占比 ≥{TR.WATER_PCT}% 且离真河 ≤3 格的 {int(cand.sum()):,}，"
                      f"其中与水面相连的 {int(fill.sum()):,} 补成河流"
                      f"（河口/三角洲/辫状河；离河远的海岸湿格归盐沼/滩涂）")
        # **湖面赢**：河网里有"湖心线"（HydROSHEDS/NE 都把水流路径画过湖），那是流向记录
        # 不是地表河。让它盖掉湖面，贝加尔湖心就成了一条河（check_terrain 抓到了）。
        # 河穿湖本来就是河→湖→河，颜色一变不是"断"。
        if was_lake.any():
            back = int((was_lake & (terrain != T_LAKE)).sum())
            terrain[was_lake] = T_LAKE
            if back:
                print(f"  湖面优先：把被河线盖掉的 {back:,} 格湖面还回来")
        # 封缝放在**湖面还原之后**：还原会把河在湖岸处切成两段，再封才能把
        # "河→1 格湖→河"这种查出来的断口接上（反过来做，桥刚封上就被还原成湖）。
        seal_river_gaps(terrain, T_RIVER, (T_OCEAN, T_LAKE), log=print)
        # 连对角放在封缝之后、去散点之前：先把角接触补成正交，合并后的段才不会被当作小段丢掉。
        connect_diagonal_rivers(terrain, T_RIVER, log=print)
        # 去散点放在**湖面还原之后**：还原会把河段切碎，先清会留下新的小段（实测 880 个孤点）。
        cleanup_river_specks(terrain, before_rivers, T_RIVER, RIVER_MIN_CELLS, log=print)

        # **盐沼 / 滩涂**（v3 新增。**放在河流之后**：先让河流拿走河口与三角洲，
        # 剩下的沿海湿格才是潮滩——顺序反了就会把河口抢走，长江口那样）。
        # 两者都是湿地，差别只在**有没有植被**，而这在 LC100 里是分得开的：
        #   · 草本湿地（码 90）贴海 = 有植被 → **盐沼**（碱蓬/芦苇/米草那一类）
        #   · 格内水占比 ≥30% 的光泥滩  → **滩涂**
        if veg is not None and water is not None:
            from scipy import ndimage as _nd
            sea8 = _nd.binary_dilation(land == 0, np.ones((3, 3), bool))
            beach = land.astype(bool) & sea8
            saltm = beach & (veg == T_MARSH)
            terrain[saltm] = T_SALTM
            mud = (beach & (water >= TR.WATER_PCT) & (terrain != T_SALTM)
                   & ~np.isin(terrain, (T_OCEAN, T_LAKE, T_RIVER)))
            terrain[mud] = T_TIDAL
            print(f"  盐沼（LC100 草本湿地 ∧ 贴海，有植被）：{int(saltm.sum()):,} 格")
            print(f"  滩涂（格内水占比 ≥{TR.WATER_PCT}% ∧ 贴海，光泥滩）：{int(mud.sum()):,} 格")
    # 海洋口径收口：陆地掩膜的补集。**但河线穿过的格子不算海** —— 长江江阴以下的入海段
    # 在 NE 陆地面与 LC100 里都是 200（开阔海），若一律按掩膜收口，刚补上的入海段会被
    # 重新抹成海洋，等于白换数据源。判据只看 `terrain == T_RIVER`（只有河烧伤它），
    # 所以不会把任何真海格变成陆地。见 tools/rivers.py。
    terrain[(land == 0) & (terrain != T_RIVER)] = T_OCEAN
    # 内海 / 大湖：里海、贝加尔、死海、五大湖在 Natural Earth 里属于"海洋层"（不在湖泊层），
    # 光靠 NE 会把它们记成「海洋」。LC100 自己分得很干净 —— 内陆水体是 80、开阔海是 200
    # （实测：里海/贝加尔/鄱阳/青海湖/死海/五大湖 = 80；渤海/黄海/南海/地中海/红海/日本海 = 200），
    # 所以直接采信它：被算成海、但 LC100 说是"内陆水体"的格子，改记湖泊。
    if veg is not None:
        inland = (terrain == T_OCEAN) & (veg == TR.C_LAKE)
        if inland.any():
            terrain[inland] = T_LAKE
            print(f"  内海/大湖：{int(inland.sum())} 格由海洋改记湖泊（LC100 内陆水体）")
    Image.fromarray(TR.pack(terrain, form), "L").save(os.path.join(OUT, F_TERRAIN),
                                                     optimize=True)

    # ---------------- 参考层：矢量顶点（不再是栅格掩膜） ----------------
    tang = tang_rings(cell)
    ref_info = build_ref_vector(units, k, cell, LON0, LAT1, tang, os.path.join(OUT, F_REFV))

    counts = np.bincount(terrain.ravel(), minlength=len(TERRAIN_LEGEND))
    ratio = {TERRAIN_LEGEND[i]: round(int(c) / terrain.size, 4)
             for i, c in enumerate(counts) if c}
    fcounts = np.bincount(form.ravel(), minlength=len(FORM_LEGEND))
    form_ratio = {FORM_LEGEND[i]: round(int(c) / form.size, 4)
                  for i, c in enumerate(fcounts) if c}
    # **数据契约断言**放在落盘之前（ADR 0006）：4 位覆盖、14 位地块、8 位块区局部码，
    # 余量都不大，而"余量用尽"的后果是静默截断——宁可让管线在这一步红掉。
    from display_class import entries as _disp_entries, note as _disp_note
    assert_contract(terrain, form, plot_id, districts, heat, moist, klim, LAT, land, log=print)
    write_runtime(terrain, form, plot_id, dist_local, heat, moist, W, H, cell,
                  os.path.join(os.path.dirname(OUT), "运行态"), log=print)
    # 底图指纹：写进台账，也写进 data.js。import_editor 要靠它判断草稿是否基于旧底图
    # （工单 §3.3、§4.2 第 2 步），所以必须在 meta 落盘**之前**算出来。
    base_tag = make_base_tag(cell, W, H, len(seeds), covered,
                             [s["n"] for s in seeds], TERRAIN_LEGEND)
    meta = {
        "grid": {"lon0": LON0, "lon1": LON1, "lat0": LAT0, "lat1": LAT1, "cell": cell,
                 "w": W, "h": H,
                 "note": "经度折回连续（>180 为日界线以东）；行序自北向南"},
        "cover_legend": {str(i): n for i, n in enumerate(TERRAIN_LEGEND)},
        "form_legend": {str(i): n for i, n in enumerate(FORM_LEGEND)},
        "cover_ratio": ratio,
        "form_ratio": form_ratio,
        "plot_id_encoding": "R + G*256（0 = 无地块）",
        "dist_id_encoding": "8 位灰度 = **地块内的局部序号**（0 = 无块区）；全局块区 id 见台账 districts 的 (plot, local)",
        "terrain_encoding": "8 位灰度 = 覆盖（高 4 位）× 16 + 形态（低 4 位）；解包见 tools/terrain.py 的 unpack（docs/adr/0007）",
        "land_rule": "陆地 = Natural Earth 10m 陆地 ∪ 湖泊 ∪ 冰川区（格心命中）；"
                     "地形层的「海洋」是该掩膜的补集，地块层也被它裁过",
        "cover_rule": "覆盖 = LC100 土地覆盖（森林/草原/平原）＋ 由气候与海岸判出的三类："
                      "荒漠 = 裸地 ∧ 干旱 ∧ 海拔 < 3500 m；绿洲 = 可耕地 ∧ 干旱；"
                      "滩涂 = LC100 湿地 ∧ 贴海。**沙漠/苔原不存储**，由「覆盖 × 气候」派生"
                      "（见 ADR 0006）",
        "climate_rule": "气候 = 柯本两轴：热量带（热带/亚热带/温带/亚寒带，B 组按 |lat| ≤ 23.5 补刀）"
                        "× 干湿（干旱/半干旱/冬干/冬雨/夏雨/季风/常湿）。**寒带不占热量带取值**，"
                        "由干湿码 0 表示；海洋格上的气候码无意义",
        "display_rule": _disp_note(),
        "river_rule": "河流 = HydroRIVERS v1.0（流量 ≥ 默认 100 m³/s）∪ Natural Earth 河线，"
                      "按 supercover 逐格点燃（4 邻接连通）；再补「水体占比 ≥ 30% 且与水面相连」"
                      "的碎水格（河口/三角洲，逐格众数会把它们藏成陆地）。河线穿过的格不算海洋",
        "water_rule": TR.water_frac_note(),
        "climate": {"source": "Beck et al. 2023, Scientific Data 10:724（CC BY 4.0）",
                    "member": CL.KOPPEN_MEMBER,
                    "grid": "1 km（0.00833333°），现值期 1991–2020",
                    "arid": list(CL.ARID),
                    "heat_names": list(CL.HEAT_NAMES),
                    "moist_names": list(CL.MOIST_NAMES),
                    "encoding": "热量带 × 8 + 干湿（0..31）；干湿 = 0 读作寒带"},
        "ref_encoding": "参考顶点.bin：ZLRV1 魔数 + 环表 + 格坐标×8 的 uint16 顶点对",
        "base_tag": base_tag,
        "districts": districts,
        "block_rule": "块区 = 地块的下一级行政单元（中华＝县；世界暂无二级，每地块 1 个占位）。"
                      "与地块层在同一个 contains_xy 循环里写出，故块区必然落在其声明地块内；"
                      "管线只出底稿，定稿在编辑器里改",
        "counts": {"units": len(units), "plots": len(seeds), "covered_cells": covered,
                   "covered_before_mask": covered_raw, "land_cells": int(land.sum())},
        "ref": ref_info,
        # domain 由编辑器日后指派（工单 §4.1）：这里先留空串，字段必须在，
        # 否则 import_editor 合入时"有/无该键"两种形状混进同一份台账。
        "plots": [{"id": i + 1, "name": s["n"], "domain": ""} for i, s in enumerate(seeds)],
    }
    with open(os.path.join(OUT, F_META), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    for fn in (F_PLOT, F_TERRAIN, F_CLIM, F_DIST, F_REFV, F_META):
        p = os.path.join(OUT, fn)
        print(f"  {fn:<16}{os.path.getsize(p) / 1048576:6.2f} MB")
    print("地形占比:", ratio)

    # ---------------- 输出：编辑器读的那份 data.js ----------------
    # **图不再拷给编辑器**：真源只有 地图数据/栅格/ 一处（见 docs/adr/0002），
    # 编辑器由 serve.py 的 /数据/ 虚拟挂载去读它。这里只写它要的 js/data.js。
    from build_editor import load_palette
    from editor_data import write_data_js
    pal = load_palette()
    APP = os.path.join(ROOT, "地图", "地图编辑器")
    # 上一代把参考层烧成 县界参考.png 的产物已废弃：留着只会让人以为它还在用
    stale = os.path.join(OUT, "县界参考.png")
    if os.path.exists(stale):
        os.remove(stale)
        print(f"  已删除废弃产物 {os.path.relpath(stale, ROOT)}")
    # 旧版编辑器副本目录：ADR 0002 之后不该再存在，顺手清掉（否则它又变成第二份真源）
    old_copy = os.path.join(APP, "data")
    if os.path.isdir(old_copy):
        shutil.rmtree(old_copy)
        print(f"  已删除编辑器副本 {os.path.relpath(old_copy, ROOT)}（真源唯一，见 docs/adr/0002）")

    payload = {
        "grid": meta["grid"], "cover_legend": TERRAIN_LEGEND, "form_legend": FORM_LEGEND,
        "climate_legend": {"heat": list(CL.HEAT_NAMES), "moist": list(CL.MOIST_NAMES),
                           "encoding": "热量带 × 8 + 干湿（0..31）；干湿 = 0 读作寒带",
                           "note": meta["climate_rule"]},
        "display_classes": _disp_entries(),
        "plots": meta["plots"], "palette": pal,
        "domains": [{"g": g["geo"], "d": d} for g in pal for d in g["domains"]],
        "districts": districts,
        "block_rule": "块区 = 地块的下一级行政单元（中华＝县；世界暂无二级，每地块 1 个占位）。"
                      "与地块层在同一个 contains_xy 循环里写出，故块区必然落在其声明地块内；"
                      "管线只出底稿，定稿在编辑器里改",
        "base_tag": base_tag,
        "land_rule": meta["land_rule"],
    }
    p = write_data_js(payload, APP)
    print(f"  {os.path.relpath(p, ROOT)}"
          f"（图走 {URL_PREFIX} 虚拟挂载 → 地图数据/栅格/）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
