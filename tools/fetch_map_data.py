#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""地图原始数据下载器（幂等、可断点续传）。

用法：
    python tools/fetch_map_data.py --list                # 列出清单与本地状态
    python tools/fetch_map_data.py --group core          # 下载核心集（底图 + 汉地行政图）
    python tools/fetch_map_data.py --group basins        # 下载流域底（边地地块划分用）
    python tools/fetch_map_data.py --group foreign       # 下载外国县一级（53 国，约 15 MB）
    python tools/fetch_map_data.py --group all

全部落到 地图/地图数据/原始数据/。已存在且大小相符的文件跳过；不符则续传。
许可与出处见 地图/地图数据/说明.md。
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import RAW                  # noqa: E402

NE = "https://naciscdn.org/naturalearth/10m"
DV = "https://dataverse.harvard.edu/api/access/datafile"

# group, subdir, filename, url, 期望字节数(0=不校验), 说明
ITEMS = [
    # ---- 底图：Natural Earth 10m（公有领域，可商用）----
    ("core", "自然地球", "海岸线.zip",                    f"{NE}/physical/ne_10m_coastline.zip", 3069451, "海岸线"),
    ("core", "自然地球", "陆地.zip",                         f"{NE}/physical/ne_10m_land.zip", 3269070, "陆地"),
    ("core", "自然地球", "海洋.zip",                        f"{NE}/physical/ne_10m_ocean.zip", 3189765, "海洋"),
    ("core", "自然地球", "湖泊.zip",                        f"{NE}/physical/ne_10m_lakes.zip", 2349685, "湖泊"),
    ("core", "自然地球", "河流.zip",      f"{NE}/physical/ne_10m_rivers_lake_centerlines.zip", 2079507, "河流"),
    ("core", "自然地球", "重要经纬线.zip",             f"{NE}/physical/ne_10m_geographic_lines.zip", 31268, "重要经纬/回归线"),
    ("core", "自然地球", "自然地理区.zip",      f"{NE}/physical/ne_10m_geography_regions_polys.zip", 2038519, "自然地理区（沙漠/高原等）"),
    ("core", "自然地球", "现代国界_国家.zip",            f"{NE}/cultural/ne_10m_admin_0_countries.zip", 4930492, "现代国界（边地底）"),
    ("core", "自然地球", "现代一级政区.zip",     f"{NE}/cultural/ne_10m_admin_1_states_provinces.zip", 14909524, "现代一级政区（边地底）"),
    ("core", "自然地球", "国界线.zip",  f"{NE}/cultural/ne_10m_admin_0_boundary_lines_land.zip", 1036202, "国界线"),
    ("core", "自然地球", "灰度晕渲底图.zip",                    f"{NE}/raster/GRAY_HR_SR_OB_DR.zip", 91669338, "灰度晕渲底图（现成栅格）"),

    # ---- 汉地行政图：Hartwell 唐→明 近历史政区（CC0 / 见 README 许可冲突）----
    ("core", "唐至明政区", "Hartwell_唐至明政区_2010.zip",                   f"{DV}/2542563", 80979494, "唐741/宋1080/宋金1200/元1290/明1391 州·县·道·路面"),
    ("core", "唐至明政区", "说明_CHGIS_V5.txt",           f"{DV}/2867263", 3664, "图层命名与分级说明"),
    ("core", "唐至明政区", "投影重设说明.pdf", f"{DV}/2867264", 31173, "投影与编码说明（Xian80 GK19 / BIG5）"),

    # ---- 历史水系与明清参照：CHGIS V5 ----
    ("core", "历史水系", "CHGIS_1820_水系.zip",           f"{DV}/2691189", 12031609, "1820 省/府/县 + 海岸线/江河/湖泊（UTF8，全套）"),
    ("core", "历史水系", "CHGIS_时间序列_省级面.zip",  f"{DV}/2799650", 25984437, "时间序列 省级面 222BCE–1911（一级政区演进）"),
    ("core", "历史水系", "CHGIS_时间序列_府州级面.zip",  f"{DV}/2691132", 24543715, "时间序列 府州级面（1350 后较全，宋以前有缺口→只作校验）"),

    # ---- 海东：日本德川 国/道/藩 ----
    ("core", "日本德川", "国_kuni_面.ZIP", f"{DV}/3004363", 174468, "国（kuni）面"),
    ("core", "日本德川", "道_doo_面.ZIP",  f"{DV}/3004366", 254083, "道（doo）面"),
    ("core", "日本德川", "藩_dmyo_面.ZIP", f"{DV}/3004365", 332352, "藩（daimyo）面"),
    ("core", "日本德川", "藩治点.ZIP", f"{DV}/3004364", 26576, "藩治点"),

    # ---- 流域底：边地/远域地块划分（禁止 Voronoi 的替代骨架）----
    ("basins", "流域", "亚洲流域_6级.zip", "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_as_lev06_v1c.zip", 12871684, "亚洲流域 6 级（约数百单元）"),
    ("basins", "流域", "亚洲流域_7级.zip", "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_as_lev07_v1c.zip", 20966344, "亚洲流域 7 级（更细）"),

    # ---- 现代行政底图：中华用县（level 3），世界用 NE admin-1（已在 core 组）----
    ("modern", "中华县级", "中华县级_GADM41_3.json.zip", "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_CHN_3.json.zip", 2714936, "中华县级面（GADM 4.1，2421 个）← 编辑器底料"),
    ("modern", "中华县级", "中华市级_GADM41_2.json.zip", "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_CHN_2.json.zip", 1417217, "中华市级面（备查）"),
    ("modern", "中华县级", "中华省级_GADM41_1.json.zip", "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_CHN_1.json.zip", 714043, "中华省级面（备查）"),
]

