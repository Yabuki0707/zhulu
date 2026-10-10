# -*- coding: utf-8 -*-
"""高程与覆盖 —— 生成流程的第 2 步。

本文件由 `_拆分.py` 从原来的单坨 `生成.py` **逐字搬**出来，只做了两件机械事：
缩进回退 4 格、跨阶段的状态名换成 `ctx.xxx`。**改判据要连着 `管线.py` 的阶段表一起看**
（顺序即语义：后一步压前一步）。
"""
from __future__ import annotations

from __future__ import annotations

import numpy as np
import os
import sys

from mapdata import DUNE_ZIP
from mapdata import ETOPO_TIF as ETOPO
from mapdata import GLWD1_ZIP
from mapdata import GLWD3_ADF
from mapdata import LC100_RAW
from mapdata import LC100_TIF
from mapdata import VOLCANO_GEOJSON
import glwd as GL
import ice as IC
import mapdata as MD
import sanddunes as SD
import terrain as TR
import volcano as VO

from 契约 import (
    F_DUNE, F_ELEV, F_ICE, F_LAKEPOLY, F_PAN, F_RELIEF, F_SALINE, F_VEG, F_VOLC, F_WATER, LAT0,
    LAT1, LON0, LON1, OUT, T_DENSE, T_FARM, T_GRASS, T_GRAVEL, T_OPEN, T_SAND, T_SHRUB,
    T_TUNDRA,
)


