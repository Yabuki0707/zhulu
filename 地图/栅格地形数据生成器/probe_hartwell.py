#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Hartwell 唐 741 州面 —— 只读诊断脚本。

复现 `设计笔记03` §7 的验收基线（数量 / 投影 / 邻接），可选导出 GeoJSON 小样供预览。
不写加工产物到 `地图/`，纯诊断。

用法：
    python 地图/栅格地形数据生成器/probe_hartwell.py                    # 全国州面
    python 地图/栅格地形数据生成器/probe_hartwell.py --region hd        # 单域（hd = 河东）
    python 地图/栅格地形数据生成器/probe_hartwell.py --dump 地图/_preview_741.geojson

实测结论（本脚本即依据）：
  投影  Xian 1980 高斯克吕格 19 带（中央经线 111°E，假东 19 500 000 m）；编码 BIG5
  陷阱一  国家层有无效几何（TopologyException: side location conflict）→ 必须先 make_valid
  陷阱二  相邻州之间存在 ~1e-9 度² 的重叠碎片，故 `touches` 会误判为不相邻
          （例：山西域 蒲/慈 被 touches 判为孤立，实为共享长边）
  正解   拓扑运算全在「投影米制」下做；邻接 = 相交 且 共享边长 > 阈值
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile

import shapefile  # pyshp
from pyproj import CRS, Transformer
from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import transform as sh_transform
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ⚠️ 路径表（mapdata）与底图指纹（basetag）在 **地图/栅格地形数据生成器/** 里 ——
#    2026-10-10 地形流程那一整包搬去了那里，本文件留在 tools/（它做的是行政图那半）。
#    所以先把那一包挂上 sys.path，再 import 它里面的共用模块。
_GEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "地图", "栅格地形数据生成器")
sys.path.insert(0, _GEN)
from mapdata import ROOT, HARTWELL_ZIP     # noqa: E402

ZIP = HARTWELL_ZIP
WGS84 = CRS.from_epsg(4326)

# 数据坐标系：Gauss Kruger / Xian 1980 / zone 19
# 注：EPSG:2333 名义同义，但实测与该 proj4 的 equals() 为 False；以「bbox 落在中国」为验收。
XIAN80_GK19 = CRS.from_proj4(
    "+proj=tmerc +lat_0=0 +lon_0=111 +k=1 +x_0=19500000 +y_0=0 +ellps=IAU76 +units=m +no_defs"
)
TO_WGS = Transformer.from_crs(XIAN80_GK19, WGS84, always_xy=True)

# 共享边短于此值不算邻接（米）。0 与 1000 实测同结果，取 1000 抗噪。
MIN_SHARED_M = 1000.0


def load(zf: zipfile.ZipFile, member: str):
    """读图层 → 修几何 → 同时返回「投影米制」与「WGS84」两套。"""
    sf = shapefile.Reader(
        shp=io.BytesIO(zf.read(member)),
        dbf=io.BytesIO(zf.read(member[:-4] + ".dbf")),
        encoding="big5",
    )
    proj, wgs, recs, n_invalid = [], [], [], 0
    for sr in sf.iterShapeRecords():
        g = shape(sr.shape.__geo_interface__)
        if not g.is_valid:
            n_invalid += 1
            g = make_valid(g)
        proj.append(g)
        wgs.append(sh_transform(lambda x, y: TO_WGS.transform(x, y), g))
        recs.append(sr.record.as_dict())
    return proj, wgs, recs, n_invalid


def adjacency(proj, min_shared: float = MIN_SHARED_M):
    """邻接 = 相交 且 共享边长 > 阈值。返回 (邻居索引表, 共享边长表)。"""
    tree = STRtree(proj)
    adj, shared = [], []
    for i, g in enumerate(proj):
        ns, ls = [], []
        for j in tree.query(g, predicate="intersects"):
            if j == i:
                continue
            L = g.intersection(proj[j]).length
            if L > min_shared:
                ns.append(j)
                ls.append(L)
        order = sorted(range(len(ns)), key=lambda k: -ls[k])
        adj.append([ns[k] for k in order])
        shared.append([ls[k] for k in order])
    return adj, shared


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="", help="单域缩写，如 hd（河东）、jgn、sn；空 = 全国层")
    ap.add_argument("--min-shared", type=float, default=MIN_SHARED_M, help="邻接共享边长阈值（米）")
    ap.add_argument("--dump", default="", help="导出 GeoJSON 路径")
    args = ap.parse_args()

    if not os.path.exists(ZIP):
        print("缺少数据，先跑: python 地图/栅格地形数据生成器/fetch_map_data.py --group core", file=sys.stderr)
        return 1

    member = (
        f"v5_Hartwell/v5_0741_pref_{args.region}_0741_p.shp"
        if args.region
        else "v5_Hartwell/v5_0741_chin_chn_0741_p.shp"
    )
    zf = zipfile.ZipFile(ZIP)
    if member not in zf.namelist():
        print(f"没有这个层: {member}", file=sys.stderr)
        return 1

    proj, wgs, recs, n_invalid = load(zf, member)
    name = lambda i: recs[i].get("H_UNICODE_") or recs[i].get("H_PINYIN_N") or str(recs[i].get("CODE"))

    minx = min(g.bounds[0] for g in wgs); miny = min(g.bounds[1] for g in wgs)
    maxx = max(g.bounds[2] for g in wgs); maxy = max(g.bounds[3] for g in wgs)
    print(f"图层      {member.split('/')[-1]}")
    print(f"要素数    {len(proj)}    （其中无效几何 {n_invalid} 个，已 make_valid 修复）")
    print(f"经纬 bbox {minx:.2f}, {miny:.2f} → {maxx:.2f}, {maxy:.2f}   （应落在中国 73–135E / 18–54N）")
    cm, = TO_WGS.transform(19500000, 4000000)[:1]
    print(f"投影自检  (19500000, 4000000) → 经度 {cm:.3f}   （应为 111.000）")
    print(f"多部件面  {sum(1 for g in proj if g.geom_type == 'MultiPolygon')}   （飞地表现为多部件）")

    adj, shared = adjacency(proj, args.min_shared)
    deg = [len(a) for a in adj]
    edges = sum(deg) // 2
    iso = [i for i, ns in enumerate(adj) if not ns]
    print(f"邻接      边 {edges}，平均度 {sum(deg)/len(deg):.2f}，中位 {sorted(deg)[len(deg)//2]}，"
          f"孤立 {len(iso)}" + (f" → {[name(i) for i in iso]}" if iso else ""))
    print(f"          阈值 {args.min_shared:.0f} m；共享边长同时可作为「边界长度」属性")

    if iso:
        print("          孤立件须人工补通路边（海岛/飞地/关隘），不得静默留下断点")

    top = sorted(range(len(proj)), key=lambda i: -proj[i].area)[:8]
    print("最大 8 个 " + " | ".join(f"{name(i)} {proj[i].area/1e9:.1f}万km²" for i in top))

    widest = sorted(range(len(adj)), key=lambda i: -(shared[i][0] if shared[i] else 0))[:3]
    print("最长边界  " + " | ".join(f"{name(i)}–{name(adj[i][0])} {shared[i][0]/1000:.0f}km" for i in widest))

    if args.dump:
        out = args.dump if os.path.isabs(args.dump) else os.path.join(ROOT, args.dump)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": name(i),
                        "code": recs[i].get("CODE"),
                        "adm_type": recs[i].get("H_ADMIN_TY"),
                        "area_km2": round(proj[i].area / 1e6, 1),
                        "neighbors": [name(j) for j in adj[i]],
                        "border_km": [round(L / 1000, 1) for L in shared[i]],
                    },
                    "geometry": mapping(wgs[i]),
                }
                for i in range(len(proj))
            ],
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)
        print(f"\n已导出 {out}  （{len(fc['features'])} 个要素）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
