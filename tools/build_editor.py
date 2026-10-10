#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建单文件地图编辑器（全图范围 · 两级模型）。

基础单元（底料）：
  中华地区 = GADM 4.1 CHN level 3（县级，2421 个，带中文省市县名）
  其他地区 = Natural Earth 10m admin-1（一级政区，4564 个）
地块（游戏单位）：
  由若干基础单元组成。初始种子：中华 = 按「市」归并（一市一地块）；其他 = 一单元一地块。
  编辑器里可再归并/拆分/改名/指派地缘地域。

    python tools/build_editor.py --dump-units    # → 地图数据/基础单元.json（给 生成.py 栅格化）
    python tools/build_editor.py --no-world      # 只做中华（数据小时调试用）
    python tools/build_editor.py --dp 3          # 量化精度（0.001°，约 111 m）

拓扑约定（见 设计笔记03）：所有判定在投影米制下做；make_valid 先行；
相邻州间有 ~1e-9 度² 重叠碎片 → 不用 touches，用「相交且共享边长 > 阈值」。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import date

import shapefile
# ⚠️ 路径表（mapdata）与底图指纹（basetag）在 **地图/栅格地形数据生成器/** 里 ——
#    2026-10-10 地形流程那一整包搬去了那里，本文件留在 tools/（它做的是行政图那半）。
#    所以先把那一包挂上 sys.path，再 import 它里面的共用模块。
_GEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "地图", "栅格地形数据生成器")
sys.path.insert(0, _GEN)
from 附录C import load_palette, APPENDIX_C          # noqa: E402
from geo_wrap import wrap_union
from mapdata import SCOPE_LON0, SCOPE_LON1, SCOPE_LAT0, SCOPE_LAT1
from mapdata import (ROOT, DATA_DIR, under, UNITS as UNITS_JSON,
                     NE_ADM1, NE_COUNTRIES, GADM_CN3)
from pyproj import CRS, Geod, Transformer
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import transform as sh_transform
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
GADM = GADM_CN3
NE1 = NE_ADM1
NE0 = NE_COUNTRIES
OUT_UNITS = UNITS_JSON
CJK = re.compile(r"[\u4e00-\u9fff]")


def zh_name(rec: dict, keys=("name_zh", "NAME_ZH", "name_zht", "NAME_ZHT")) -> str:
    """Natural Earth 要素的中文名：优先 name_zh，其次 name_zht，都没有则空。
    （admin-1 用小写字段名，admin-0 用大写，故两种都试。）"""
    for k in keys:
        v = (rec.get(k) or "").strip()
        if v and CJK.search(v):
            return v
    return ""


def load_country_zh() -> dict:
    """国家/地区中文名（admin-0 的 name_zh），给没有名字的一级政区兜底。"""
    if not os.path.exists(NE0):
        return {}
    z = zipfile.ZipFile(NE0)
    shp = [n for n in z.namelist() if n.endswith(".shp")][0]
    sf = shapefile.Reader(shp=io.BytesIO(z.read(shp)), dbf=io.BytesIO(z.read(shp[:-4] + ".dbf")))
    out = {}
    for sr in sf.iterShapeRecords():
        r = sr.record.as_dict()
        for key in ("ADMIN", "NAME", "SOVEREIGNT", "ADM0_A3", "ISO_A2"):
            v = (r.get(key) or "").strip()
            if not v:
                continue
            zh = zh_name(r)
            if zh:
                out.setdefault(v, zh)
    return out


WGS84 = CRS.from_epsg(4326)
# 用于面积/长度的近似等积投影（中国附近），仅取量级
AEA = CRS.from_proj4("+proj=aea +lat_1=25 +lat_2=47 +lat_0=35 +lon_0=105 +datum=WGS84 +units=m +no_defs")
CHINA_TOL = 0.003        # 中华县级简化容差（度）
WORLD_TOL = 0.08         # 世界一级政区简化容差（度）
MIN_OVERLAP_M2 = 1000.0  # 底图单元重叠报警阈值

# 只保留「亚洲 + 大洋洲」——与游戏的 14 地缘一致；欧洲/非洲/美洲/南极剔除。
ASIA = {"AE","AF","AM","AZ","BD","BH","BN","BT","CN","CY","GE","ID","IL","IN","IQ","IR","JO","JP",
        "KG","KH","KP","KR","KW","KZ","LA","LB","LK","MM","MN","MV","MY","NP","OM","PH","PK","PS",
        "QA","SA","SG","SY","TH","TJ","TL","TM","TR","TW","UZ","VN","YE","IO","CC","CX"}
