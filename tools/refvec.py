# -*- coding: utf-8 -*-
"""参考层：把「单元边界 + 唐 741 州面」导出成**矢量顶点**（不再是烧进 PNG 的栅格掩膜）。

为什么要改：原来的 `县界参考.png` 是 8 位掩膜，1 px 线在缩放时要么整片消失、要么闪烁，
于是又得配一套 mipmap 金字塔（`buildRefMips` / `maskToCanvas`）来兜。顶点图是矢量，
画的时候按屏幕像素描线、缩放到街道级还能落出原始顶点，既不用金字塔也不会糊。

输出格式（`参考顶点.bin`，小端）：

    "ZLRV1\0\0\0"        8 B  魔数
    uint32 n_rings             环数
    uint32 n_points            顶点总数
    uint32 off[n_rings + 1]    每个环在顶点表里的起止下标（off[n] = n_points）
    uint8  src[n_rings]        0 = 现代单元边界，1 = 唐 741 州面
    uint16 xy[n_points * 2]    格坐标 × 8（1/8 格 ≈ 1 km），交错存放 x, y

格坐标 × 8 是为了留出亚格精度又不撑体积：x ∈ [0, 2813×8 = 22504] ⊂ uint16。
"""
from __future__ import annotations

import struct

import numpy as np

MAGIC = b"ZLRV1\0\0\0"
SUB = 8                     # 每个格再分 8 份（1/8 格 ≈ 1.04 km）
SRC_UNIT = 0                # 现代基础单元边界（非汉地，或汉地内唐州覆盖不到的部分）
SRC_TANG = 1                # 唐 741 州面


def _quant(pts, H):
    """[(x, y), …] 格坐标 → (int32 x8, int32 y8)，并去掉相邻重复点。"""
    if len(pts) < 2:
        return None
    q = []
    last = None
    for x, y in pts:
        xi = int(round(x * SUB))
        yi = int(round(y * SUB))
        if xi < 0 or yi < 0 or xi > 65535 or yi > 65535:
            continue
        if (xi, yi) != last:
            q.append((xi, yi))
            last = (xi, yi)
    if len(q) < 2:
        return None
    return q


def _tang_cover(tang, H):
    """唐州面（像素坐标）→ 合并后的覆盖多边形，用来判断现代单元边界要不要让位。"""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polys = []
    for ext, holes in tang:
        if len(ext) < 3:
            continue
        p = Polygon(ext, [h for h in holes if len(h) >= 3])
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty:
            polys.append(p)
    if not polys:
        return None
    try:
        cover = unary_union(polys)
    except Exception:                                                        # noqa: BLE001
        return None
    from shapely.prepared import prep
    return prep(cover) if cover is not None and not cover.is_empty else None


def build_ref_vector(units, k, cell, lon0, lat1, tang_px, out_path, log=print) -> dict:
    """units = 基础单元.json['units']；tang_px = [(外环像素点, [洞环像素点]), …]。"""
    from shapely.geometry import LineString

    cover = _tang_cover(tang_px, None)
    rings, srcs = [], []

    # 1) 唐 741 州面（汉地以此为准），先入表
    for ext, holes in tang_px:
        q = _quant([((x), (y)) for x, y in ext], None)
        if q:
            rings.append(q)
            srcs.append(SRC_TANG)
        for h in holes:
            q = _quant([((x), (y)) for x, y in h], None)
            if q:
                rings.append(q)
                srcs.append(SRC_TANG)

    # 2) 现代单元边界：整条环被唐州覆盖区盖住的就丢掉（汉地不给两套线叠加）
    skipped = 0
    for u in units:
        for rr in u["g"]:
            for ring in rr:
                pts = [((ring[i] / k - lon0) / cell, (lat1 - ring[i + 1] / k) / cell)
                       for i in range(0, len(ring), 2)]
                if len(pts) < 2:
                    continue
                if cover is not None and len(pts) >= 3:
                    try:
                        if cover.covers(LineString(pts)):
                            skipped += 1
                            continue
                    except Exception:                                        # noqa: BLE001
                        pass
                q = _quant(pts, None)
                if q:
                    rings.append(q)
                    srcs.append(SRC_UNIT)

    off = np.zeros(len(rings) + 1, np.uint32)
    flat = []
    for i, r in enumerate(rings):
        off[i] = len(flat)
        flat.extend(r)
    off[len(rings)] = len(flat)

    with open(out_path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<II", len(rings), len(flat)))
        f.write(off.astype("<u4").tobytes())
        f.write(bytes(srcs))
        f.write(np.asarray(flat, np.uint32).astype("<u2").tobytes())

    import os
    info = {"rings": len(rings), "points": len(flat), "tang_rings": int(sum(1 for s in srcs if s == SRC_TANG)),
            "skipped_covered": skipped, "bytes": os.path.getsize(out_path)}
    log(f"  参考顶点：{info['rings']} 环 / {info['points']} 顶点"
        f"（唐州 {info['tang_rings']} 环，汉地被唐州覆盖而略去 {skipped} 环）"
        f" {info['bytes'] / 1048576:.2f} MB")
    return info
