#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一次性迁移：把 地图/地图数据/ 下的目录与文件改成中文名（与 tools/mapdata.py 对齐）。

    python tools/rename_mapdata.py --dry       # 只看会怎么改
    python tools/rename_mapdata.py             # 真改

幂等：源不存在而目标已存在时跳过，可以重复跑。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import DATA_DIR                      # noqa: E402

J = os.path.join
D = DATA_DIR
NE, CN, TE, HW, CG, JP, BA = "自然地球", "中华县级", "高程与地表", "唐至明政区", "历史水系", "日本德川", "流域"

# (源, 目标) —— 目录与文件；相对 DATA_DIR
MOVES = [
    # ---- 原始数据：目录 ----
    # ---- 原始数据：Natural Earth ----
    ("raw/natural_earth/ne_10m_coastline.zip", f"原始数据/{NE}/海岸线.zip"),
    ("raw/natural_earth/ne_10m_land.zip", f"原始数据/{NE}/陆地.zip"),
    ("raw/natural_earth/ne_10m_ocean.zip", f"原始数据/{NE}/海洋.zip"),
    ("raw/natural_earth/ne_10m_lakes.zip", f"原始数据/{NE}/湖泊.zip"),
    ("raw/natural_earth/ne_10m_rivers_lake_centerlines.zip", f"原始数据/{NE}/河流.zip"),
    ("raw/natural_earth/ne_10m_geographic_lines.zip", f"原始数据/{NE}/重要经纬线.zip"),
    ("raw/natural_earth/ne_10m_geography_regions_polys.zip", f"原始数据/{NE}/自然地理区.zip"),
    ("raw/natural_earth/ne_10m_admin_0_countries.zip", f"原始数据/{NE}/现代国界_国家.zip"),
    ("raw/natural_earth/ne_10m_admin_1_states_provinces.zip", f"原始数据/{NE}/现代一级政区.zip"),
    ("raw/natural_earth/ne_10m_admin_0_boundary_lines_land.zip", f"原始数据/{NE}/国界线.zip"),
    ("raw/natural_earth/ne_10m_glaciated_areas.zip", f"原始数据/{NE}/冰川区.zip"),
    ("raw/natural_earth/GRAY_HR_SR_OB_DR.zip", f"原始数据/{NE}/灰度晕渲底图.zip"),
    # ---- 原始数据：中华县级 / 高程与地表 ----
    ("raw/modern/gadm41_CHN_3.json.zip", f"原始数据/{CN}/中华县级_GADM41_3.json.zip"),
    ("raw/modern/gadm41_CHN_2.json.zip", f"原始数据/{CN}/中华市级_GADM41_2.json.zip"),
    ("raw/modern/gadm41_CHN_1.json.zip", f"原始数据/{CN}/中华省级_GADM41_1.json.zip"),
    ("raw/modern/datav_counties.geojson", f"原始数据/{CN}/阿里县级_样本.geojson"),
    ("raw/modern/datav_units.csv", f"原始数据/{CN}/阿里县级_台账.csv"),
    ("raw/modern/etopo60_surface.tif", f"原始数据/{TE}/全球高程_ETOPO_60秒.tif"),
    ("raw/modern/lc100_discrete.tif", f"原始数据/{TE}/全球土地覆盖_100米.tif"),
    # ---- 原始数据：Hartwell / CHGIS / 日本 / 流域 ----
    ("raw/chgis_hartwell/v5_Hartwell_2010.zip", f"原始数据/{HW}/Hartwell_唐至明政区_2010.zip"),
    ("raw/chgis_hartwell/README_CHGIS_V5_HARTWELL.txt", f"原始数据/{HW}/说明_CHGIS_V5.txt"),
    ("raw/chgis_hartwell/Hartwell_Reprojection_Info_28sep10.pdf", f"原始数据/{HW}/投影重设说明.pdf"),
    ("raw/chgis_v5/v5_1820_utf.zip", f"原始数据/{CG}/CHGIS_1820_水系.zip"),
    ("raw/chgis_v5/v5_time_prov_pgn_utf.zip", f"原始数据/{CG}/CHGIS_时间序列_省级面.zip"),
    ("raw/chgis_v5/v5_time_pref_pgn_utf.zip", f"原始数据/{CG}/CHGIS_时间序列_府州级面.zip"),
    ("raw/japan/jp_toku_kuni_pgn.ZIP", f"原始数据/{JP}/国_kuni_面.ZIP"),
    ("raw/japan/jp_toku_doo_pgn.ZIP", f"原始数据/{JP}/道_doo_面.ZIP"),
    ("raw/japan/jp_toku_dmyo_pgn.ZIP", f"原始数据/{JP}/藩_dmyo_面.ZIP"),
    ("raw/japan/jp_toku_dmyo_pts.ZIP", f"原始数据/{JP}/藩治点.ZIP"),
    ("raw/hydrosheds/hybas_as_lev06_v1c.zip", f"原始数据/{BA}/亚洲流域_6级.zip"),
    ("raw/hydrosheds/hybas_as_lev07_v1c.zip", f"原始数据/{BA}/亚洲流域_7级.zip"),
    # ---- 加工产物 ----
    ("units.json", "基础单元.json"),
    ("README.md", "说明.md"),
    ("raster/plot_id.png", "栅格/地块编码.png"),
    ("raster/dist_id.png", "栅格/分区编码.png"),
    ("raster/terrain.png", "栅格/地形编码.png"),
    ("raster/ref_edges.png", "栅格/县界参考.png"),
    ("raster/meta.json", "栅格/台账.json"),
    ("raster/_elev_small.npy", "栅格/高程_降采样.npy"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    done = skip = 0
    for src, dst in MOVES:
        s, d = J(D, *src.split("/")), J(D, *dst.split("/"))
        if not os.path.exists(s):
            if os.path.exists(d):
                skip += 1
                continue
            print(f"  ! 源与目标都不存在：{src}")
            continue
        if os.path.exists(d):
            print(f"  ! 目标已存在，跳过：{dst}")
            skip += 1
            continue
        print(f"  {src}  →  {dst}")
        if args.dry:
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.move(s, d)
        done += 1
    # 清掉空目录
    if not args.dry:
        for root, dirs, files in os.walk(D, topdown=False):
            if root == D:
                continue
            if not os.listdir(root):
                os.rmdir(root)
                print(f"  删除空目录 {os.path.relpath(root, D)}")
    print(f"{'（预演）' if args.dry else ''}迁移 {done} 项，跳过 {skip} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
