# -*- coding: utf-8 -*-
"""陆地与地块 —— 生成流程的第 1 步。

本文件由 `_拆分.py` 从原来的单坨 `生成.py` **逐字搬**出来，只做了两件机械事：
缩进回退 4 格、跨阶段的状态名换成 `ctx.xxx`。**改判据要连着 `管线.py` 的阶段表一起看**
（顺序即语义：后一步压前一步）。
"""
from __future__ import annotations

from __future__ import annotations

import json
import numpy as np
import os
import shapely

from PIL import Image
from mapdata import NE_GLACIATED
from mapdata import NE_LAKES
from mapdata import NE_LAND
from shapely import contains_xy
from 栅格工具 import bbox_cells
from 栅格工具 import encode_id
from 栅格工具 import ne_features
from 栅格工具 import unit_polys
from 栅格工具 import wraps
import terrain as TR

from 契约 import (
    F_DIST, F_PLOT, LAT1, LON0, OUT, UNITS_JSON,
)


def run(ctx) -> None:
    """跑这一步。日志走 `ctx.log`（界面上是实时日志框）。"""
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
    ctx.陆地 = TR.rasterize_union(ctx.LON, ctx.LAT, LON0, LAT1, ctx.参数.cell, land_geoms)
    print(f"  陆地 {ctx.陆地.sum() / ctx.陆地.size * 100:.1f}% 像元（其余为海洋）")

    # ---------------- 地块 id 层 ----------------
    with open(UNITS_JSON, encoding="utf-8") as f:
        d = json.load(f)
    ctx.层级, ctx.单元们, ctx.种子 = d["k"], d["units"], d["seeds"]
    print(f"单元 {len(ctx.单元们)}，种子地块 {len(ctx.种子)}")
    ctx.地块码 = np.zeros((ctx.H, ctx.W), dtype=np.uint16)
    # 块区层（**底稿**）与地块层在**同一个循环**里写：一个单元的像元，地块编码与块区编码
    # 来自同一次 `contains_xy`，天然满足"块区必须落在它声明的地块内"这条硬约束
    # （import_editor 会校验），也省掉第二遍栅格化。这里先写**单元下标**做临时编号，
    # 循环结束后按"有像元的单元"重排成连续的块区编号。
    ctx.块区临时 = np.zeros((ctx.H, ctx.W), dtype=np.uint16)
    order = sorted(range(len(ctx.单元们)), key=lambda i: -ctx.单元们[i]["a"])   # 大面先画，小面压上
    for n, i in enumerate(order, 1):
        g = unit_polys(ctx.单元们[i], ctx.层级)
        c0, c1, r0, r1 = bbox_cells(g, ctx.参数.cell, ctx.W, ctx.H)
        if c1 <= c0 or r1 <= r0:
            continue
        xs, ys = ctx.LON[r0:r1, c0:c1].ravel(), ctx.LAT[r0:r1, c0:c1].ravel()
        from shapely import contains_xy
        m = contains_xy(g, xs, ys).reshape(r1 - r0, c1 - c0)
        ctx.地块码[r0:r1, c0:c1][m] = ctx.单元们[i]["sp"] + 1
        ctx.块区临时[r0:r1, c0:c1][m] = i + 1
        if n % 800 == 0:
            print(f"    {n}/{len(order)}")
    ctx.原始覆盖格数 = int((ctx.地块码 > 0).sum())
    # 裁掉压在海洋上的像元：单位面是按容差简化过的，沿海会甩出去几格（还有整片海域算进
    # 行政区的，如三沙那种"海上辖区"）。陆地掩膜是唯一口径，这里一次性对齐。
    ctx.地块码[ctx.陆地 == 0] = 0
    ctx.块区临时[ctx.地块码 == 0] = 0
    ctx.覆盖格数 = int((ctx.地块码 > 0).sum())
    print(f"  覆盖 {ctx.覆盖格数 / ctx.地块码.size * 100:.1f}% 像元（其余为无地块）"
          f"；裁掉压在海上的 {ctx.原始覆盖格数 - ctx.覆盖格数:,} 格"
          f"（简化容差甩出海岸 + 行政区含海域）")
    ctx.零像元地块 = len(ctx.种子) - (int(np.unique(ctx.地块码).size) - 1)     # 台账里有、栅格里一格没落到的地块
    print(f"  零像元地块 {ctx.零像元地块} 个（小单元落在格心之间 / 只剩海域；编辑器里会标「空」）")
    Image.fromarray(encode_id(ctx.地块码), "RGB").save(os.path.join(OUT, F_PLOT), optimize=True)

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
    present = np.unique(ctx.块区临时)
    present = present[present > 0]
    blk_lut = np.zeros(len(ctx.单元们) + 1, dtype=np.uint16)
    ctx.块区台账 = []
    seen = {}
    for n, ui in enumerate(present, 1):
        blk_lut[int(ui)] = n
        plot = ctx.单元们[int(ui) - 1]["sp"] + 1
        loc = seen.get(plot, 0) + 1
        seen[plot] = loc
        ctx.块区台账.append({"id": n, "name": ctx.单元们[int(ui) - 1]["n"],
                          "plot": plot, "local": loc})
    ctx.块区码 = blk_lut[ctx.块区临时]
    local_of = np.zeros(len(ctx.块区台账) + 1, np.uint8)
    for dd in ctx.块区台账:
        local_of[dd["id"]] = dd["local"]
    ctx.块区局部 = local_of[ctx.块区码]
    del ctx.块区临时
    nogap = int(((ctx.地块码 > 0) & (ctx.块区码 == 0)).sum())
    print(f"  块区底稿 {len(ctx.块区台账):,} 个（中华＝县；世界＝每地块 1 个占位）"
          f"；有地块却没块区的像元 {nogap}（必须为 0）"
          f"；栅格里的**局部序号** 1..{int(ctx.块区局部.max())}")
    assert nogap == 0, "块区必须覆盖每一个有地块的像元"
    # 分区编码.png = 8 位灰度，值 = **地块内的局部序号**（0 = 无块区）。
    Image.fromarray(ctx.块区局部, "L").save(os.path.join(OUT, F_DIST), optimize=True)
