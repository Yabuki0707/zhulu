# -*- coding: utf-8 -*-
"""地图数据的路径与文件名的唯一出处（改名只改这里）。

目录结构（2026-10-07 起：全部改成中文名，一眼看得懂）：

    地图/地图数据/
      说明.md                      本目录的说明（许可、清单、校验值）
      基础单元.json                基础单元 + 种子地块（3682 单元 / 1607 地块，中文名）
      原始数据/                    第三方原始件，只读；由 tools/fetch_map_data.py 获取
        自然地球/                  Natural Earth 10m（底图、河流湖泊、现代国界与一级政区）
        中华县级/                  GADM 4.1 中华县级 + 阿里 DataV 备选
        高程与地表/                ETOPO 全球高程 + Copernicus 土地覆盖
        气候/                      柯本气候分类（Beck et al. 2023，1 km；沙漠/草原判据）
        河流/                      HydroRIVERS v1.0 河网（HydroSHEDS；NE 河流的替代/补充）
        唐至明政区/                Hartwell CHGIS V5（唐 741 → 明 1391）
        历史水系/                  CHGIS 1820 水系与时间序列面（参照）
        日本德川/                  国 / 道 / 藩
        流域/                      HydroBASINS 亚洲流域 6、7 级
      栅格/                        编辑器与游戏读的底层数据（栅格是几何真源）
        地块编码.png               24 位 RGB，码 = R + G×256
        分区编码.png               同上，0 = 无分区；分区隶属于地块
        地形编码.png               8 位灰度 = 地形编码（20 类，见 tools/terrain.py）
        参考顶点.bin               参考层的**矢量顶点**（环表 + 格坐标×8），不是栅格掩膜
        台账.json                  网格几何 + 地形图例 + 陆地口径 + 地块台账
        高程_降采样.npy            备用：降采样高程（改地形分类规则时不必重读原图）
        起伏_降采样.npy            备用：格内极差（分丘陵/山地/高原的依据）
        植被_降采样.npy            备用：LC100 主导类（森林/农田/灌丛…的依据）
        气候_降采样.npy            备用：柯本主导气候类（沙漠/草原/苔原判据的来源）
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "地图", "地图数据")


# ================================================================ 世界窗口与格边长
# **唯一出处**：build_editor（筛单元）与 build_raster（出栅格）都从这里取，免得两处各写一份。
#
# 2026-10-08 裁过一次（原 25°E–236°E / 56°S–82°N），依据是 附录C 的地缘清单：
#   东 236→226：只丢「皮特凯恩群岛」（附录C 的沧溟只列 关岛/密克/波利/夏威，没有它）。
#                再往西切就会切到法属波利尼西亚那几个岛群（它们的经纬互相咬着，矩形切不干净）。
#   南 −56→−48.1：只丢 4 个南极圈外的无人岛（麦夸里/坎贝尔/奥克兰/安蒂波德斯）。
#                 −47 会切到新西兰「南地大区」（南缘 −47.27）；−48.0 恰好切在
#                 「斯奈尔斯群岛」（−48.06…−48.00）的北缘上，把它切成"零像元地块"，
#                 所以取 −48.1 让那一块整块留在窗内。
#   西 25 与北 82 不动：西边最靠外的是土耳其「恰纳卡莱省」（25.66），北边是「克拉斯诺亚尔斯克」（81.29）。
# 裁不掉的两块（矩形办不到，要动就得上非矩形遮罩）：
#   · 非洲（埃及/苏丹）：和 波斯/天竺 同纬度，矩形切它必切波斯；
#   · 法属波利尼西亚的外围岛群：与塔希提的经纬交叠。
SCOPE_LON0, SCOPE_LON1 = 25.0, 226.0
SCOPE_LAT0, SCOPE_LAT1 = -48.1, 82.0
# 格边长：1/19° ≈ 5.86 km。原来是 1/16°（0.0625°≈6.9 km），**细 1.1875 倍**
# （1/16 ÷ 1.2 落在 1/19 与 1/20 之间，取 1/19 更近，且 201°/1/19 与 130°/1/19 都是整数）。
CELL = 1.0 / 19.0


def under(*parts: str) -> str:
    return os.path.join(DATA_DIR, *parts)


# ---------------- 加工产物 ----------------
UNITS = under("基础单元.json")                       # 单元 + 种子地块台账
RASTER = under("栅格")
# 编辑器改完的草稿落这里，由 tools/import_editor.py 合入 RASTER（见 docs/adr/0002）。
# 注意它**不在 地图数据/ 里**：草稿不是数据，是待办的活；路径与 地图数据/ 平级。
STAGING = os.path.join(ROOT, "地图", "待合入")
# 编辑器**唯一**读数据的网址前缀：serve.py 把它虚拟映射到 RASTER，
# 且 STAGING 里有同名文件时草稿优先（"读真源与草稿"）。写进 js/data.js 的就是它。
URL_PREFIX = "/数据/"
# 编辑器**只允许**写这几个文件（受限 POST 的白名单）——地形与参考顶点是管线定稿，不许改
STAGING_FILES = ("地块编码.png", "分区编码.png", "台账.json")
GRID_PLOT = under("栅格", "地块编码.png")
GRID_DIST = under("栅格", "分区编码.png")
GRID_TERRAIN = under("栅格", "地形编码.png")
GRID_REFV = under("栅格", "参考顶点.bin")          # 参考层改矢量顶点（2026-10-07）
GRID_META = under("栅格", "台账.json")
GRID_ELEV = under("栅格", "高程_降采样.npy")
GRID_RELIEF = under("栅格", "起伏_降采样.npy")
GRID_VEG = under("栅格", "植被_降采样.npy")
GRID_CLIMATE = under("栅格", "气候_降采样.npy")

# ---------------- 原始数据 ----------------
RAW = under("原始数据")
NE_DIR = under("原始数据", "自然地球")
CN_DIR = under("原始数据", "中华县级")
FOREIGN_DIR = under("原始数据", "外国县级")
TERRAIN_DIR = under("原始数据", "高程与地表")
CLIMATE_DIR = under("原始数据", "气候")
HARTWELL_DIR = under("原始数据", "唐至明政区")
CHGIS_DIR = under("原始数据", "历史水系")
JAPAN_DIR = under("原始数据", "日本德川")
BASINS_DIR = under("原始数据", "流域")
HYDRO_RIVERS_DIR = under("原始数据", "河流")

# 常用原始件（文件名也中文；URL 里的原文件名见 tools/fetch_map_data.py 清单）
NE_COAST = os.path.join(NE_DIR, "海岸线.zip")
NE_LAND = os.path.join(NE_DIR, "陆地.zip")
NE_OCEAN = os.path.join(NE_DIR, "海洋.zip")
NE_LAKES = os.path.join(NE_DIR, "湖泊.zip")
NE_RIVERS = os.path.join(NE_DIR, "河流.zip")
NE_LINES = os.path.join(NE_DIR, "重要经纬线.zip")
NE_REGIONS = os.path.join(NE_DIR, "自然地理区.zip")
NE_COUNTRIES = os.path.join(NE_DIR, "现代国界_国家.zip")
NE_ADM1 = os.path.join(NE_DIR, "现代一级政区.zip")
NE_BOUNDS = os.path.join(NE_DIR, "国界线.zip")
NE_GRAY = os.path.join(NE_DIR, "灰度晕渲底图.zip")
NE_GLACIATED = os.path.join(NE_DIR, "冰川区.zip")
GADM_CN3 = os.path.join(CN_DIR, "中华县级_GADM41_3.json.zip")
GADM_CN2 = os.path.join(CN_DIR, "中华市级_GADM41_2.json.zip")
GADM_CN1 = os.path.join(CN_DIR, "中华省级_GADM41_1.json.zip")
DATAV_GEOJSON = os.path.join(CN_DIR, "阿里县级_样本.geojson")
DATAV_CSV = os.path.join(CN_DIR, "阿里县级_台账.csv")


def gadm2(zh_name: str) -> str:
    """外国县一级（GADM 4.1 level 2）的本地路径：<国名>_县级_GADM41_2.json.zip。

    可用国家清单（53 个）与字节数在 tools/fetch_map_data.py 的 FOREIGN_L2；
    范围＝游戏的地图范围（亚洲＋大洋洲＋夏威夷，俄罗斯只取乌拉尔以东）。
    """
    return os.path.join(FOREIGN_DIR, f"{zh_name}_县级_GADM41_2.json.zip")

ETOPO_TIF = os.path.join(TERRAIN_DIR, "全球高程_ETOPO_60秒.tif")
LANDCOVER_TIF = os.path.join(TERRAIN_DIR, "全球土地覆盖_100米.tif")
LC100_TIF = LANDCOVER_TIF
# LC100 的满分辨率裸数组曾放在这里（141120 × 362880 × uint8 = 51.2 GB）：本机那份是残件
# （lat −18° 以南整片是 0），**2026-10-07 深夜 已删**。这个常量留在原地只是为了将来若放入一份
# 可信的裸数组时，terrain.validate_raw() 能自动发现并自检启用；没有它就走 TIFF 流式解瓦片。
LC100_RAW = os.path.join(TERRAIN_DIR, "numpy")
# 柯本气候分类（Beck et al. 2023, CC BY 4.0）：沙漠/草原/苔原的**气候判据**来源，
# 取代原先那几个 Natural Earth 手绘沙漠面（见 tools/climate.py、设计笔记03 §14.11）。
KOPPEN_ZIP = os.path.join(CLIMATE_DIR, "koppen_geiger_tif.zip")
HARTWELL_ZIP = os.path.join(HARTWELL_DIR, "Hartwell_唐至明政区_2010.zip")
CHGIS_WATER = os.path.join(CHGIS_DIR, "CHGIS_1820_水系.zip")
CHGIS_PROV = os.path.join(CHGIS_DIR, "CHGIS_时间序列_省级面.zip")
CHGIS_PREF = os.path.join(CHGIS_DIR, "CHGIS_时间序列_府州级面.zip")
JP_KUNI = os.path.join(JAPAN_DIR, "国_kuni_面.ZIP")
JP_DOO = os.path.join(JAPAN_DIR, "道_doo_面.ZIP")
JP_DMYO = os.path.join(JAPAN_DIR, "藩_dmyo_面.ZIP")
JP_PTS = os.path.join(JAPAN_DIR, "藩治点.ZIP")
BASIN6 = os.path.join(BASINS_DIR, "亚洲流域_6级.zip")
BASIN7 = os.path.join(BASINS_DIR, "亚洲流域_7级.zip")


def hydro_rivers(zh_name: str) -> str:
    """HydroRIVERS v1.0 分区片（HydroSHEDS）的本地路径：HydroRIVERS_<分区>.zip。

    与 HydroBASINS 同一家（`原始数据/流域/`）。分区是 HydroSHEDS 自己划的，**不是我们选的**：
    亚洲片只覆盖 57.6°E–150.5°E，所以本管线（25°E–236°E）要拼 亚洲/西伯利亚/欧洲/澳洲 四片。
    缺哪片只影响那片有没有 HydroRIVERS 的河——Natural Earth 那一层仍在兜底。
    分区名与字节数见 tools/fetch_map_data.py 的 HYDRO_RIVERS。
    """
    return os.path.join(HYDRO_RIVERS_DIR, f"HydroRIVERS_{zh_name}.zip")


def missing() -> list:
    """自检：管线必需的东西在不在。"""
    need = [UNITS, GRID_PLOT, GRID_TERRAIN, NE_ADM1, GADM_CN3]
    return [p for p in need if not os.path.exists(p)]