OCEANIA = {"AU","NZ","PG","FJ","SB","VU","NC","PF","WS","TO","KI","NR","TV","FM","MH","PW","GU",
           "MP","AS","CK","NU","TK","WF","NF","PN"}
# GADM 的中华层里，港澳两地的 `NL_NAME_1/2` 是空的、`NAME_*` 是罗马字（Macau / Ilhas / NA），
# 不补就会印出「Macau市区」。原来靠一张手写译名表 `CITY_ZH` 兜，那张表在"地名全量中文化"
# 那次重构里被删了。这里只留**实测需要的那三条**——小、稳定、一眼看得懂。
ADMIN_ZH = {"Macau": "澳门", "Ilhas": "澳门离岛", "NA": "香港"}
RU_ASIA_LON = 58.0       # 俄罗斯以此经度为界，只留乌拉尔以东（北荒/辽海）
# 世界窗口与格边长：**唯一出处是 地图/栅格地形数据生成器/mapdata.py**（生成.py 用的是同一份）。
LON0, LON1 = SCOPE_LON0, SCOPE_LON1
LAT0, LAT1 = SCOPE_LAT0, SCOPE_LAT1


def keep_unit(iso: str, iso2: str, lon: float) -> bool:
    if iso == "CN":
        return False                              # 中华用县界，见 build_china
    if iso in ASIA or iso in OCEANIA:
        return True
    if iso == "RU":
        return lon >= RU_ASIA_LON
    return iso2 == "US-HI"                        # 夏威夷（沧溟·夏威域）


# `load_palette()` 与 APPENDIX_C 2026-10-10 搬进 `地图/栅格地形数据生成器/附录C.py`
# （生成器要读它，行政侧跟着从这里 import —— 依赖方向就顺了）。


def polygonal(g):
    g = make_valid(g)
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    parts = [p for p in getattr(g, "geoms", []) if p.geom_type in ("Polygon", "MultiPolygon")]
    if not parts:
        return Polygon()
    return MultiPolygon([q for p in parts for q in (p.geoms if p.geom_type == "MultiPolygon" else [p])])


def rings_int(g, dp: int):
    """→ [[ring...], …]，ring 为扁平整数数组（坐标 × 10^dp），省体积。"""
    k = 10 ** dp
    polys = g.geoms if g.geom_type == "MultiPolygon" else [g]
    out = []
    for poly in polys:
        if poly.is_empty or poly.area == 0:
            continue
        rr = [[int(round(v * k)) for xy in poly.exterior.coords for v in xy]]
        for h in poly.interiors:
            rr.append([int(round(v * k)) for xy in h.coords for v in xy])
        out.append(rr)
    return out


def nm(p, key):
    v = (p.get(key) or "").strip()
    return "" if v in ("NA", "") else v.split("|")[0]


def build_china(dp: int):
    z = zipfile.ZipFile(GADM)
    src = json.loads(z.read("gadm41_CHN_3.json"))
    tr = Transformer.from_crs(WGS84, AEA, always_xy=True)
    units, invalid = [], 0
    _used_names = set()
    for f in src["features"]:
        p = f["properties"]
        g = shape(f["geometry"])
        if not g.is_valid:
            invalid += 1
        g = polygonal(g)
        if g.is_empty or g.area == 0:
            continue
        g = g.simplify(CHINA_TOL, preserve_topology=True)
        if g.is_empty:
            continue
        # 名称一律取 GADM 自带的**本地语言名**（`NL_NAME_*`），没有才退回罗马字名。
        # 原先这里还过一层手写的 `CITY_ZH` 译名表——那张表在"地名全量中文化"那次重构里
        # 已经删掉了，留下三处悬空引用（`--dump-units` 一跑就 NameError）。核实过：
        # 现有 基础单元.json 里的「安庆市」这类名字本来就来自 NL_NAME_3，所以直接用即可。
        prov = nm(p, "NL_NAME_1") or p.get("NAME_1") or ""
        city = nm(p, "NL_NAME_2") or p.get("NAME_2") or ""
        prov = ADMIN_ZH.get(prov, prov)
        city = ADMIN_ZH.get(city, city)
        # 只认本地语言名；**不要**退回罗马字 `NAME_3`——那会让市辖区在中文地图上显示
        # "Anqing" 这种英文名。没有本地名的走下面的「<市名>市区」兜底（实测 331 个）。
        name = nm(p, "NL_NAME_3") or ""
        if not name:
            # GADM 的市辖区无中文名（NAME_3 为拼音）；用所属市名兜底，保证可辨识
            base = (city or prov or nm(p, "NL_NAME_1") or p.get("NAME_3") or "").replace("市", "")
            name = (base + "市区") if base else "无名地"
            seen = name
            k = 2
            while seen in _used_names:
                seen = f"{name}·{k}"; k += 1
            name = seen
        _used_names.add(name)
        c = g.centroid
        units.append({
            "n": name, "s": f"{prov}{city}" if city and city != name else prov,
            "prov": prov, "city": city, "kind": "县", "cn": 1,
            "x": round(c.x, 4), "y": round(c.y, 4),
            "a": round(abs(sh_transform(lambda x, y: tr.transform(x, y), g).area) / 1e6),
            "g": rings_int(g, dp),
        })
    # 底图重叠：在等积投影的米制下判定（make_valid 已在 _gj 重建前完成）
    proj = [sh_transform(lambda x, y: tr.transform(x, y), _gj(u, dp)) for u in units]
    tree = STRtree(proj)
    overlaps = []
    for i, g in enumerate(proj):
        for jj in tree.query(g, predicate="intersects"):
            j = int(jj)
            if j <= i:
                continue
            try:
                inter = g.intersection(proj[j])
            except Exception:                        # 少数退化几何跳过，不阻断构建
                continue
            if inter.area > MIN_OVERLAP_M2:
                overlaps.append([i, j, round(inter.area)])
    return units, overlaps, invalid


