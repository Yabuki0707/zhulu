# -*- coding: utf-8 -*-
"""把跨日界线（或跨出窗口）的几何，切成落在连续经度窗口内的分段。

问题：按「逐点」折回（x + 360 if x < 阈值）会切穿几何——被切的那条要素会被拉成
一条横贯全图的带（本轮踩到的色条就是这个：美洲河流的副本在 −120° 附近被切开）。
正解：先把几何沿窗口两条缝切开，再整段平移，最后丢掉落在窗口外的段。

    from geo_wrap import wrap_into
    for piece in wrap_into(geom, lon0=25.0, lon1=236.0): ...
"""
from __future__ import annotations

from shapely.geometry import LineString
from shapely.ops import split, transform

SEAM_LAT = 90.0


def wrap_into(g, lon0: float = 25.0, lon1: float = 236.0):
    """返回落在 [lon0, lon1] 内的分段列表（可能是空、一段或多段）。"""
    if g is None or g.is_empty:
        return []
    seam_a, seam_b = lon0, lon1 - 360.0
    pieces = [g]
    for seam in (seam_a, seam_b):
        cutter = LineString([(seam, -SEAM_LAT), (seam, SEAM_LAT)])
        out = []
        for p in pieces:
            if p.is_empty:
                continue
            minx, _, maxx, _ = p.bounds
            if minx < seam < maxx:
                try:
                    out.extend([q for q in split(p, cutter).geoms if not q.is_empty])
                except Exception:            # 自交等退化情形：保持原样，后面再做窗口过滤
                    out.append(p)
            else:
                out.append(p)
        pieces = out
    res = []
    for p in pieces:
        if p.is_empty:
            continue
        if p.bounds[0] < seam_a:             # 整段平移到日界线以东
            p = transform(lambda x, y, z=None: (x + 360.0, y), p)
        if p.is_empty:
            continue
        if p.bounds[0] >= lon0 - 1e-6 and p.bounds[2] <= lon1 + 1e-6:
            res.append(p)
        else:                                 # 仍在窗口外的部分丢掉
            continue
    return res


def wrap_union(g, lon0: float = 25.0, lon1: float = 236.0):
    """像 wrap_into，但把分段并成一个几何（用于「一个单元可能被切成两段」的场合）。"""
    from shapely.ops import unary_union
    parts = wrap_into(g, lon0, lon1)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    u = unary_union(parts)
    return None if u.is_empty else u


def supercover(a, b):
    """两个格坐标之间按 ≤1 格步长走 supercover，返回格子列表（含两端，**保证 4 邻接连通**）。

    相邻两点之间线性采样，遇到"横纵同时跨一格"的对角步就补一格正交格。这是**线状要素转
    栅格**的公共底座：`build_raster.burn_lines`（Natural Earth 河）与 `rivers.burn_hydrorivers`
    （HydroRIVERS 河）都靠它，否则缩小时会断流（原委见 `设计笔记03` §14.11）。
    放在这里的理由：它既不属于"折回"也不属于"烧面"，是二者的下游公用件。
    """
    import numpy as np
    cells = []
    dr, dc = b[0] - a[0], b[1] - a[1]
    n = int(np.ceil(max(abs(dr), abs(dc)))) + 1
    py = px = None
    for i in range(n + 1):
        t = i / n
        cy, cx = int(np.floor(a[0] + dr * t)), int(np.floor(a[1] + dc * t))
        cells.append((cy, cx))
        if px is not None and abs(cy - py) == 1 and abs(cx - px) == 1:
            cells.append((py, cx))              # 对角步补一格 → 4 邻接
        py, px = cy, cx
    return cells
