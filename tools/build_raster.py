#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成栅格底图：地块 id 栅格 + 块区 id 栅格 + 地形栅格 + 参考顶点矢量。

栅格是全图唯一几何真源，**一一映射**：每个像元恰好一条记录（地块编码 + 块区编码 + 地形）。

    python tools/build_raster.py                     # 默认 cell 0.0625°（1/16°）→ 3376 × 2208
    python tools/build_raster.py --no-veg            # 不读土地覆盖（地形只按高程+掩膜）
    python tools/build_raster.py --raw-lc100         # 裸数组自检通过时用它（否则自动走 TIFF）
    python tools/build_raster.py --no-terrain        # 只出地块层（不等高程）
    python tools/build_raster.py --cell 0.075        # 粗一档（2813 × 1840），体积小约 28%

输入（数据目录：地图/地图数据/）：
  基础单元.json                     由 build_editor.py --dump-units 产出
  原始数据/高程与地表/全球高程_ETOPO_60秒.tif      ETOPO 2022 60s 高程（NOAA，公有领域）
  原始数据/高程与地表/全球土地覆盖_100米.tif       Copernicus LC100 离散分类（森林/雨林等）
  （LC100 的满分辨率裸数组曾在此，2026-10-07 深夜 已删：它是残件。见 #15.3）
  原始数据/自然地球/*.zip                         陆地 / 湖泊 / 冰川 / 具名地貌 / 河流掩膜
  原始数据/唐至明政区/Hartwell_*.zip               参考层的唐 741 州面

输出（地图/地图数据/栅格/）：
  地块编码.png   24 位 RGB，R + G*256 = 地块编码（0 = 无地块）—— 与 P社 province.bmp 同法
  分区编码.png   同上，0 = 无块区；块区隶属于地块 —— 初始全空，由编辑器绘制
  地形编码.png   8 位灰度，值 = 16 类地形编码（见 tools/terrain.py 的 LEGEND）
  参考顶点.bin   **矢量顶点**（现代单元边界 + 唐 741 州面）—— 参考层不再是栅格掩膜
  台账.json      网格几何 / 地形图例 / 陆地口径 / 地块台账
  高程_降采样.npy 起伏_降采样.npy 植被_降采样.npy   中间层（改分类规则时不必重读原图）

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
from geo_wrap import wrap_into                     # noqa: E402
from mapdata import (ROOT, under, UNITS as UNITS_JSON, RASTER, NE_DIR,      # noqa: E402
                     NE_LAND, NE_LAKES, NE_RIVERS, NE_REGIONS, NE_GLACIATED,
                     ETOPO_TIF, LC100_TIF, LC100_RAW, HARTWELL_ZIP, URL_PREFIX)
import terrain as TR                                                    # noqa: E402
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
F_ELEV, F_RELIEF, F_VEG = "高程_降采样.npy", "起伏_降采样.npy", "植被_降采样.npy"

LON0, LON1 = 25.0, 236.0
LAT0, LAT1 = -56.0, 82.0

TERRAIN_LEGEND = TR.LEGEND
(T_OCEAN, T_LAKE, T_RIVER, T_ICE, T_DESERT, T_BARE, T_PLATEAU, T_MOUNTAIN, T_HILL, T_PLAIN,
 T_FOR_NEEDLE, T_FOR_BROAD, T_FOR_RAIN, T_GRASS, T_MARSH,
 T_TUNDRA) = range(len(TERRAIN_LEGEND))


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


def name_tag(seeds) -> str:
    """保留这个名字做兼容（旧调用点），实现已挪到 tools/basetag.py 与 import_editor 共用。"""
    return _bt_name_tag([s["n"] for s in seeds])


def legend_tag() -> str:
    return _bt_legend_tag(TERRAIN_LEGEND)


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
    ap.add_argument("--cell", type=float, default=0.0625,
                    help="像元边长（度）；0.0625° = 1/16° ≈ 6.9 km（0.075° ≈ 8.3 km，粗一档）")
    ap.add_argument("--no-terrain", action="store_true")
    ap.add_argument("--no-veg", action="store_true", help="不读 Copernicus 土地覆盖")
    ap.add_argument("--raw-lc100", action="store_true",
                    help="若裸数组存在且自检通过则用它（那份残件已删，一般用不上）")
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
        if n % 800 == 0:
            print(f"    {n}/{len(order)}")
    covered_raw = int((plot_id > 0).sum())
    # 裁掉压在海洋上的像元：单位面是按容差简化过的，沿海会甩出去几格（还有整片海域算进
    # 行政区的，如三沙那种"海上辖区"）。陆地掩膜是唯一口径，这里一次性对齐。
    plot_id[land == 0] = 0
    covered = int((plot_id > 0).sum())
    print(f"  覆盖 {covered / plot_id.size * 100:.1f}% 像元（其余为无地块）"
          f"；裁掉压在海上的 {covered_raw - covered:,} 格"
          f"（简化容差甩出海岸 + 行政区含海域）")
    blank = len(seeds) - (int(np.unique(plot_id).size) - 1)     # 台账里有、栅格里一格没落到的地块
    print(f"  零像元地块 {blank} 个（小单元落在格心之间 / 只剩海域；编辑器里会标「空」）")
    Image.fromarray(encode_id(plot_id), "RGB").save(os.path.join(OUT, F_PLOT), optimize=True)

    # 块区层：初始为空（0 = 无块区），由编辑器在地块内绘制
    dist_id = np.zeros((H, W), dtype=np.uint16)
    Image.fromarray(encode_id(dist_id), "RGB").save(os.path.join(OUT, F_DIST), optimize=True)

    # ---------------- 地形层（20 类） ----------------
    terrain = np.full((H, W), T_OCEAN, dtype=np.uint8)
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
        veg = None
        if not args.no_veg:
            veg = TR.veg_from_landcover(
                W, H, cell, LON0, LON1, LAT0, LAT1,
                LC100_RAW, LC100_TIF, os.path.join(OUT, F_VEG), use_raw=args.raw_lc100)
            if veg is not None:
                share = float((veg != TR.VEG_UNKNOWN).mean())
                show = tuple(TR.FAM_AFFINITY) + (T_GRASS, T_BARE, T_PLAIN)
                print(f"  植被层覆盖 {share * 100:.1f}% 像元（" +
                      "，".join(f"{TR.FAM_NAMES.get(t) or TR.LEGEND[t]} {int((veg == t).sum())}"
                                for t in show) + "）")
        terrain = TR.classify(elev, relief, veg, land, LAT)   # lat 用于林型的权重制

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

        # Natural Earth 在这条管线里只干两件事：
        #   ① 水体与冰雪（湖泊/河流/冰川）——物理事实，土地覆盖产品分不了这么细；
        #   ② 沙漠/苔原的**细化**——且只允许覆盖"本来就没森林"的类（only_from），
        #      否则会把泰加林盖成苔原、把雨林边缘盖成沙漠。
        # **高原与山脉不再烧**：那是地理区划的手绘椭圆块（一条条褐色团），
        # 形态交给高程 + 格内极差（terrain.landform），出来的是真实山系。
        # 沙漠 / 苔原：**形状由 LC100 定，NE 只当"气候区"标签**。
        # NE 那几个沙漠面是 1:1000 万手绘的（边界几十个顶点），拿它当形状就会画出一大团
        # 光溜溜的椭圆——实测被需求方一眼看出"沙漠过于平滑"。反过来用才对：
        # 在 NE 沙漠区里，只把 LC100 已经判成「裸地」的像元改记「沙漠」，
        # 于是沙漠的每条边都来自 100 米数据（与裸岩、河谷、绿洲咬合），NE 的形状看不见了。
        # 沙漠区里 LC100 说是草/灌丛的边缘，就老实留着草原——半荒漠草原本来就是草原。
        REG = ne_features(NE_REGIONS)
        burn(REG, T_DESERT, "沙漠（NE 沙漠区内，凡 LC100 判「裸地」的格 → 沙漠）",
             filt=lambda r: r.get("FEATURECLA") == "Desert", only_veg=(T_BARE,))
        burn(REG, T_TUNDRA, "苔原（NE 苔原区内，LC100 的裸地/草原/苔藓 → 苔原）",
             filt=lambda r: r.get("FEATURECLA") == "Tundra",
             only_veg=(T_BARE, T_GRASS, T_TUNDRA))
        burn(ne_features(NE_GLACIATED), T_ICE, "冰川")
        burn(ne_features(NE_LAKES), T_LAKE, "湖泊")
        burn(ne_features(NE_RIVERS), T_RIVER, "河流", buf=cell * 0.55)
    terrain[land == 0] = T_OCEAN                  # 海洋口径收口
    # 内海 / 大湖：里海、贝加尔、死海、五大湖在 Natural Earth 里属于"海洋层"（不在湖泊层），
    # 光靠 NE 会把它们记成「海洋」。LC100 自己分得很干净 —— 内陆水体是 80、开阔海是 200
    # （实测：里海/贝加尔/鄱阳/青海湖/死海/五大湖 = 80；渤海/黄海/南海/地中海/红海/日本海 = 200），
    # 所以直接采信它：被算成海、但 LC100 说是"内陆水体"的格子，改记湖泊。
    if veg is not None:
        inland = (terrain == T_OCEAN) & (veg == TR.T_LAKE)
        if inland.any():
            terrain[inland] = T_LAKE
            print(f"  内海/大湖：{int(inland.sum())} 格由海洋改记湖泊（LC100 内陆水体）")
    Image.fromarray(terrain, "L").save(os.path.join(OUT, F_TERRAIN), optimize=True)

    # ---------------- 参考层：矢量顶点（不再是栅格掩膜） ----------------
    tang = tang_rings(cell)
    ref_info = build_ref_vector(units, k, cell, LON0, LAT1, tang, os.path.join(OUT, F_REFV))

    counts = np.bincount(terrain.ravel(), minlength=len(TERRAIN_LEGEND))
    ratio = {TERRAIN_LEGEND[i]: round(int(c) / terrain.size, 4)
             for i, c in enumerate(counts) if c}
    # 底图指纹：写进台账，也写进 data.js。import_editor 要靠它判断草稿是否基于旧底图
    # （工单 §3.3、§4.2 第 2 步），所以必须在 meta 落盘**之前**算出来。
    base_tag = make_base_tag(cell, W, H, len(seeds), covered,
                             [s["n"] for s in seeds], TERRAIN_LEGEND)
    meta = {
        "grid": {"lon0": LON0, "lon1": LON1, "lat0": LAT0, "lat1": LAT1, "cell": cell,
                 "w": W, "h": H,
                 "note": "经度折回连续（>180 为日界线以东）；行序自北向南"},
        "terrain_legend": {str(i): n for i, n in enumerate(TERRAIN_LEGEND)},
        "terrain_ratio": ratio,
        "plot_id_encoding": "R + G*256（0 = 无地块）",
        "dist_id_encoding": "R + G*256（0 = 无块区；块区隶属于地块）",
        "terrain_encoding": "8 位灰度，值 = terrain_legend 的下标（16 类）",
        "land_rule": "陆地 = Natural Earth 10m 陆地 ∪ 湖泊 ∪ 冰川区（格心命中）；"
                     "地形层的「海洋」是该掩膜的补集，地块层也被它裁过",
        "ref_encoding": "参考顶点.bin：ZLRV1 魔数 + 环表 + 格坐标×8 的 uint16 顶点对",
        "base_tag": base_tag,
        "districts": [],
        "counts": {"units": len(units), "plots": len(seeds), "covered_cells": covered,
                   "covered_before_mask": covered_raw, "land_cells": int(land.sum())},
        "ref": ref_info,
        # domain 由编辑器日后指派（工单 §4.1）：这里先留空串，字段必须在，
        # 否则 import_editor 合入时"有/无该键"两种形状混进同一份台账。
        "plots": [{"id": i + 1, "name": s["n"], "domain": ""} for i, s in enumerate(seeds)],
    }
    with open(os.path.join(OUT, F_META), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    for fn in (F_PLOT, F_TERRAIN, F_DIST, F_REFV, F_META):
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
        "grid": meta["grid"], "terrain_legend": TERRAIN_LEGEND,
        "plots": meta["plots"], "palette": pal,
        "domains": [{"g": g["geo"], "d": d} for g in pal for d in g["domains"]],
        "districts": [],
        "base_tag": base_tag,
        "land_rule": meta["land_rule"],
    }
    p = write_data_js(payload, APP)
    print(f"  {os.path.relpath(p, ROOT)}"
          f"（图走 {URL_PREFIX} 虚拟挂载 → 地图数据/栅格/）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
