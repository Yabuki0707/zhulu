#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""地图原始数据下载器（幂等、可断点续传）。

用法：
    python 地图/栅格地形数据生成器/fetch_map_data.py --list                # 列出清单与本地状态
    python 地图/栅格地形数据生成器/fetch_map_data.py --group core          # 下载核心集（底图 + 汉地行政图）
    python 地图/栅格地形数据生成器/fetch_map_data.py --group basins        # 下载流域底（边地地块划分用）
    python 地图/栅格地形数据生成器/fetch_map_data.py --group foreign       # 下载外国县一级（53 国，约 15 MB）
    python 地图/栅格地形数据生成器/fetch_map_data.py --group climate       # 下载柯本气候分类（130 MB，沙漠判据）
    python 地图/栅格地形数据生成器/fetch_map_data.py --group rivers        # 下载 HydroRIVERS 河网（254 MB，四片）
    python 地图/栅格地形数据生成器/fetch_map_data.py --group soil          # 下载 GSDP30 沙丘形态（115 MB，沙/砾判据）
    python 地图/栅格地形数据生成器/fetch_map_data.py --group all

全部落到 地图/地图数据/原始数据/。已存在且大小相符的文件跳过；不符则续传。
许可与出处见 地图/地图数据/说明.md。
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request
import urllib.error
import urllib.parse

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

# ---- 气候：柯本气候分类（Beck et al. 2023，CC BY 4.0）----
# 「沙漠 = LC100 裸地 ∧ 干旱气候」的判据来源，取代 Natural Earth 的手绘沙漠面
# （见 地图/栅格地形数据生成器/climate.py 与 设计笔记03 §14.11）。包里 73 个文件，管线只用现值期那一幅：
#   1991_2020/koppen_geiger_0p00833333.tif
# ⚠️ 这个源在 AWS WAF 后面：裸的 urllib UA 只会拿到 `x-amzn-waf-action: challenge`
#    （HTTP 202 + 0 字节）。必须带浏览器那一套请求头，见下面的 HOST_HEADERS。
ITEMS += [("climate", "气候", "koppen_geiger_tif.zip",
           "https://figshare.com/ndownloader/files/61012822", 130618411,
           "柯本气候分类 1901–2099（Beck et al. 2023, CC BY 4.0）；现值期 1991–2020 的 1 km 那幅是干旱判据")]

# ---- 河网：HydroRIVERS v1.0（HydroSHEDS）----
# Natural Earth 的河流层全库只有 1,473 个要素，长江入海段（江阴→崇明，约 230 km）
# **一条线都没有**——这是覆盖度问题，缩小像元救不了。HydroRIVERS 光亚洲片就有
# 1,428,959 条河段，且上下游共用节点（天然接得上，没有"端点缝"）。见 地图/栅格地形数据生成器/rivers.py。
# HydroSHEDS 的分区是它自己划的、**不是我们选的**：亚洲片只覆盖 57.6°E–150.5°E，
# 所以要拼 亚洲＋西伯利亚＋欧洲＋澳洲 四片，才盖住本管线窗口（25°E–236°E）的主要陆地。
# 许可：免费含商用，**禁作独立产品再分发**（随产品分发可以）——与已有的 流域/ 同一笔账。
# 另有一片 `ar`（北极，22 MB）**故意不列**：它只覆盖加拿大北极群岛，那里的河流量全在
# 默认阈值 100 m³/s 之下，实测"画 0 段"。若要把阈值降到 50 以下，按同样格式加回来：
#   ("北极", "ar", 22048523, "...")  →  https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_ar_shp.zip
HYDRO_RIVERS = [
    ("亚洲", "as", 90510995, "东亚/南亚/东南亚/日本：长江、黄河、湄公河…（窗口内主力）"),
    ("西伯利亚", "si", 47301335, "叶尼塞/勒拿/鄂毕（北荒、辽海、瀚海）"),
    ("欧洲", "eu", 67648957, "含安纳托利亚/高加索（波斯西缘、河中北缘）"),
    ("澳洲", "au", 48770754, "澳大利亚与太平洋岛屿（红洲、南洋东缘）"),
]
ITEMS += [(("rivers", "河流", f"HydroRIVERS_{zh}.zip",
            f"https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_{code}_shp.zip", n,
            f"HydroRIVERS v1.0 河网·{zh}（HydroSHEDS）—— {desc}"))
          for zh, code, n, desc in HYDRO_RIVERS]

# ---- 地表材质：GSDP30 全球 30 m 沙丘形态图（沙 / 砾岩 的判据，CC BY 4.0）----
# 要分的是**沙质荒漠（erg）与砾／岩质荒漠（reg、戈壁）**。气候数据分不开它们——塔克拉玛干与
# 蒙古戈壁同属柯本 BWk；**土壤数据也分不开**（试过 ISRIC SoilGrids 2.0 的粗碎屑与沙粒占比，
# 见 地图/栅格地形数据生成器/sanddunes.py 抬头：塔克拉玛干读 177‰ 而戈壁读 171‰，沙粒占比更糟）。沙漠里实测
# 土壤剖面极少，模型在那儿是区域均值回归，边界是假的。**沙是与不是沙，遥感看得见。**
#
# GSDP30 = Gao et al. 的全球沙丘形态图（Zenodo doi:10.5281/zenodo.13907012），Landsat 合成 +
# 深度学习，331 片 460.8 km 见方的 EPSG:3857 瓦片。**它的图例自己就是二元判据**：
# 0–8/10 十类沙丘形态与沙席＝沙，9「Others」＝"没有被沙覆盖的地面（砾石、裸岩、农田…）"。
# 实测：沙海 70–97%（塔克拉玛干 93、辛普森 97、鲁卜哈利 84），砾漠 0–20%（蒙古戈壁 7.7、
# 内盖夫 0、卢特 8.3）。见 地图/栅格地形数据生成器/sanddunes.py。取样口径与其它层一致（每格有沙像素占比）。
# 许可：CC BY 4.0（须署名）。见 地图/地图数据/说明.md §三。
ITEMS += [("soil", "沙丘形态", "GSDP30.zip", 
           "https://zenodo.org/records/13907012/files/GSDP30.zip?download=1", 115287854,
           "GSDP30 全球 30 m 沙丘形态图 —— 沙漠/戈壁 的判据（Zenodo，CC BY 4.0）")]


