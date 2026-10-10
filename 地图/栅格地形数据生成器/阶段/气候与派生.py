# -*- coding: utf-8 -*-
"""气候与派生 —— 生成流程的第 3 步。

本文件由 `_拆分.py` 从原来的单坨 `生成.py` **逐字搬**出来，只做了两件机械事：
缩进回退 4 格、跨阶段的状态名换成 `ctx.xxx`。**改判据要连着 `管线.py` 的阶段表一起看**
（顺序即语义：后一步压前一步）。
"""
from __future__ import annotations

from __future__ import annotations

import numpy as np
import os

from PIL import Image
from mapdata import KOPPEN_ZIP
import climate as CL
import glwd as GL
import terrain as TR

from 契约 import (
    F_CLIM, F_CLIMATE, LAT1, LON0, OUT, T_FARM, T_GRAVEL, T_OASIS, T_SALTPAN, T_SAND,
)


def run(ctx) -> None:
    """跑这一步。日志走 `ctx.log`（界面上是实时日志框）。"""
    # 柯本气候类 → 两个轴（热量带 × 干湿），并**出产品层** `气候编码.png`。
    # v1 这里只是中间层（判沙漠用），v2 升格为产品层：地形表把气候那一半交还给了它
    # （沙漠/苔原/雨林/针叶/阔叶都不再存储，改由「覆盖 × 气候」派生，见 ADR 0006）。
    # 码 = 热量带 × 8 + 干湿（0..31）。**海洋格上的气候码无意义**（恒 0），读取方一律
    # 先看覆盖层是不是水。
    ctx.气候类 = ctx.热量带 = ctx.干湿 = None
    if not ctx.参数.no_veg:
        ctx.气候类 = CL.koppen_from_zip(ctx.W, ctx.H, ctx.参数.cell, LON0, LAT1, KOPPEN_ZIP,
                                  cache_path=os.path.join(OUT, F_CLIMATE),
                                  reuse_cache=True)
        if ctx.气候类 is not None:
            arid = np.isin(ctx.气候类, CL.ARID)
            # **先补洞**（柯本把水体与冰盖 mask 成 nodata，而 NE 说那是陆；不补就会把
            # 阿拉斯加 58°N 读成寒带——这条是断言第 4 条逼出来的，见 assert_contract）。
            ctx.气候类, _n_hole = CL.fill_land_nodata(ctx.气候类, ctx.陆地, log=print)
            ctx.热量带, ctx.干湿 = CL.axes(ctx.气候类, ctx.LAT)
            kod = CL.pack(ctx.热量带, ctx.干湿)
            Image.fromarray(kod, "L").save(os.path.join(OUT, F_CLIM), optimize=True)
            print(f"  气候层（柯本）：{CL.summarise(ctx.气候类, 4)}")
            print(f"    干旱气候（BWh/BWk/BSh/BSk）{int(arid.sum()):,} 格"
                  f"（占全图 {arid.mean() * 100:.1f}%）")
            print("    热量带：" + "，".join(
                f"{nm} {int((ctx.热量带 == i).sum()):,}" for i, nm in enumerate(CL.HEAT_NAMES)))
            print("    干湿：" + "，".join(
                f"{nm} {int((ctx.干湿 == i).sum()):,}"
                for i, nm in enumerate(CL.MOIST_NAMES) if (ctx.干湿 == i).any()))
            print(f"    {F_CLIM} 已出（码 = 热量带 × 8 + 干湿，0..31）")

    # **覆盖里这三类是"派生类"**（要气候或海岸才判得出来，已在覆盖表里声明）：绿洲 / 盐沼 / 滩涂。
    if ctx.气候类 is not None and ctx.植被 is not None:
        # 绿洲 = **真沙漠气候**（BWh/BWk）∧ LC100 可耕地（40/50）。
        # ⚠️ 只能用 DESERT，不能用 ARID：华北平原在柯本里是 **BSk**（冬干、年降水约 550 mm），
        # 用 ARID 就会把中国最著名的一片农田判成「绿洲」——`check_terrain` 的华北平原那一条
        # 第一次跑就抓到了这个。改成"真沙漠气候"之后，留下的正是需要灌溉才种得活的地方：
        # 印度河下游、尼罗河、两河、塔里木南缘、河西走廊。
        oasis = np.isin(ctx.气候类, CL.DESERT) & (ctx.植被 == T_FARM) & ctx.陆地.astype(bool)
        ctx.地形[oasis] = T_OASIS
        print(f"  绿洲（LC100 耕地/建成区 ∧ 柯本真沙漠 BWh/BWk）：{int(oasis.sum()):,} 格")
    elif ctx.植被 is not None:
        print("  ! 无柯本气候：绿洲跳过（否则会把真沙漠里的耕地误当绿洲）")
    # **盐漠 / 咸水湖 / 火山**（v9）。三个都只动"已经定了的东西"，不新造无水之地的水。
    if ctx.盐盘 is not None:
        # 盐漠 = 无植被地表（沙质/砾质裸地）∧ GLWD-3 的"盐盘/咸水湿地"占比 ≥ 50%。
        # ⚠️ 已知漏项（`adr/0014`）：GLWD-3 是 2004 年产品，实测**察尔汗、乌斯秋尔特、
        # 卢特、长芦盐场都读成"非湿地"**——所以这一类不会修掉渤海湾那排盐田
        # （那是 LC100 的内陆水体码造成的，另有规则治）。
        sp = np.isin(ctx.地形, (T_SAND, T_GRAVEL)) & (ctx.盐盘 != GL.GLWD3_NODATA)                 & (ctx.盐盘 >= TR.SALT_PCT)
        ctx.地形[sp] = T_SALTPAN
        print(f"  盐漠（GLWD-3 盐盘占比 ≥ {TR.SALT_PCT}% 的裸地）：{int(sp.sum()):,} 格")
        if not sp.any():
            print("  ! 一格盐漠都没有：GLWD-3 可能没取到，检查 地图/栅格地形数据生成器/glwd.py 的缓存")
