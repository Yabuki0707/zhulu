# -*- coding: utf-8 -*-
"""水与河 —— 生成流程的第 4 步。

本文件由 `_拆分.py` 从原来的单坨 `生成.py` **逐字搬**出来，只做了两件机械事：
缩进回退 4 格、跨阶段的状态名换成 `ctx.xxx`。**改判据要连着 `管线.py` 的阶段表一起看**
（顺序即语义：后一步压前一步）。
"""
from __future__ import annotations

from __future__ import annotations

import numpy as np
import os
import sys

from mapdata import NE_GLACIATED
from mapdata import NE_LAKES
from mapdata import NE_RIVERS
from mapdata import hydro_rivers
from 栅格工具 import cleanup_river_specks
from 栅格工具 import connect_diagonal_rivers
from 栅格工具 import ne_features
from 栅格工具 import seal_river_gaps
from 栅格工具 import 烧线
from 栅格工具 import 烧面
import rivers as RV
import terrain as TR

from 契约 import (
    LAT1, LON0, RIVER_MIN_CELLS, T_ICE, T_LAKE, T_MARSH, T_OCEAN, T_RIVER, T_SALTM, T_TIDAL,
)


def run(ctx) -> None:
    """跑这一步。日志走 `ctx.log`（界面上是实时日志框）。"""
    # Natural Earth 在这条管线里现在只剩一件事：**水与冰**（湖泊 / 河流 / 冰川）——
    # 那是物理事实，土地覆盖产品分不了这么细。
    #   · **高原与山脉不再烧**：那是 Natural Earth 自己的手绘椭圆块（一条条褐色团），
    #     形态交给高程 + 格内极差（terrain.landform），出来的是真实山系。
    #   · **裸地不再靠气候判**（v6 改、v7 再改）：v5 及之前是「LC100 裸地 ∧ 柯本干旱 ∧
    #     海拔<3500 m → 荒漠」，那让「荒漠」成了气候词、还留了 4.5 万格"源数据说是裸露地面、
    #     图上却写着草原"的洞。v6 起**裸地直接来自 LC100 60**，沙漠/戈壁/寒漠由显示层按气候判；
    #     **v7 再把裸地按材质拆成 沙质裸地／砾质裸地**（GSDP30 的有沙占比，见 adr/0012）——
    #     因为「沙漠／戈壁」是**材质**的差别不是气候的差别（塔克拉玛干与蒙古戈壁同属柯本 BWk）。
    #   · **苔原**：v2 起"派生"、**v5 起回到覆盖类**（LC100 100 苔藓/地衣，见 ADR 0009）、
    #     **v6.1 起名字只归这一支**（`adr/0011` 一名一源）：`草原 ∧ 干湿 0` 那条派生**已删**
    #     ——它把柯本 ET 的高原草地（青藏/羌塘/帕米尔，实测 4.5 万格）吃成了苔原，
    #     按中国地理那批是**高寒草原**。现在 ET 气候上的草地按形态读作
    #     寒地草原／高寒草原／高山苔原。
    # 详见 地图/栅格地形数据生成器/climate.py、地图/栅格地形数据生成器/display_class.py 与 `设计笔记03` §14.11。
    # `自然地理区.zip` 那层**不读**：地理区层 2026-10-09 裁掉（见 docs/adr/0006）。
    # 原始件仍在 `原始数据/自然地球/` 备着，与灰度晕渲、重要经纬线同处一类（下了但没用）。
    # ⚠️ **咸水湖与火山不能在这里判**：里海/咸海在 NE 的"陆地掩膜"之外，此刻还是「海洋」，
    # 要等下面「海洋收口」＋「内海转湖」把它们转成湖泊之后才判得上（踩过一次：
    # 掩膜∩湖泊有 18,410 格，早判只有 724 格生效）。
    烧面(ctx, ne_features(NE_GLACIATED), T_ICE, "冰川")
    烧面(ctx, ne_features(NE_LAKES), T_LAKE, "湖泊")
    # ⚠️ 「盐沼 / 滩涂」**不在这里**判：它们必须等河流那一段跑完（否则会把河口
    # 抢走），见下面 `cleanup_river_specks` 之后的那一段。
    was_lake = ctx.地形 == T_LAKE
    # 河流：**HydroRIVERS（主）+ Natural Earth（兜）取并集**。
    # 为什么换：NE 的河流层全库 1,473 个要素，长江入海段（江阴→崇明，约 230 km）
    # 一条线都没有（最近的 NE 河线离江阴 81 km）——需求方看到的"还是断的"就是这处。
    # 那是**覆盖度**问题，缩小像元救不了：空的地方再细也是空的。
    # HydroRIVERS 光亚洲片就 1,428,959 条河段，上下游共用节点，天然接得上。
    # NE 留着兜非洲/阿拉伯/美洲（本管线只下了四片 HydroRIVERS，见 rivers.REGIONS）。
    before_rivers = ctx.地形.copy()          # 去散点时还原用（覆盖 16 类，9.4 MB，便宜）
    hr_files = [hydro_rivers(z) for z in RV.REGIONS]
    if any(os.path.exists(p) for p in hr_files):
        RV.burn_hydrorivers(ctx.地形, T_RIVER, ctx.参数.cell, LON0, LAT1, hr_files,
                            min_cms=ctx.参数.river_min, log=print)
    else:
        print(f"  ! 没有 HydroRIVERS（{RV.REGIONS}），河流退回只有 NE 那一层", file=sys.stderr)
    # NE 用"按折线点燃"而不是 burn：折线要**保证 4 邻接连通**，否则缩小时断流（见 burn_lines）
    烧线(ctx, ne_features(NE_RIVERS), T_RIVER, "NE 河流（兜底并集）")
    # 碎水补面：**逐格取众数会把"碎成几块的水"藏起来**。实测长江口有格 45% 是水像素
    # （80/200 各占一部分），可单一类最多的是农田（LC100 40），取众数就记成「平原」——
    # 于是河到 119.6°E 就"断"了，之后 230 km 的入海段整片是陆地色。
    # 修法：水体占比 ≥ WATER_PCT 且**与既有水面 4 邻接**的格补成水面（河流）。
    # 加"邻接"是为了不动海岸线：孤立的 30% 水格（滩涂、灌溉水田）不该变成河。
    # 做法是"只灌与既有水相连的那一部分"——先按候选 ∪ 既有水做 4 邻接连通块，
    # 丢掉不含既有水的块，再把剩下的候选格点亮。
    if ctx.水体 is not None:
        from scipy import ndimage
        is_water = np.isin(ctx.地形, (T_OCEAN, T_LAKE, T_RIVER))
        # **只灌"离真河 ≤3 格"的碎水格**（v3 收紧）。原先的条件是"与任何水面 4 邻接"，
        # 海也算——于是整条海岸线被镶了一圈假河、小岛整块变河（实测补出 23,166 格里
        # 16,105 格 8 邻接海洋、13,907 格 LC100 明说那是开阔海）。改成按到真河的**距离**
        # 之后：三角洲与河口照样连通（它们本来就紧贴河道），海岸光晕消失——那批格改判
        # 「盐沼/滩涂」（见下面那一段）。
        near_riv = ndimage.distance_transform_edt(ctx.地形 != T_RIVER) <= 3.5
        cand = (ctx.水体 >= TR.WATER_PCT) & ~is_water & near_riv
        if cand.any():
            seed = is_water | cand
            lab = ndimage.label(seed, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))[0]
            keep = np.unique(lab[is_water & (lab > 0)])
            fill = cand & np.isin(lab, keep)
            ctx.地形[fill] = T_RIVER
            print(f"  碎水补面：占比 ≥{TR.WATER_PCT}% 且离真河 ≤3 格的 {int(cand.sum()):,}，"
                  f"其中与水面相连的 {int(fill.sum()):,} 补成河流"
                  f"（河口/三角洲/辫状河；离河远的海岸湿格归盐沼/滩涂）")
    # **湖面赢**：河网里有"湖心线"（HydROSHEDS/NE 都把水流路径画过湖），那是流向记录
    # 不是地表河。让它盖掉湖面，贝加尔湖心就成了一条河（check_terrain 抓到了）。
    # 河穿湖本来就是河→湖→河，颜色一变不是"断"。
    if was_lake.any():
        back = int((was_lake & (ctx.地形 != T_LAKE)).sum())
        ctx.地形[was_lake] = T_LAKE
        if back:
            print(f"  湖面优先：把被河线盖掉的 {back:,} 格湖面还回来")
    # 封缝放在**湖面还原之后**：还原会把河在湖岸处切成两段，再封才能把
    # "河→1 格湖→河"这种查出来的断口接上（反过来做，桥刚封上就被还原成湖）。
    seal_river_gaps(ctx.地形, T_RIVER, (T_OCEAN, T_LAKE), log=print)
    # 连对角放在封缝之后、去散点之前：先把角接触补成正交，合并后的段才不会被当作小段丢掉。
    connect_diagonal_rivers(ctx.地形, T_RIVER, log=print)
    # 去散点放在**湖面还原之后**：还原会把河段切碎，先清会留下新的小段（实测 880 个孤点）。
    cleanup_river_specks(ctx.地形, before_rivers, T_RIVER, RIVER_MIN_CELLS, log=print)

    # **盐沼 / 滩涂**（v3 新增。**放在河流之后**：先让河流拿走河口与三角洲，
    # 剩下的沿海湿格才是潮滩——顺序反了就会把河口抢走，长江口那样）。
    # 两者都是湿地，差别只在**有没有植被**，而这在 LC100 里是分得开的：
    #   · 草本湿地（码 90）贴海 = 有植被 → **盐沼**（碱蓬/芦苇/米草那一类）
    #   · 格内水占比 ≥30% 的光泥滩  → **滩涂**
    if ctx.植被 is not None and ctx.水体 is not None:
        from scipy import ndimage as _nd
        sea8 = _nd.binary_dilation(ctx.陆地 == 0, np.ones((3, 3), bool))
        beach = ctx.陆地.astype(bool) & sea8
        saltm = beach & (ctx.植被 == T_MARSH)
        ctx.地形[saltm] = T_SALTM
        mud = (beach & (ctx.水体 >= TR.WATER_PCT) & (ctx.地形 != T_SALTM)
               & ~np.isin(ctx.地形, (T_OCEAN, T_LAKE, T_RIVER)))
        ctx.地形[mud] = T_TIDAL
        print(f"  盐沼（LC100 草本湿地 ∧ 贴海，有植被）：{int(saltm.sum()):,} 格")
        print(f"  滩涂（格内水占比 ≥{TR.WATER_PCT}% ∧ 贴海，光泥滩）：{int(mud.sum()):,} 格")