def _gj(u, dp):
    k = 10 ** dp
    polys = []
    for rr in u["g"]:
        ext = [(rr[0][i] / k, rr[0][i + 1] / k) for i in range(0, len(rr[0]), 2)]
        holes = [[(r[i] / k, r[i + 1] / k) for i in range(0, len(r), 2)] for r in rr[1:]]
        p = Polygon(ext, holes)
        if p.is_empty or p.area == 0:
            continue                                 # 量化后退化的环直接丢弃
        polys.append(p)
    if not polys:
        return Polygon()
    g = MultiPolygon(polys) if len(polys) > 1 else polys[0]
    if not g.is_valid:
        g = g.buffer(0)                              # 量化/简化后自交的通用修法
    if g.is_empty or g.geom_type not in ("Polygon", "MultiPolygon"):
        return Polygon()
    return g


def build_world(dp: int, country_zh: dict | None = None):
    country_zh = country_zh or {}
    z = zipfile.ZipFile(NE1)
    shp = [n for n in z.namelist() if n.endswith(".shp")][0]
    sf = shapefile.Reader(shp=io.BytesIO(z.read(shp)), dbf=io.BytesIO(z.read(shp[:-4] + ".dbf")))
    tr = Transformer.from_crs(WGS84, AEA, always_xy=True)
    units = []
    dropped = 0
    for sr in sf.iterShapeRecords():
        r = sr.record.as_dict()
        iso2 = (r.get("iso_a2") or "").strip()
        g = polygonal(shape(sr.shape.__geo_interface__))
        if g.is_empty or g.area == 0:
            continue
        if not keep_unit(iso2, (r.get("iso_3166_2") or "").strip(), g.centroid.x):
            dropped += 1
            continue
        # 跨日界线的单元（如楚科奇 bbox −180..180）沿窗口缝切开再整段平移，
        # 绝不可逐点折回——那会把几何拉成横贯全图的带（本轮踩过的坑）
        gg = wrap_union(g, LON0, LON1)
        if gg is None:
            dropped += 1
            continue
        # 窗口外的单元整块丢掉（不留"零像元地块"）。`wrap_union` 只在两条经缝上切，
        # 管不了纬度，所以这里按包围盒再判一次。裁之前逐个核过：被丢的都是附录C 范围外
        # 的孤岛（皮特凯恩、5 个南极圈外无人岛），且**没有任何保留单元横跨窗口边**
        # ——否则会被切掉一角而不是整块丢。见 地图/栅格地形数据生成器/mapdata.py 的 SCOPE_* 注释。
        bx = gg.bounds
        if bx[2] < LON0 or bx[0] > LON1 or bx[3] < LAT0 or bx[1] > LAT1:
            dropped += 1
            continue
        g = gg.simplify(WORLD_TOL, preserve_topology=True)
        if g.is_empty:
            continue
        c = g.centroid
        admin = (r.get("admin") or "").strip()
        admin_zh = country_zh.get(admin) or country_zh.get((r.get("adm0_a3") or "").strip(), "")
        name = zh_name(r) or zh_name(r, ("name_local", "name_alt", "gn_name"))
        if not name:
            # 没有译名的极少数（无名属地）：用国家中文名兜底，保证"可读"
            name = admin_zh or admin or "无名地"
        units.append({
            "n": name, "s": admin_zh or admin, "prov": admin_zh or admin,
            "city": "", "kind": "州省", "src": (r.get("name") or "").strip(),
            "x": round(c.x, 4), "y": round(c.y, 4),
            "a": round(abs(sh_transform(lambda x, y: tr.transform(x, y), g).area) / 1e6),
            "g": rings_int(g, dp),
        })
    print(f"  剔除（欧洲/非洲/美洲/南极）{dropped} 个单元")
    return units


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dp", type=int, default=3)
    ap.add_argument("--no-world", action="store_true")
    ap.add_argument("--dump-units", action="store_true", help="另存 地图/地图数据/基础单元.json（供 生成.py 栅格化）")
    args = ap.parse_args()

    for p in (GADM, NE1):
        if not os.path.exists(p):
            print(f"缺少 {p}", file=sys.stderr)
            return 1

    palette = load_palette()
    print(f"调色板：{len(palette)} 地缘 / {sum(len(g['domains']) for g in palette)} 地域")

    country_zh = load_country_zh()
    print(f"国家/地区中文名 {len(country_zh)} 条（admin-0 的 name_zh）")

    print("读中华县级（GADM CHN L3）…")
    cn, overlaps, invalid = build_china(args.dp)
    print(f"  中华 {len(cn)} 单元（无效几何 {invalid} 已修）；底图重叠 {len(overlaps)} 对")

    world = []
    if not args.no_world:
        print("读世界一级政区（Natural Earth admin-1）…")
        world = build_world(args.dp, country_zh)
        print(f"  世界 {len(world)} 单元")

    units = cn + world
    for i, u in enumerate(units):
        u["i"] = i
    xs = [c / (10 ** args.dp) for u in units for rr in u["g"] for r in rr for c in r[0::2]]
    ys = [c / (10 ** args.dp) for u in units for rr in u["g"] for r in rr for c in r[1::2]]
    WORLD_EXTENT = [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]
    print(f"  几何范围 {WORLD_EXTENT}")
    # 种子地块：中华按「市」归并；世界一单元一地块
    plots, seed = [], []
    key2plot = {}
    for u in units:
        if u.get("cn") and u.get("city"):
            k = ("CN", u["prov"], u["city"])
            if k not in key2plot:
                key2plot[k] = len(plots)
                plots.append({"n": u["city"], "u": 0, "seed": 1})
            pid = key2plot[k]
        else:
            pid = len(plots)
            plots.append({"n": u["n"], "u": 0, "seed": 1})
        plots[pid]["u"] += 1
        u["sp"] = pid
    # 去掉计数用的中间键，并导出种子信息
    for p in plots:
        p.pop("u", None)
    # 同名地块加序号（世界一级政区里确有同名者，如三个"连科兰"）
    seen, dup = {}, 0
    for p in plots:
        n = p["n"]
        if n in seen:
            seen[n] += 1
            p["n"] = f"{n}·{seen[n]}"
            dup += 1
        else:
            seen[n] = 1
    seeds = [{"n": p["n"], "seed": 1} for p in plots]
    print(f"基础单元 {len(units)}；种子地块 {len(plots)}（中华按市归并 + 世界一单元一块）；同名加序号 {dup} 个")
    latin = sorted({p["n"] for p in plots if not CJK.search(p["n"])})
    print(f"非中文地块名 {len(latin)} 个" + (f"：{latin[:10]}" if latin else "（全中文）"))

    if args.dump_units:
        with open(OUT_UNITS, "w", encoding="utf-8") as f:
            json.dump({"k": 10 ** args.dp, "extent": WORLD_EXTENT, "units": units,
                       "seeds": seeds, "overlaps": overlaps}, f, ensure_ascii=False, separators=(",", ":"))
        print(f"单元已导出 {OUT_UNITS}  {os.path.getsize(OUT_UNITS)/1048576:.2f} MB")

    # 旧矢量编辑器（地图编辑器.html + tools/editor_template.html）已废弃并删除：
    # 本脚本现在的唯一产物就是 基础单元.json，交给 生成.py 栅格化。
    print("单元已导出，下一步：python 地图/栅格地形数据生成器/生成.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
