# -*- coding: utf-8 -*-
"""收口与湖海 —— 生成流程的第 5 步。

本文件由 `_拆分.py` 从原来的单坨 `生成.py` **逐字搬**出来，只做了两件机械事：
缩进回退 4 格、跨阶段的状态名换成 `ctx.xxx`。**改判据要连着 `管线.py` 的阶段表一起看**
（顺序即语义：后一步压前一步）。
"""
from __future__ import annotations

from __future__ import annotations

import numpy as np

from scipy import ndimage as nd
import glwd as GL
import terrain as TR

from 契约 import (
    T_FARM, T_GRASS, T_GRAVEL, T_ICE, T_LAKE, T_OCEAN, T_RIVER, T_SALTLAKE, T_SALTM, T_SAND,
    T_SEAICE, T_VOLCANO,
)


def run(ctx) -> None:
    """跑这一步。日志走 `ctx.log`（界面上是实时日志框）。"""
    # 海洋口径收口：陆地掩膜的补集。**但河线穿过的格子不算海** —— 长江江阴以下的入海段
    # 在 NE 陆地面与 LC100 里都是 200（开阔海），若一律按掩膜收口，刚补上的入海段会被
    # 重新抹成海洋，等于白换数据源。判据只看 `terrain == T_RIVER`（只有河烧伤它），
    # 所以不会把任何真海格变成陆地。见 地图/栅格地形数据生成器/rivers.py。
    ctx.地形[(ctx.陆地 == 0) & (ctx.地形 != T_RIVER)] = T_OCEAN
    # **内海 / 大湖**（v9 重做）：里海、咸海、贝加尔、死海、五大湖在 Natural Earth 里属于
    # **"海洋层"**（不在湖泊层），光靠 NE 会把它们记成「海洋」。
    # 旧版靠"LC100 说是内陆水体(80)"往回捞 —— **漏得厉害**：LC100 在里海的**浅滩**说那是陆地
    # （草本湿地/草原/裸地），于是里海里残留 439 格"海洋"（需求方截图报的就是这个）。
    # 现在改成：**GLWD-1 的湖面清单当"什么算湖"的唯一口径** —— 它在窗口内的面
    # 没有一个其实是海（黑海/地中海不在里面），既能把里海整块捞回来，又不会误伤真海。
    # ⚠️ v10 起这张掩膜是**分型码**（1 湖 2 水库，见 地图/栅格地形数据生成器/glwd.py），所以判"是湖"写 `> 0`。
    if ctx.湖面 is not None:
        il = (ctx.地形 == T_OCEAN) & (ctx.湖面 > 0)
        if il.any():
            ctx.地形[il] = T_LAKE
            print(f"  内海/大湖（GLWD 湖面清单）：{int(il.sum())} 格由海洋改记湖泊")
    # 兜底：GLWD 只收 ≥50 km² 的大湖，小水体仍靠 LC100 —— 但**排除贴着真海洋的格**，
    # 那些是沿海水体（盐田/潟湖），不是湖（见下面那一步）。
    if ctx.植被 is not None:
        sea8 = nd.binary_dilation(ctx.地形 == T_OCEAN, np.ones((3, 3), bool))
        inland = (ctx.地形 == T_OCEAN) & (ctx.植被 == TR.C_LAKE) & ~sea8
        if inland.any():
            ctx.地形[inland] = T_LAKE
            print(f"  内海/大湖（LC100 内陆水体兜底，不含贴海格）：{int(inland.sum())} 格")
    # **湖岸收口**（v9）：GLWD 的湖面是 1:100 万级的手绘面，**比湖略小**——里海东南角就缺
    # 一块，实测残留 704 格"海洋"（52–54°E / 40–42°N，一格都不在 GLWD 的里海面内）。
    # 它们是**被湖围住、贴不到外海**的小块"海洋"，按定义就是湖岸。
    # 判据三条同时成立才归湖：①这一块"海洋"**走不到窗口边界**（＝被围住）；②**≤3,000 格**
    # （黑海 18,458 格就过不了这条，仍是海洋 ✓）；③**8 邻接有湖**。归哪一类按邻域多数投。
    if nd is not None:
        sea = ctx.地形 == T_OCEAN
        lab, nlab = nd.label(sea, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
        if nlab:
            edge = set(np.unique(np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]])))
            sizes = nd.sum(np.ones_like(lab), lab, range(1, nlab + 1))
            is_lake = np.isin(ctx.地形, (T_LAKE, T_SALTLAKE))
            near_lake = nd.binary_dilation(is_lake, np.ones((3, 3), bool))
            n_shore = 0
            for i in range(1, nlab + 1):
                if i in edge or sizes[i - 1] > 3000:
                    continue
                comp = lab == i
                if not (comp & near_lake).any():
                    continue
                fresh = (comp & nd.binary_dilation(ctx.地形 == T_LAKE, np.ones((3, 3), bool))).sum()
                salt = (comp & nd.binary_dilation(ctx.地形 == T_SALTLAKE, np.ones((3, 3), bool))).sum()
                ctx.地形[comp] = T_SALTLAKE if salt > fresh else T_LAKE
                n_shore += int(comp.sum())
            if n_shore:
                print(f"  湖岸收口（被围住、贴湖、≤3,000 格的'海洋'块归湖）：{n_shore:,} 格")

    # **沿海的内陆水体 → 盐沼**（v9）：LC100 把**盐田**（长芦盐场，天津汉沽—沧州黄骅，全国最大
    # 海盐场）的蒸发池记成"内陆水体"，于是图上读成「湖泊」——需求方报的"沧州、天津沿海的湖泊"
    # 就是这 138 格（全图同类 2,051 格：里海/咸海沿岸潟湖、渤海湾西岸、北极沿岸潟湖）。
    # 它们不是湖：贴着真海洋、且不在 GLWD 湖面清单里 → 读**盐沼**（沿海盐碱滩）。
    if ctx.植被 is not None and ctx.湖面 is not None:
        # 用"距海 ≤2 格"而不是只 8 邻接：盐田是一大片蒸发池，靠内那几排贴不到海，
        # 但它们同样是盐田不是湖。口径与既有的「碎水补面：离真河 ≤3 格」同一路。
        sea8 = nd.binary_dilation(ctx.地形 == T_OCEAN, np.ones((3, 3), bool))             | nd.binary_dilation(nd.binary_dilation(ctx.地形 == T_OCEAN, np.ones((3, 3), bool)),
                                 np.ones((3, 3), bool))
        works = (ctx.地形 == T_LAKE) & (ctx.植被 == TR.C_LAKE) & sea8 & (ctx.湖面 == 0)
        if works.any():
            ctx.地形[works] = T_SALTM
            print(f"  沿海盐田/潟湖（LC100 内陆水体 ∧ 距海 ≤2 格 ∧ 非 GLWD 湖）→ 盐沼："
                  f"{int(works.sum()):,} 格")
    # **干涸的湖床回水**（v10，2026-10-10 需求方定）：GLWD 说这里是一片湖，而今天的 LC100 说
    # 那是裸地/草原/农田 —— **咸海**就是这一类：内流湖（`closedx`），1960 年代起持续萎缩，
    # LC100（2019 影像）看到的已是干涸湖床（砾质裸地），于是"底图照今天的影像走"与
    # "这里是咸海"打架。判据三条：
    #   ① 落在 GLWD-1 的**湖**面内（`lakepoly == LAKE`）—— **水库面不算**：水库的面普遍画得
    #      比今天的水面大（布拉茨克/卡布拉巴萨/下卡马），跟着它走会把湖边的**真林子**变成假湖
    #      （实测 699 格，其中 290 格是密林）；
    #   ② 今天的覆盖只能是**沙质裸地 / 砾质裸地 / 草甸 / 草原**（干了的湖床）——
    #      **不碰密林/疏林/灌丛/沼泽**：那是活着的植被与湿地，不是湖床；
    #   ③ 咸淡照旧，由下面两步定（闭合盆地 → 咸湖）。实测命中 2,833 格，其中咸海 2,119 格
    #      （74%）、闭合盆地 2,395 格。
    if ctx.湖面 is not None:
        # 内流湖：今天的水 + 干湖床都算「内流湖／外流湖」里的前者；外流湖（open）同样接回水。
        dry = (ctx.湖面 == GL.LAKE) & np.isin(ctx.地形, (T_SAND, T_GRAVEL, T_FARM, T_GRASS))
        if dry.any():
            ctx.地形[dry] = T_LAKE
            n_salt = int((dry & (ctx.闭合盆地 == 1)).sum()) if ctx.闭合盆地 is not None else 0
            print(f"  干涸湖床回水（GLWD 湖面 ∧ 沙/砾/草甸/草原）：{int(dry.sum()):,} 格"
                  f"，其中闭合盆地 {n_salt:,} 格（随后读咸湖）")
    # **咸水湖**（v9）：必须等「内海转湖」之后 —— 里海/咸海/死海这些在 NE 里属"海洋层"，
    # 到这一步才变成「湖泊」，在这之前判会全漏掉。
    if ctx.闭合盆地 is not None:
        sl = (ctx.地形 == T_LAKE) & (ctx.闭合盆地 == 1)
        ctx.地形[sl] = T_SALTLAKE
        print(f"  咸水湖（GLWD-1 闭合盆地湖 ∧ 已是湖泊）：{int(sl.sum()):,} 格")
    # **咸淡按"水体整体"定**（v9）：同一个湖里不该一半咸一半淡 —— 咸淡是**这片水**的性质，
    # 不是格的性质。所以把「淡湖 ∪ 咸湖」按 4 邻接连通域切开，**只要一块里有一格落在 GLWD 的
    # 闭合盆地湖面内，整块就是咸湖**。修的是里海东南角：那块是被"LC100 兜底"补上的、
    # GLWD 面没盖到，于是先读成了淡湖（实测 704 格海洋 → 补成淡湖）。
    if ctx.闭合盆地 is not None:
        lk = np.isin(ctx.地形, (T_LAKE, T_SALTLAKE))
        lab, nl = nd.label(lk, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
        seed = np.unique(lab[(ctx.闭合盆地 == 1) & lk])
        seed = seed[seed > 0]
        if seed.size:
            whole = np.isin(lab, seed) & lk
            n_fix = int((whole & (ctx.地形 == T_LAKE)).sum())
            ctx.地形[whole] = T_SALTLAKE
            if n_fix:
                print(f"  咸淡按水体整体定：{n_fix:,} 格由淡湖改咸湖（同一片水不拆开）")
    # **火山**（v9）：GVP 的全新世火山点是**点**，盖在陆地地表上（不盖水面）。
    if ctx.火山点 is not None:
        vc = (ctx.火山点 == 1) & ~np.isin(ctx.地形, (T_OCEAN, T_LAKE, T_RIVER, T_ICE, T_SEAICE))
        ctx.地形[vc] = T_VOLCANO
        print(f"  火山（GVP 全新世火山点，落在陆地格）：{int(vc.sum()):,} 格")
    # **海冰**（v9）：必须在**海洋收口之后**——否则会被收口那一步抹掉。
    # 判据是数据自带的频率：1981–2010 的 30 个 3 月里 ≥50% 的年份被冰盖住。
    if ctx.海冰层 is not None:
        si = (ctx.地形 == T_OCEAN) & (ctx.海冰层 == 1)
        ctx.地形[si] = T_SEAICE
        print(f"  海冰（NSIDC 3 月范围面，1981–2010 常年）：{int(si.sum()):,} 格"
              + ("　⚠️ 渤海海冰不在 NSIDC 25 km 产品里，见 adr/0014" if si.any() else ""))
