# -*- coding: utf-8 -*-
"""契约.py —— 地形流程里的**只读常量**：世界窗口、覆盖/形态码、产物文件名。

**为什么单开一个模块**（2026-10-10 拆管线时加的）：这些常量原来长在 `生成.py` 一个
文件里，谁都能改；一拆成「阶段 × N」之后，如果放在 `管线.py`，阶段模块就得反过来 import 管线
——而管线要 import 阶段表，**转圈**。所以常量独立一层：`管线.py` 与 `阶段/*.py` 都只往下 import
它，依赖是一个有向无环图：

    生成.py / 界面.py  →  管线.py  →  阶段/*.py  →  契约.py / 参数.py / 栅格工具.py
                                                        ↓
                                        terrain / climate / display_class / mapdata …

**这里一个字都不许「顺手改」**：覆盖码顺序进 `base_tag`，文件名是编辑器与说明.md 的接口。
要动就改 ADR＋规格（`docs/地形覆盖判定规格.md`）＋GLOSSARY，再改这里。
"""
from __future__ import annotations

import os

import mapdata as MD
import terrain as TR

# ================================================================ 世界窗口（唯一出处在 mapdata）
LON0, LON1 = MD.SCOPE_LON0, MD.SCOPE_LON1
LAT0, LAT1 = MD.SCOPE_LAT0, MD.SCOPE_LAT1
CELL0 = MD.CELL                      # 默认格边长 1/19° ≈ 5.86 km
OUT = MD.RASTER                      # 产物目录：地图/地图数据/栅格/
RUN_DIR = os.path.join(os.path.dirname(OUT), "运行态")   # 底图.bin 落这里
APP_DIR = os.path.join(MD.ROOT, "地图", "地图编辑器")     # data.js 落这里
UNITS_JSON = MD.UNITS

# ================================================================ 覆盖与形态（顺序即契约）
TERRAIN_LEGEND = TR.COVER_LEGEND     # 20 值：0海洋 1淡湖 2河流 3冰川 ｜ 4密林 5疏林 6灌丛 7草原
                                     #        8草甸 9沼泽 10苔原 ｜ 11盐沼 12滩涂 ｜ 13沙质裸地
                                     #        14砾质裸地 ｜ 15绿洲 ｜ 16海冰 17咸湖 18盐漠 19火山
FORM_LEGEND = TR.FORM_LEGEND         # 4 值：0平原 1丘陵 2高原 3山地
(T_OCEAN, T_LAKE, T_RIVER, T_ICE,
 T_DENSE, T_OPEN, T_SHRUB, T_GRASS, T_FARM, T_MARSH, T_TUNDRA,
 T_SALTM, T_TIDAL, T_SAND, T_GRAVEL, T_OASIS,
 T_SEAICE, T_SALTLAKE, T_SALTPAN, T_VOLCANO) = range(len(TERRAIN_LEGEND))
(F_PLAIN, F_HILL, F_PLATEAU, F_MOUNTAIN) = range(len(FORM_LEGEND))

# 底图指纹里那份图例摘要 = 覆盖 ＋ 形态（⚠️ 必须与 tools/import_editor.py 的 _legend 同口径）
LEGEND_FOR_TAG = list(TERRAIN_LEGEND) + list(FORM_LEGEND)

# ================================================================ 产物文件名
F_PLOT, F_DIST, F_TERRAIN, F_REFV, F_META = (
    "地块编码.png", "分区编码.png", "地形编码.png", "参考顶点.bin", "台账.json")
F_CLIM = "气候编码.png"                                   # 产品层：热量带 × 8 + 干湿
F_ELEV, F_RELIEF, F_VEG = "高程_降采样.npy", "起伏_降采样.npy", "植被_降采样.npy"
F_CLIMATE = "气候_降采样.npy"                             # 柯本类栅格（改规则不必重读 130 MB）
F_WATER = "水体_降采样.npy"
F_DUNE = "沙丘占比_降采样.npy"                            # GSDP30 每格有沙占比（材质判据）
F_PAN = "盐盘占比_降采样.npy"                             # GLWD-3 盐盘/咸水湿地占比（盐漠判据）
F_SALINE = "咸水湖_降采样.npy"                            # GLWD-1 闭合盆地湖（咸湖判据）
F_LAKEPOLY = "湖面清单_降采样.npy"                        # GLWD-1 全部分型码（0非湖/1湖/2水库）
F_ICE = "海冰_降采样.npy"                                 # NSIDC 3 月范围面频率
F_VOLC = "火山_降采样.npy"                                # GVP 全新世火山点

# 河段短于这么多格就不画：低于 6.9 km 栅格的分辨能力，画出来是散点（见 栅格工具.去河散点）
RIVER_MIN_CELLS = 4