# ---- v9 追加的三份（`docs/adr/0014`）----
# 海冰：NSIDC「Sea Ice Index v3」逐月范围面（**公用领域**）。取北半球 **3 月**（冰最多）1981–2010
# 共 30 个，由 地图/栅格地形数据生成器/ice.py 叠成"出现频率 ≥ 50%"——该产品**没有现成的"中位"文件**，得自己叠。
# ⚠️ 渤海海冰不在这个 25 km 网格产品里（渤海最宽处才 ~70 km），已知缺口。
_N_ICE_BASE = ("https://noaadata.apps.nsidc.org/NOAA/G02135/north/monthly/"
                "shapefiles/shp_extent/03_Mar/")
_N_ICE = [(f"extent_N_{y}03_polygon_v4.0.zip",
           f"{_N_ICE_BASE}extent_N_{y}03_polygon_v4.0.zip")
          for y in range(1981, 2011)]
ITEMS += [(("ice", "海冰", nm, u, 0, f"NSIDC 海冰 3 月范围面 {nm[8:13]}（Sea Ice Index v3，公有领域）"))
          for nm, u in _N_ICE]
# 湖沼：GLWD（WWF／卡塞尔大学）。**许可：限非商业的科研/保护/教育用途**——本项目非商业可用。
#   level1：3,721 个大湖面（带 MGLD_TYPE = open/closed，**闭合盆地 → 咸水湖**的判据）
#   level3：30 弧秒全球栅格，12 类，**第 7 类 = 盐盘/咸水湿地 → 盐漠**
#   ⚠️ level3 是 ArcInfo 二进制网格（.adf），**只有 地图/栅格地形数据生成器/glwd.py 用 rasterio/GDAL 读**，
#      管线只读它落下的 .npy 缓存 —— 所以管线本身仍然不依赖 GDAL。
ITEMS += [
    ("lake", "湖泊湿地", "GLWD-level1.zip",
     "https://c402277.ssl.cf1.rackcdn.com/publications/16/files/original/GLWD-level1.zip?1343838522",
     6757519, "GLWD-1 全球大湖面（≥50 km²，含闭合盆地判据）—— 咸水湖的来源"),
    ("lake", "湖泊湿地", "GLWD-level3.zip",
     "https://c402277.ssl.cf1.rackcdn.com/publications/18/files/original/GLWD-level3.zip?1343838716",
     9284786, "GLWD-3 全球湿地栅格（30 弧秒 12 类）—— 第 7 类盐盘 = 盐漠的来源"),
]
# 火山：Smithsonian GVP 的 WFS 直接给 GeoJSON（**CC BY 4.0**）。全新世火山 1,214 座，窗口内 604。
ITEMS += [("volcano", "火山", "GVP_全新世火山.geojson",
           "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows?service=WFS&version=2.0.0"
           "&request=GetFeature&typeName=GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes"
           "&outputFormat=application/json&count=100000",
           2505828, "Smithsonian GVP 全新世火山（GeoJSON）—— 火山类的来源")]


# 需要浏览器请求头的源（host 后缀 → 头字典）。figshare 前面挂着 AWS WAF 的人机校验，
# 裸 UA 一律 202 + 0 字节；实测带这一套就 200。
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HOST_HEADERS = {
    "figshare.com": {
        "User-Agent": BROWSER_UA,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    },
    # Zenodo：裸 UA 会 403（它要求走签名跳转），带浏览器 UA 才 200；偶尔还回 504，
    # 所以下载器那份重试是必要的（第一次下 GSDP30 就撞上过 504）。
    "zenodo.org": {
        "User-Agent": BROWSER_UA,
        "Accept": "*/*",
    },
}


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
        host = urllib.parse.urlsplit(url).netloc.lower()
        hdrs = {"User-Agent": "zhuilu-map-fetch/1.0"}
        for suffix, extra in HOST_HEADERS.items():
            if host == suffix or host.endswith("." + suffix):
                hdrs.update(extra)
        req = urllib.request.Request(url, headers=hdrs)
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
                    choices=["core", "basins", "modern", "foreign", "climate",
                             "rivers", "soil", "ice", "lake", "volcano", "all"])
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print(f"{'状态':<10}{'组':<8}{'大小':<9}文件")
        for it in ITEMS:
            _, sub, name, _, want, desc = it
            print(f"{state(it):<10}{it[0]:<8}{human(want) if want else '?':<9}{sub}/{name}  — {desc}")
        return 0

    want_groups = ({"core", "basins", "modern", "foreign", "climate", "rivers", "soil",
                    "ice", "lake", "volcano"}
                   if args.group == "all" else {args.group})
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