# ---- 外国县一级：GADM 4.1 level 2（与中华县级同源、同许可）----
# 范围＝游戏的地图范围（亚洲＋大洋洲＋夏威夷；俄罗斯只取乌拉尔以东），见 tools/build_editor.py 的 keep_unit()。
# 只列**真的存在二级政区**的国家（53 个，合计约 15 MB）；新加坡/卡塔尔/以色列/巴林/科威特/塞浦路斯/亚美尼亚
# 一级即最细，NE admin-1 已经给了；马尔代夫/基里巴斯/纽埃/皮特凯恩等只有一级，也由 NE admin-1 覆盖。
# 许可：GADM 非商用（本项目非商业可用；与中华底图同一笔账）。
FOREIGN_L2 = [
    ("AFG", "阿富汗", 144819),
    ("ARE", "阿拉伯联合酋长国", 46421),
    ("ASM", "美属萨摩亚", 2245),
    ("AUS", "澳大利亚", 1373710),
    ("AZE", "阿塞拜疆", 41197),
    ("BGD", "孟加拉国", 179133),
    ("BRN", "文莱", 7541),
    ("BTN", "不丹", 76079),
    ("FJI", "斐济", 54866),
    ("FSM", "密克罗尼西亚联邦", 15890),
    ("GEO", "格鲁吉亚", 35443),
    ("IDN", "印度尼西亚", 1324235),
    ("IND", "印度", 1489046),
    ("IRN", "伊朗", 171886),
    ("IRQ", "伊拉克", 57637),
    ("JOR", "约旦", 15462),
    ("JPN", "日本", 680963),
    ("KAZ", "哈萨克斯坦", 112439),
    ("KGZ", "吉尔吉斯斯坦", 58451),
    ("KHM", "柬埔寨", 148072),
    ("KOR", "大韩民国", 257706),
    ("LAO", "老挝", 91989),
    ("LBN", "黎巴嫩", 24503),
    ("LKA", "斯里兰卡", 135894),
    ("MMR", "缅甸", 216318),
    ("MNG", "蒙古国", 163509),
    ("MYS", "马来西亚", 162608),
    ("NCL", "新喀里多尼亚", 34953),
    ("NPL", "尼泊尔", 58740),
    ("NZL", "新西兰", 303872),
    ("OMN", "阿曼", 25341),
    ("PAK", "巴基斯坦", 85410),
    ("PHL", "菲律宾", 550610),
    ("PNG", "巴布亚新几内亚", 185022),
    ("PRK", "朝鲜民主主义人民共和国", 108158),
    ("RUS", "俄罗斯", 2291985),
    ("SAU", "沙特阿拉伯", 282986),
    ("SLB", "所罗门群岛", 108593),
    ("SYR", "叙利亚", 28750),
    ("THA", "泰国", 710743),
    ("TJK", "塔吉克斯坦", 37360),
    ("TKM", "土库曼斯坦", 30023),
    ("TLS", "东帝汶", 33045),
    ("TON", "汤加", 8743),
    ("TUR", "土耳其", 328468),
    ("TWN", "中华民国", 32185),
    ("USA", "美国", 2553202),
    ("UZB", "乌兹别克斯坦", 95626),
    ("VNM", "越南", 560161),
    ("VUT", "瓦努阿图", 35983),
    ("WLF", "瓦利斯和富图纳", 2010),
    ("WSM", "萨摩亚", 7751),
    ("YEM", "也门", 108777),
]
ITEMS += [(("foreign", "外国县级", f"{zh}_县级_GADM41_2.json.zip",
            f"https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_{iso}_2.json.zip", n,
            f"{zh}二级政区面（GADM 4.1 level 2）"))
          for iso, zh, n in FOREIGN_L2]


