# -*- coding: utf-8 -*-
"""地图数据的路径与文件名的唯一出处（改名只改这里）。

目录结构（2026-10-07 起：全部改成中文名，一眼看得懂）：

    地图/地图数据/
      说明.md                      本目录的说明（许可、清单、校验值）
      基础单元.json                基础单元 + 种子地块（3682 单元 / 1607 地块，中文名）
      原始数据/                    第三方原始件，只读；由 地图/栅格地形数据生成器/fetch_map_data.py 获取
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
        地形编码.png               8 位灰度 = 地形编码（20 类，见 地图/栅格地形数据生成器/terrain.py）
        参考顶点.bin               参考层的**矢量顶点**（环表 + 格坐标×8），不是栅格掩膜
        台账.json                  网格几何 + 地形图例 + 陆地口径 + 地块台账
        高程_降采样.npy            备用：降采样高程，float32（改形态门槛时不必重读 ETOPO）
        起伏_降采样.npy            备用：格内极差，float32（分丘陵/山地/高原的依据）
                                   ⚠️ 存 float32 不存 int16：门槛是 `起伏 > 350` 这种硬比较，
                                   取整会在阈值附近翻掉约 0.2% 的格、拿它重算会看到假警报
        植被_降采样.npy            备用：LC100 主导类（森林/农田/灌丛…的依据）
        气候_降采样.npy            备用：柯本主导气候类（沙漠/草原/苔原判据的来源）
"""
from __future__ import annotations

import os

# ⚠️ 本文件 2026-10-10 从 `tools/` 搬进 `地图/栅格地形数据生成器/`（**深了一层**），
#    所以仓库根要往上数**三层**。改错的后果是路径全指到 `地图/` 上——那不是报错，
#    是去别处建目录、把产物写歪，所以下面留一条断言把它逼出来。
_这里 = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_这里))
assert os.path.isdir(os.path.join(ROOT, "地图")) and os.path.isdir(os.path.join(ROOT, "tools")),     f"仓库根算错了：{ROOT}（mapdata.py 在 地图/栅格地形数据生成器/ 下，根要往上数三层）"
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
GRID_DUNE = under("栅格", "沙丘占比_降采样.npy")     # GSDP30 每格有沙占比（沙漠/戈壁 的判据）
# v9 新加的四个派生量（每个都有自己的缓存标记；管线只读缓存，只有 地图/栅格地形数据生成器/glwd.py 需要 GDAL）
GRID_PAN = under("栅格", "盐盘占比_降采样.npy")      # GLWD-3 第 7 类（盐盘/咸水湿地）每格占比
GRID_SALINE = under("栅格", "咸水湖_降采样.npy")     # GLWD-1 闭合盆地湖（MGLD_TYPE=closed）
GRID_ICE = under("栅格", "海冰_降采样.npy")          # NSIDC 3 月范围面 30 年命中频率 ≥ 50%
GRID_LAKEPOLY = under("栅格", "湖面清单_降采样.npy")   # GLWD-1 全部湖面（"什么算湖"的唯一口径）
GRID_VOLC = under("栅格", "火山_降采样.npy")         # GVP 全新世火山点

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
DUNE_DIR = under("原始数据", "沙丘形态")
LAKE_DIR = under("原始数据", "湖泊湿地")            # GLWD level 1/2/3
ICE_DIR = under("原始数据", "海冰")                 # NSIDC Sea Ice Index 逐月范围面
VOLCANO_DIR = under("原始数据", "火山")             # Smithsonian GVP 全新世火山


def ice_zips() -> list:
    """NSIDC Sea Ice Index 逐月范围面（北半球 3 月，1981–2010 共 30 个）。"""
    import glob
    return sorted(glob.glob(os.path.join(ICE_DIR, "extent_N_*03_polygon_v4.0.zip")))

# 常用原始件（文件名也中文；URL 里的原文件名见 地图/栅格地形数据生成器/fetch_map_data.py 清单）
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

    可用国家清单（53 个）与字节数在 地图/栅格地形数据生成器/fetch_map_data.py 的 FOREIGN_L2；
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
# 取代原先那几个 Natural Earth 手绘沙漠面（见 地图/栅格地形数据生成器/climate.py、设计笔记03 §14.11）。
KOPPEN_ZIP = os.path.join(CLIMATE_DIR, "koppen_geiger_tif.zip")
# GSDP30：全球 30 m 沙丘形态图（Zenodo doi:10.5281/zenodo.13907012，CC BY 4.0，须署名）。
# **沙漠／戈壁的判据来源**——它的图例自带二元分界（0–8/10 沙丘与沙席＝沙；9 Others＝砾石/裸岩）。
# 气候数据分不开沙与砾（塔克拉玛干与蒙古戈壁同属 BWk），土壤数据也分不开（实测试过，见
# 地图/栅格地形数据生成器/sanddunes.py 抬头）。取点见 地图/栅格地形数据生成器/sanddunes.py，许可与出处见 地图/地图数据/说明.md。
DUNE_ZIP = os.path.join(DUNE_DIR, "GSDP30.zip")
# GLWD（WWF／卡塞尔大学；限非商业科研/保护/教育用途，本项目非商业可用）
GLWD1_ZIP = os.path.join(LAKE_DIR, "GLWD-level1.zip")
GLWD3_ADF = os.path.join(LAKE_DIR, "glwd_3_adf", "glwd_3")   # ArcInfo 网格（rasterio/GDAL 读）
VOLCANO_GEOJSON = os.path.join(VOLCANO_DIR, "GVP_全新世火山.geojson")
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
    分区名与字节数见 地图/栅格地形数据生成器/fetch_map_data.py 的 HYDRO_RIVERS。
    """
    return os.path.join(HYDRO_RIVERS_DIR, f"HydroRIVERS_{zh_name}.zip")


def missing() -> list:
    """自检：管线必需的东西在不在。"""
    need = [UNITS, GRID_PLOT, GRID_TERRAIN, NE_ADM1, GADM_CN3]
    return [p for p in need if not os.path.exists(p)]
