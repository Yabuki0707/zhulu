#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抓取现代县级行政区划（中华地区底图）。

数据源：阿里 DataV.GeoAtlas（民政部口径的行政区划，含全部县级单元与中文名）
  省列表   https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json
  下级      https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json

策略（数据驱动，不猜 URL）：先取省级列表 → 逐省取下级；
  若下级 level 已是 district（直辖市情形）则直接用，否则再逐市取一次。

产物：
  地图/地图数据/原始数据/中华县级/阿里县级_样本.geojson   县级面（合并）
  地图/地图数据/原始数据/中华县级/阿里县级_台账.csv        层级台账（省/市/县 + adcode）

用法：
  python tools/fetch_china_counties.py            # 全量（约 380 次请求，数分钟）
  python tools/fetch_china_counties.py --limit 3  # 只跑前 3 个省，试跑用
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ⚠️ 路径表（mapdata）与底图指纹（basetag）在 **地图/栅格地形数据生成器/** 里 ——
#    2026-10-10 地形流程那一整包搬去了那里，本文件留在 tools/（它做的是行政图那半）。
#    所以先把那一包挂上 sys.path，再 import 它里面的共用模块。
_GEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "地图", "栅格地形数据生成器")
sys.path.insert(0, _GEN)
from mapdata import ROOT, CN_DIR           # noqa: E402

OUTDIR = CN_DIR
BASE = "https://geo.datav.aliyun.com/areas_v3/bound/{}.json"
BASE_FULL = "https://geo.datav.aliyun.com/areas_v3/bound/{}_full.json"


DELAY = 0.0          # 每次请求后的间隔（秒），--delay 设置


def get(url: str, retries: int = 5) -> dict:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) zhuilu-map/1.0",
                "Referer": "https://datav.aliyun.com/",
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            if DELAY:
                time.sleep(DELAY)
            return data
        except Exception as e:                       # noqa: BLE001
            code = getattr(e, "code", None)
            wait = 8.0 * (i + 1) if code in (403, 429) else 1.5 * (i + 1)
            if i == retries - 1:
                raise
            time.sleep(wait)
            print(f"    重试({code}) {url}", file=sys.stderr)
    return {}


def children(adcode: int) -> list[dict]:
    """取某行政区下一级。带 _full 才会返回下级要素；没有下级时退回自身轮廓。"""
    try:
        d = get(BASE_FULL.format(adcode))
    except Exception:
        return []
    feats = d.get("features") or []
    out = []
    for f in feats:
        p = f.get("properties") or {}
        code = str(p.get("adcode") or "")
        if not code.isdigit():          # 跳过 "100000_JD"（南海九段线）等非行政区要素
            continue
        out.append({"adcode": int(code), "name": p.get("name") or "",
                    "level": p.get("level") or "", "childrenNum": p.get("childrenNum") or 0})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个省（试跑）")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--delay", type=float, default=0.0, help="每次请求后的间隔秒数（限速用）")
    args = ap.parse_args()
    global DELAY
    DELAY = args.delay

    os.makedirs(OUTDIR, exist_ok=True)
    print("取省级列表…")
    provinces = [c for c in children(100000) if c["level"] == "province"]
    print(f"  省级 {len(provinces)} 个")
    if args.limit:
        provinces = provinces[:args.limit]

    units: list[dict] = []          # 台账
    county_codes: list[dict] = []   # 要抓面的县级 {adcode,name,parent}
    for pv in provinces:
        kids = children(pv["adcode"])
        if pv["adcode"] in (710000, 810000, 820000) or all(k["level"] == "district" for k in kids) and kids:
            # 台湾/港澳 或 直辖市：下级已是县级
            for k in kids:
                county_codes.append({"adcode": k["adcode"], "name": k["name"], "parent": pv["name"]})
                units.append({"province": pv["name"], "city": "", "county": k["name"],
                              "adcode": k["adcode"], "level": k["level"]})
            print(f"  {pv['name']}: 直辖/特别 → 县级 {len(kids)}")
            continue
        # 普通省：先市再县
        cities = [k for k in kids if k["level"] == "city"]
        # 省直辖县级（如河南济源）会直接出现在省内
        for k in kids:
            if k["level"] == "district":
                county_codes.append({"adcode": k["adcode"], "name": k["name"], "parent": pv["name"]})
                units.append({"province": pv["name"], "city": "", "county": k["name"],
                              "adcode": k["adcode"], "level": k["level"]})
        for ct in cities:
            county_codes.append({"adcode": ct["adcode"], "name": ct["name"], "parent": pv["name"], "city": True})
            units.append({"province": pv["name"], "city": ct["name"], "county": "", "adcode": ct["adcode"],
                          "level": "city"})
        print(f"  {pv['name']}: 市 {len(cities)}")

    # 展开市 → 县级
    cities = [c for c in county_codes if c.get("city")]
    print(f"取 {len(cities)} 个市的下级（并发 {args.workers}）…")
    def fetch_city(ct):
        kids = children(ct["adcode"])
        return ct, kids
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for n, (ct, kids) in enumerate(ex.map(fetch_city, cities), 1):
            for k in kids:
                county_codes.append({"adcode": k["adcode"], "name": k["name"],
                                     "parent": ct["parent"], "city_name": ct["name"]})
                units.append({"province": ct["parent"], "city": ct["name"], "county": k["name"],
                              "adcode": k["adcode"], "level": k["level"]})
            if n % 40 == 0:
                print(f"    {n}/{len(cities)}")

    real = [c for c in county_codes if not c.get("city")]
    print(f"县级单元 {len(real)} 个，开始取面…")

    def fetch_area(c):
        d = get(BASE.format(c["adcode"]))
        feats = d.get("features") or []
        if not feats:
            return None
        geom = feats[0].get("geometry")
        if not geom:
            return None
        return {"type": "Feature",
                "properties": {"adcode": c["adcode"], "name": c["name"],
                               "province": c["parent"], "city": c.get("city_name", "")},
                "geometry": geom}

    feats = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for n, f in enumerate(ex.map(fetch_area, real), 1):
            if f:
                feats.append(f)
            if n % 100 == 0:
                print(f"    {n}/{len(real)}")

    gj = {"type": "FeatureCollection",
          "meta": {"source": "阿里 DataV.GeoAtlas areas_v3", "fetched": time.strftime("%Y-%m-%d"),
                   "note": "县级行政区划面，中华地区底图"},
          "features": feats}
    p1 = os.path.join(OUTDIR, "阿里县级_样本.geojson")
    with open(p1, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False)
    p2 = os.path.join(OUTDIR, "阿里县级_台账.csv")
    with open(p2, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["province", "city", "county", "adcode", "level"])
        w.writeheader()
        w.writerows(units)
    print(f"\n完成：{len(feats)} 个县级面 → {p1}（{os.path.getsize(p1)/1048576:.1f} MB）")
    print(f"台账 → {p2}（{len(units)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