def run(ctx) -> None:
    """跑这一步。日志走 `ctx.log`（界面上是实时日志框）。"""
    if os.path.exists(ETOPO):
        print("读 ETOPO 高程（一次读取，裁到本图范围）…")
        ctx.高程, ctx.起伏 = TR.read_elevation(ETOPO, LON0, LON1, LAT0, LAT1, ctx.W, ctx.H)
        print(f"  高程 {ctx.高程.min():.0f}…{ctx.高程.max():.0f} m；起伏 p50/p90 = "
              f"{np.percentile(ctx.起伏, 50):.0f}/{np.percentile(ctx.起伏, 90):.0f} m")
        # ⚠️ **存 float32，别存 int16**：这两个数组的用途是"改形态门槛时不必重读 ETOPO"，
        # 而门槛判据正是 `起伏 > 350` 这种硬比较 —— int16 取整会把 350.4 存成 350，
        # 于是在阈值附近**翻掉约 0.2% 的格**（实测 6,497 格），拿缓存重算的人会看到
        # 与栅格对不上的假警报。多占 37 MB，换掉这个坑。
        np.save(os.path.join(OUT, F_ELEV), ctx.高程.astype(np.float32))
        np.save(os.path.join(OUT, F_RELIEF), ctx.起伏.astype(np.float32))
    else:
        print(f"  ! 未找到 {ETOPO}；地形退化到「只有海陆两档」", file=sys.stderr)
        ctx.高程 = np.where(ctx.陆地, 50.0, -1.0).astype(np.float32)
        ctx.起伏 = np.zeros((ctx.H, ctx.W), np.float32)
    ctx.植被 = ctx.水体 = None
    if not ctx.参数.no_veg:
        ctx.植被, ctx.水体 = TR.veg_from_landcover(
            ctx.W, ctx.H, ctx.参数.cell, LON0, LON1, LAT0, LAT1,
            LC100_RAW, LC100_TIF, os.path.join(OUT, F_VEG), use_raw=ctx.参数.raw_lc100,
            water_path=os.path.join(OUT, F_WATER))
        if ctx.植被 is not None:
            share = float((ctx.植被 != TR.VEG_UNKNOWN).mean())
            show = ((T_GRASS, "草原"), (T_DENSE, "密林"), (T_OPEN, "疏林"),
                    (T_SHRUB, "灌丛"), (T_TUNDRA, "苔原"), (T_SAND, "沙质裸地"),
                    (T_FARM, "耕地聚落→草甸"))
            print(f"  覆盖层覆盖 {share * 100:.1f}% 像元（" +
                  "，".join(f"{nm} {int((ctx.植被 == t).sum()):,}" for t, nm in show) + "）")
            print(f"  水体占比层：≥{TR.WATER_PCT}% 的格 {int((ctx.水体 >= TR.WATER_PCT).sum()):,}"
                  f"（含海洋与湖泊；不是既有水面的碎水见下面「碎水补面」那行）")
    # v3：classify 出**两张**——覆盖（高 4 位）与形态（低 4 位）。两轴谁也不吃谁，
    # 于是「高原 ∧ 草原」「高原 ∧ 草甸」第一次存得下来（见 adr/0007）。
    ctx.地形, ctx.形态 = TR.classify(ctx.高程, ctx.起伏, ctx.植被, ctx.陆地)

    # **沙／砾 拆分**（v7，`adr/0012`）：LC100 60 只给出"裸地"这个笼统类，材质由 GSDP30 的
    # 「有沙占比」定。这一层必须在**其它覆盖写上去之前**做（绿洲/盐沼/滩涂/河湖冰都与它无关，
    # 但顺序清楚一点省得将来打架）。
    if not ctx.参数.no_veg:
        dune = SD.read_sand_fraction(ctx.W, ctx.H, ctx.参数.cell, LON0, LAT1, DUNE_ZIP,
                                     cache_path=os.path.join(OUT, F_DUNE))
        if dune is not None:
            bare = ctx.地形 == T_SAND
            is_sand = bare & (dune != SD.NODATA) & (dune >= TR.SAND_PCT)
            ctx.地形[bare & ~is_sand] = T_GRAVEL
            n_unk = int((bare & (dune == SD.NODATA)).sum())
            print(f"  材质（GSDP30 有沙占比 ≥ {TR.SAND_PCT}% 才读作沙）："
                  f"沙质裸地 {int(is_sand.sum()):,} 格，砾质裸地 "
                  f"{int((ctx.地形 == T_GRAVEL).sum()):,} 格"
                  + (f"（其中 {n_unk:,} 格 GSDP30 无数据，按砾质算 —— 裸地多数是砾）"
                     if n_unk else ""))
            if not is_sand.any():
                print("  ! 一格沙都没有：GSDP30 可能没取到，检查 "
                      "地图/栅格地形数据生成器/fetch_map_data.py --group soil")

    # **v9 的四个新层**（`adr/0014`）：都在**其它覆盖写上去之前**读好，应用放到各自的
    # 位置（盐漠/咸水湖/火山在派生类那一段，海冰必须等"海洋收口"之后）。
    if not ctx.参数.no_veg:
        ctx.盐盘 = GL.salt_pan_fraction(ctx.W, ctx.H, ctx.参数.cell, LON0, LAT1, GLWD3_ADF,
                                   cache_path=os.path.join(OUT, F_PAN))
        ctx.闭合盆地 = GL.saline_lakes(ctx.W, ctx.H, ctx.参数.cell, LON0, LAT1, GLWD1_ZIP,
                                 cache_path=os.path.join(OUT, F_SALINE))
        ctx.湖面 = GL.lake_polygons(ctx.W, ctx.H, ctx.参数.cell, LON0, LAT1, GLWD1_ZIP,
                                    cache_path=os.path.join(OUT, F_LAKEPOLY))
        ctx.火山点 = VO.read_volcanoes(ctx.W, ctx.H, ctx.参数.cell, LON0, LAT1, VOLCANO_GEOJSON,
                                 cache_path=os.path.join(OUT, F_VOLC))
        ctx.海冰层 = IC.read_sea_ice(ctx.W, ctx.H, ctx.参数.cell, LON0, LAT1, MD.ice_zips(),
                               cache_path=os.path.join(OUT, F_ICE))
    else:
        ctx.盐盘 = ctx.闭合盆地 = ctx.火山点 = ctx.海冰层 = ctx.湖面 = None
