# -*- coding: utf-8 -*-
"""河流线网：HydroRIVERS v1.0（HydroSHEDS）→ 栅格河格。

**为什么换掉 Natural Earth 的河流层。** `ne_10m_rivers_lake_centerlines` 全库只有
**1,473 个要素**（本管线经度窗口内 1,026 条折线），是"具名大河"的概化线网。实测后果：

  · **缺覆盖**：长江在 NE 里切成 3 段，最下游那段**终点就是 119.606°E**；江阴
    （120.28°E）离最近的 NE 河线 **0.728° ≈ 81 km**。江阴→崇明→入海口约 230 km 的江段
    NE 里一条线都没有——需求方看图指的就是这处"还是断的"。这是**覆盖度**问题，
    **缩小像元救不了**：空的地方再细也是空的。
  · **端点错位**：概化线网在湖泊两端与汇口处会把线切断，两条折线端点并不重合
    （淮河入江口那处差 2 格）。这一半已在 `build_raster.seal_river_gaps()` 里补过。

HydroRIVERS v1.0 是同一家（HydroSHEDS）的**拓扑一致**河网：光亚洲片就 **1,428,959 条
河段**（地球约 850 万条）。每条带 `DIS_AV_CMS`（多年平均流量 m³/s）、`ORD_STRA`（Strahler）、
`ORD_CLAS`（1–10 级）、`UPLAND_SKM`（上游集水面积）、`NEXT_DOWN`（下游段号）。
上下游段**共用节点**，所以描出来的线天然接得上，不再有"端点缝"。

许可：HydroSHEDS v1.0 免费含商用，**禁作独立产品再分发**（随产品分发可以）。本管线已经在
用它家的 HydroBASINS（`原始数据/流域/`），同一笔账。见 `地图/地图数据/说明.md` §三。

与 NE 的关系：**取并集**。HydroRIVERS 补密度与覆盖，NE 兜住 HydroRIVERS 没分区的角落
（本管线只下了 亚洲/西伯利亚/欧洲/澳洲 四片；非洲、阿拉伯、美洲仍由 NE 供河）。
"""
from __future__ import annotations

import io
import os
import zipfile

# 画哪些河：多年平均流量 ≥ 这个值（m³/s）。**河网密度就调这一个旋钮**。
# 实测（全图河格，含 NE 并集与碎水补面）：
#     T=20 → 204,736 格 = 2.75%  ← 太密，需求方一眼"密密麻麻"，作废
#     T=50 → 153,316 格 = 2.06%
#     T=100 → 128,843 格 = 1.73%  ← **默认**（1.8 倍于上一版 NE 的 0.97%）
# 参照：换之前 NE 的河格是 72,429（全图），但那是 1,026 条粗折线拼出来的。
# 命令行：`python 地图/栅格地形数据生成器/生成.py --river-min 200` 之类。
MIN_CMS = 100.0

# 已下载的分区片（文件名见 地图/栅格地形数据生成器/mapdata.py 的 hydro_rivers()）。缺哪片只影响那片没有
# HydroRIVERS 的河，不会报错——NE 那一层还在。
# 北极片（ar）实测**一条都不画**：它只覆盖加拿大北极群岛（lon −180…−61），
# 那些岛上的河流量全部 < 本阈值。按"只留在用的东西"不下载。若把 --river-min 降到 50 以下
# 再把它加回来（清单里见 地图/栅格地形数据生成器/fetch_map_data.py 的注释）。
REGIONS = ("亚洲", "西伯利亚", "欧洲", "澳洲")

# HydroRIVERS 是 WGS84 经纬度、坐标就是格心经纬度，不存在折回问题（每段都短，
# 不会跨日界线）；但为稳妥仍按窗口 bbox 过滤。
_MAX_SEG_DEG = 5.0          # 单段跨度超过这个就当异常（防脏数据把全图拉成一条带）


def _hits(b, lon0, lon1, lat0, lat1) -> bool:
    return not (b[2] < lon0 or b[0] > lon1 or b[3] < lat0 or b[1] > lat1)


def burn_hydrorivers(terrain, value: int, cell: float, lon0: float, lat1: float,
                     files, min_cms: float = MIN_CMS, log=print) -> int:
    """把 HydroRIVERS 的河段按 supercover 烧进 terrain（原地），返回画的河段数。

    只烧**窗口内**、且 `DIS_AV_CMS ≥ min_cms` 的段。网格里的一格 = cell 度，
    行序自北向南（`row = (lat1 - lat) / cell`）。
    """
    import shapefile
    from geo_wrap import supercover

    H, W = terrain.shape
    lo, hi = lon0, lon0 + W * cell
    la, ha = lat1 - H * cell, lat1
    nseg = nbad = 0
    for path in files:
        if not path or not os.path.exists(path):
            log(f"  ! 缺 {os.path.basename(path or '')}，跳过")
            continue
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            shp = next((n for n in names if n.lower().endswith(".shp")), None)
            if not shp or shp[:-4] + ".dbf" not in names:
                log(f"  ! {os.path.basename(path)} 里找不到 .shp/.dbf，跳过")
                continue
            sf = shapefile.Reader(shp=io.BytesIO(z.read(shp)),
                                  dbf=io.BytesIO(z.read(shp[:-4] + ".dbf")))
            i_d = [f[0] for f in sf.fields[1:]].index("DIS_AV_CMS")
            got = 0
            for sr in sf.iterShapeRecords():
                cms = sr.record[i_d]
                if cms is None or cms < min_cms:
                    continue
                sh = sr.shape
                if not _hits(sh.bbox, lo, hi, la, ha):
                    continue
                if sh.bbox[2] - sh.bbox[0] > _MAX_SEG_DEG or sh.bbox[3] - sh.bbox[1] > _MAX_SEG_DEG:
                    nbad += 1
                    continue
                pts, parts = sh.points, list(sh.parts) + [len(sh.points)]
                for a, b in zip(parts, parts[1:]):
                    co = pts[a:b]
                    for (ax, ay), (bx, by) in zip(co, co[1:]):
                        for cy, cx in supercover(((lat1 - ay) / cell, (ax - lon0) / cell),
                                                 ((lat1 - by) / cell, (bx - lon0) / cell)):
                            if 0 <= cy < H and 0 <= cx < W:
                                terrain[cy, cx] = value
                    got += 1
                if got and got % 50000 < 1:
                    log(f"      … {got:,} 段")
        nseg += got
        log(f"    {os.path.basename(path)}：画 {got:,} 段")
    if nbad:
        log(f"  ! {nbad} 段跨度过大被跳过（> {_MAX_SEG_DEG}°，疑似脏数据）")
    log(f"  HydroRIVERS（流量 ≥ {min_cms:g} m³/s，{len(REGIONS)} 片）：共画 {nseg:,} 段")
    return nseg