def human(n: int) -> str:
    return f"{n / 1048576:.1f}MB" if n >= 1048576 else f"{n / 1024:.0f}KB"


def local_path(subdir: str, filename: str) -> str:
    return os.path.join(RAW, subdir, filename)


def state(item) -> str:
    _, sub, name, _, want, _ = item
    p = local_path(sub, name)
    if not os.path.exists(p):
        return "缺"
    got = os.path.getsize(p)
    if want and got == want:
        return "有"
    if want and got != want:
        return f"残({human(got)})"
    return "有"


def download(item, retries: int = 3) -> bool:
    _, sub, name, url, want, desc = item
    p = local_path(sub, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)

    if os.path.exists(p):
        got = os.path.getsize(p)
        if want and got == want:
            print(f"  跳过（已完整） {name}")
            return True
        if not want:
            print(f"  跳过（已存在） {name}")
            return True
        # 断点续传
        resume = got
    else:
        resume = 0

    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": "zhuilu-map-fetch/1.0"})
        if resume:
            req.add_header("Range", f"bytes={resume}-")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                mode = "ab" if resume else "wb"
                total = resume + int(r.headers.get("Content-Length") or 0)
                done = resume
                with open(p, mode) as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            pct = done * 100 // total
                            sys.stdout.write(f"\r  {name} {pct:3d}%  {human(done)}/{human(total)}   ")
                            sys.stdout.flush()
            sys.stdout.write("\r" + " " * 70 + "\r")
            got = os.path.getsize(p)
            if want and got != want:
                print(f"  大小不符 {name}: {got} != {want}（重试 {attempt}）")
                resume = got
                continue
            print(f"  完成 {name}  {human(got)}")
            return True
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"  失败 {name}: {e}（重试 {attempt}/{retries}）")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="core",
                    choices=["core", "basins", "modern", "foreign", "all"])
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print(f"{'状态':<10}{'组':<8}{'大小':<9}文件")
        for it in ITEMS:
            _, sub, name, _, want, desc = it
            print(f"{state(it):<10}{it[0]:<8}{human(want) if want else '?':<9}{sub}/{name}  — {desc}")
        return 0

    want_groups = {"core", "basins", "modern", "foreign"} if args.group == "all" else {args.group}
    todo = [it for it in ITEMS if it[0] in want_groups]
    print(f"目标目录: {RAW}")
    print(f"待处理 {len(todo)} 项")
    fail = [it[2] for it in todo if not download(it)]
    print()
    if fail:
        print("未完成:", ", ".join(fail))
        return 1
    print("全部就绪。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
