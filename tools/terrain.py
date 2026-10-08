# -*- coding: utf-8 -*-
"""地形分类（16 类）：高程 + 起伏 + Copernicus LC100 土地覆盖 + Natural Earth 掩膜。

    from terrain import LEGEND, read_elevation, veg_from_landcover, landform, classify

真源口径（每一条都是踩过坑之后才这么定的）：

  陆地 = **Natural Earth 10m 陆地 ∪ 湖泊 ∪ 冰川区**（格心命中，`rasterize_union`）
         · 不用「ETOPO > 0」：吐鲁番（−154 m）、里海（−28 m）、死海（−430 m）会被判成海；
         · 不用「plot_id > 0」：欧/非/美洲整片（撒哈拉、刚果、东欧）会被判成海。
         海洋 = 这个掩膜的补集，**全管线只有这一处口径**（地块层也按它裁）。
  高程 = ETOPO 2022 60s（1 弧分）在窗口内按格做面积平均（BOX）。
  起伏 = 同一窗口按格取 max−min（0.0625° 的格 ≈ 6.9 × 5.3 km 的相对高差）——
         分丘陵 / 山地 / 高原全靠它，只看海拔分不出来（青藏 4500 m 是"面"，
         喜马拉雅 4500 m 是"脊"，四川盆地 400 m 且平坦是"平原"）。
  植被 = Copernicus LC100 离散分类（80 N–60 S，100 m），每格取 8 × 3 = 24 个样本。
         数据源是 `全球土地覆盖_100米.tif`（Deflate 分块，只解用得到的瓦片）。
         那份 48.8 GB 的裸数组（`原始数据/高程与地表/numpy`）已确认是**残件**并已删除：
         它在 lat −18° 以南整片是 0（澳洲、新西兰、南部非洲全废），而字节数恰好等于
         141120 × 362880。若将来放入一份新的裸数组，`validate_raw` 会先拿 6 个已知地点
         与 TIFF 逐点比对，对不上就不用，自动走 TIFF 流式解瓦片。

### 森林怎么定（v2：**不在这里定，交给气候层**）

v1 用一套「纬度 + 海拔」连续权重把 LC100 的林型族判成雨林／阔叶林／针叶林，为的是
避开"23.5° 一刀切"那条横穿两广的直线。v2 把林型合并成**一个「森林」**之后，那套
权重制整段删掉：**林型的差别是气候带的差别，就该由气候层（柯本热量带）来分**。
四种绿由 `森林 × 热量带` 当场派生（`tools/display_class.py`），存储里只有「森林」。

代价是一条已知的小偏差：低纬的人工针叶林（马尾松、杉木、日本人工林——LC100 也标成
针叶林）在气候看来是亚热带，会显示成常绿阔叶。实测面积极小，且换气候数据不必重做地形
——这正是这一层分离要买的东西。

### 地形表（14 类；2026-10-08 契约 v2，见 docs/adr/0006）

    0 海洋 1 湖泊 2 河流 3 冰川          ← 水冰
    4 森林 5 草原 6 荒漠 7 沼泽 8 滩涂 9 绿洲   ← 覆盖
    10 平原 11 丘陵 12 高原 13 山地       ← 形态

相对 v1 的 16 类，**砍掉的都是气候，不是地形**：

  · **针叶林 / 阔叶林 / 雨林 / 混交 → 一个「森林」**。林型的差别全在气候带上（雨林与泰加林
    的区别不在"长着什么"，而在"长在哪个气候带"）。合并后**那套「纬度 + 海拔权重制」林型
    判定整段删掉**（`_forest_label` / `climate_weights` / `FAM_AFFINITY`）——它的活改由
    柯本热量带干，且改得更准：日本海侧雪国的阔叶林与西伯利亚的泰加林，柯本本来就分了带。
    视觉不丢：编辑器按 `森林 × 热量带` 当场派生出四种绿（见 tools/display_class.py）。
  · **沙漠 → 不存储**。它 = `荒漠 ∧ 干旱气候`，是本表与气候层的乘积（v1 的沙漠规则已经是
    「LC100 裸地 ∧ 柯本干旱 ∧ 海拔 < 3500 m」——它本来就在拿气候判，只是把结果落进了存储）。
  · **苔原 → 不存储**。它 = `草原/荒漠 ∧ 寒带`。`设计笔记03` §14.12 那个「苔原走 NE 手绘面
    还是柯本 ET」的悬案到此结案：两边都不走。
  · **裸地 → 改名「荒漠」，语义收紧为干旱区的裸露与稀疏植被**。v1 里它被沙漠规则掏空到
    2,687 格（0.028%，名存实亡）；非干旱区的裸露地表（高山岩屑、冰川前缘）现在归**形态**
    （山地/高原），因为那是地形起伏的事，不是覆盖的事。
  · **新增绿洲与滩涂**。绿洲 = 干旱气候里的可耕地（实测 73,749 格，分布在印度河、尼罗河、
    两河、塔里木南缘、河西走廊）；滩涂 = 贴海的潮滩湿地（LC100 90 或格内水占比 ≥30% 的
    沿海格，≈1.1 万格）。滩涂还顺手解掉一个两难：它让"格内过半是海的小岛格"既保住岛、
    又不长假河、也不留绿边。
  · **农田、聚落仍然并入平原**；**灌丛仍然并入草原**；**山地/高原仍然不用 NE 具名多边形定形**
    （形态全交给高程 + 起伏）。这三条 v1 的判断不变。

**覆盖与形态仍是"互斥取一"**：形态（山地/高原）不吃覆盖，所以一格记「山地」就看不见它的
森林。真正的正交分层（覆盖一层、形态一层）留待将来——现状 14 类只占 4 位，余两个码。

**改这张表 = 改数据契约**：地形编码直接写进 `栅格/地形编码.png`，编辑器 `js/config.js`
的 `TER_COLORS` 与 `js/data.js` 的 `terrain_legend` 必须同步；`base_tag` 含图例摘要，
改表会让编辑器里的本地草稿全部失效。
"""
from __future__ import annotations

import json
import os
import zlib

import numpy as np

LEGEND = ["海洋", "湖泊", "河流", "冰川", "森林", "草原", "荒漠", "沼泽", "滩涂", "绿洲",
          "平原", "丘陵", "高原", "山地"]
(T_OCEAN, T_LAKE, T_RIVER, T_ICE, T_FOREST, T_GRASS, T_WASTE, T_MARSH, T_TIDAL, T_OASIS,
 T_PLAIN, T_HILL, T_PLATEAU, T_MOUNTAIN) = range(14)

N_CLASS = len(LEGEND)
VEG_UNKNOWN = 255                 # 植被层里"没有样本/无法归类"的哨兵（uint8）

# ---- 植被层的候选标号：与地形类同码，另加两个**内部哨兵**（哨兵不进地形层） ----
# v1 这里有 4 个"林型族"（常绿阔叶/针叶/阔叶/混交），要在 classify 里按纬度 + 海拔权重
# 才能定性；v2 把林型合并成「森林」，那套权重制整段删除，候选层于是退化成
# "地形类 + 两个哨兵"。
CAND_BARE = 14                    # LC100 60「无植被～稀疏植被」：不当覆盖写进地形，
                                  # 等 build_raster 按气候判（干旱 → 荒漠；否则留给形态）
CAND_FOREST = 15                  # LC100 110–126 的任意林型：一律记「森林」
N_CAND = 16
VEG_ENCODING = "cover-v2"         # 换了编码就往缓存旁边写这个标记，对不上就不复用
WATER_ENCODING = "waterfrac-v1"   # 水体占比层的缓存标记（LC100 80∪200 占有效样本的百分比）

# 水体占比的用法：**逐格取众数会把"碎成几块的水"藏起来**。实测长江口有一格
# 45% 是水像素（80/200 各占一部分），可单一类最多的是农田（LC100 40），取众数就记成
# 「平原」——于是长江口整片成了陆地色，河到 119.6°E 就"断"了（见 `设计笔记03` §14.13）。
# 修法：一格的水体占比 ≥ WATER_PCT 且**与既有水面 4 邻接**时，补成水面。
# 加"邻接"是为了不动海岸线：孤立的 30% 水格（滩涂、灌溉水田）不该变成河。
WATER_PCT = 30                    # 判"这格是水"的占比门槛（百分数）


def water_frac_note() -> str:
    """给调用方（台账 / 日志）用的一句话说明，避免口径再被抄错。"""
    return (f"水体占比 = LC100 的 80（内陆水）∪ 200（开阔海）占格内有效样本的百分比；"
            f"≥ {WATER_PCT}% 且与既有水面 4 邻接者补成水面（逐格众数会把碎水藏起来）")

# ---------------------------------------------------------------- LC100 常量
LC100_SHAPE = (141120, 362880)    # 80 N → 60 S / 180 W → 180 E
LC100_PX_DEG = 1.0 / 1008.0       # 实测 0.0009920634920634888 = 1/1008（≈ 100 m）
LC100_TOP_LAT = 80.0
LC100_SEA = 200                   # 开阔海
LC100_NODATA = (0, 255)           # 0 = 无输入数据；255 = 产品 nodata

LC100_DIRECT = {
    20: T_GRASS,                       # 灌丛 → 草原（杂类，不单列）
    30: T_GRASS,
    40: T_PLAIN, 50: T_PLAIN,          # 农田 / 聚落 → 平原（干旱区的农田由 build_raster 改判「绿洲」）
    60: CAND_BARE, 70: T_ICE,
    80: T_LAKE, 90: T_MARSH,
    100: T_GRASS,                      # 苔原植被（moss/lichen）→ 草原；显示时按热量带派生「苔原」
    111: CAND_FOREST, 112: CAND_FOREST, 113: CAND_FOREST, 114: CAND_FOREST,
    115: CAND_FOREST, 116: CAND_FOREST, 121: CAND_FOREST, 122: CAND_FOREST,
    123: CAND_FOREST, 124: CAND_FOREST, 125: CAND_FOREST, 126: CAND_FOREST,
}

# 「缓坡」上让位给丘陵的土地覆盖类。**只让草原**：
#   · 农田不让 —— 农田是平原（坡地农田也一样，那是土地利用）；
#   · 森林不让 —— 西伯利亚的泰加林压在缓坡上，让位就把整片森林抹了；
#   · 裸地/灌丛不让 —— 300 m 的碎石坡本来就该记「草原/荒漠」；
#   · 草原让 —— "丘陵草原"是最典型的地貌（哈萨克丘陵、蒙古高原边缘），
#     而丘陵若不吃下这块，就会只剩 LC100 无数据的那 0.05%，成了死类。
YIELD_TO_HILL = (T_GRASS,)

# ---------------------------------------------------------------- 形态阈值（起伏 = 格内 max−min）
MOUNTAIN_RELIEF = 600.0           # 起伏 > 600 m → 山地
HILL_RELIEF = 120.0               # 起伏 > 120 m → 丘陵
PLATEAU_HIGH_ELEV = 2600.0        # 2600 m 以上且起伏小 → 高原（青藏）
PLATEAU_ELEV = 1200.0             # 1200 m 以上且起伏更小 → 高原（蒙古/黄土/云贵/伊朗）
PLATEAU_RELIEF_FLAT = 400.0


# ================================================================ 陆地掩膜
def rasterize_union(LON, LAT, lon0, lat1, cell, geoms, out=None) -> np.ndarray:
    """把若干（已折回本图经度窗口的）几何按**格心命中**烧进一张掩膜。

    LON / LAT 是 (H, W) 的格心经纬度网格（build_raster 里已算好）。
    geoms 需先 make_valid / buffer(0)；这里只做 bbox 剪裁 + contains_xy。
    """
    from shapely import contains_xy
    H, W = LON.shape
    m = np.zeros((H, W), np.uint8) if out is None else out
    for g in geoms:
        if g is None or g.is_empty:
            continue
        x0, y0, x1, y1 = g.bounds
        c0 = max(0, int(np.floor((x0 - lon0) / cell)) - 1)
        c1 = min(W, int(np.ceil((x1 - lon0) / cell)) + 2)
        r0 = max(0, int(np.floor((lat1 - y1) / cell)) - 1)
        r1 = min(H, int(np.ceil((lat1 - y0) / cell)) + 2)
        if c1 <= c0 or r1 <= r0:
            continue
        xs, ys = LON[r0:r1, c0:c1].ravel(), LAT[r0:r1, c0:c1].ravel()
        hit = contains_xy(g, xs, ys).reshape(r1 - r0, c1 - c0)
        m[r0:r1, c0:c1][hit] = 1
    return m


# ================================================================ 高程与起伏
def read_elevation(etopo_path, lon0, lon1, lat0, lat1, W, H):
    """→ (elev 格均值, relief 格内极差) 两张 (H, W) float32。

    原实现有个隐性浪费：`np.concatenate([page.asarray()[...], page.asarray()[...]])`
    把整页 10800 × 21600 解了两遍（≈ 2 × 933 MB）。这里只解一遍。
    """
    import tifffile
    with tifffile.TiffFile(etopo_path) as tf:
        page = tf.pages[0]
        fh, fw = page.shape[0], page.shape[1]
        r0 = int((90.0 - lat1) / 180.0 * fh)
        r1 = int((90.0 - lat0) / 180.0 * fh)
        cA0, cA1 = int((lon0 + 180.0) / 360.0 * fw), int((180.0 + 180.0) / 360.0 * fw)
        cB0, cB1 = 0, int((lon1 - 360.0 + 180.0) / 360.0 * fw)
        whole = page.asarray()
        full = np.concatenate([whole[r0:r1, cA0:cA1], whole[r0:r1, cB0:cB1]], axis=1).astype(np.float32)
        del whole
    full[full <= -9999.0] = 0.0                      # GDAL_NODATA = -99999
    from PIL import Image
    # 0.0625° ÷ (1/60)° = 3.75 像元/格，除不尽；必须按面积平均（BOX），不能截断
    elev = np.asarray(Image.fromarray(full).resize((W, H), Image.BOX), dtype=np.float32)
    return elev, relief_of(full, H, W)


def relief_of(full: np.ndarray, H: int, W: int) -> np.ndarray:
    """格内 max−min（相对高差）。用 reduceat 按格边界分段，任意 cell 都对齐格心。"""
    rows, cols = full.shape
    rs = np.round(np.arange(H + 1) * rows / H).astype(np.int64)
    cs = np.round(np.arange(W + 1) * cols / W).astype(np.int64)
    np.clip(rs, 0, rows - 1, out=rs); rs[H] = rows
    np.clip(cs, 0, cols - 1, out=cs); cs[W] = cols
    np.maximum.accumulate(rs, out=rs)
    np.maximum.accumulate(cs, out=cs)
    hi_r = np.maximum.reduceat(full, rs[:-1], axis=0)
    lo_r = np.minimum.reduceat(full, rs[:-1], axis=0)
    hi = np.maximum.reduceat(hi_r, cs[:-1], axis=1)
    lo = np.minimum.reduceat(lo_r, cs[:-1], axis=1)
    return (hi - lo).astype(np.float32)


# ================================================================ 土地覆盖（LC100）
def _lc_cols(lon_s: np.ndarray) -> np.ndarray:
    """经度 → LC100 列号（-180…180 展开）"""
    return ((lon_s + 180.0) % 360.0) * 1008.0


def _lc_rows(lat_s: np.ndarray) -> np.ndarray:
    return np.round((LC100_TOP_LAT - lat_s) / LC100_PX_DEG).astype(np.int64)


def _lut() -> np.ndarray:
    """LC100 码 → 候选标号（16 类 or 4 个林型族）；无对应给 VEG_UNKNOWN。

    林型只落到"族"，不在这里按纬度定性 —— 定性要纬度+海拔一起算权重（见 classify）。
    """
    lut = np.full(256, VEG_UNKNOWN, np.uint8)
    for c, t in LC100_DIRECT.items():
        lut[c] = t
    lut[LC100_SEA] = T_OCEAN
    for c in LC100_NODATA:
        lut[c] = VEG_UNKNOWN
    return lut


def _dominant_from_parts(W, H, cell, lon0, lat1, read_strip, cache_path, rs=8, cs=3, log=print,
                         water_path=None):
    """逐格取 rs × cs 个样本的**主导候选**（16 类 + 4 族）。read_strip(row) → 该行窗口内的列。

    同时算出**水体占比**层（LC100 的 80 内陆水 ∪ 200 开阔海 占有效样本的百分比）。
    为什么不另读一遍：LUT 已经把这两个码映射成 T_LAKE/T_OCEAN，所以水体计数就是
    `cnt` 的两列之和——白拿。为什么需要它：见 `water_frac_note()`。
    """
    x = np.arange(W)
    lon_s = lon0 + (x[:, None] + (np.arange(cs)[None, :] + 0.5) / cs) * cell      # (W, cs)
    cols = np.round(_lc_cols(lon_s)).astype(np.int64)
    colA0, colA1 = read_strip.colA
    idx = np.where(lon_s <= 180.0, cols - colA0, (colA1 - colA0) + cols)
    idx = np.clip(idx, 0, read_strip.width - 1)
    lut = _lut()

    veg = np.full((H, W), VEG_UNKNOWN, np.uint8)
    water = np.zeros((H, W), np.uint8)                     # 水体占比（百分数，0–100）
    cells_idx = np.repeat(x, cs).astype(np.int64)                              # (W*cs,)
    for y in range(H):
        lat_s = lat1 - (y + (np.arange(rs) + 0.5) / rs) * cell
        rr = np.clip(_lc_rows(lat_s), 0, LC100_SHAPE[0] - 1)
        cnt = np.zeros(W * N_CAND, np.int32)
        for r in rr:
            codes = read_strip(int(r))[idx]                                   # (W, cs)
            cls = lut[codes]
            keep = (cls != VEG_UNKNOWN).ravel()
            if not keep.any():
                continue
            flat = cells_idx[keep] * N_CAND + cls.ravel()[keep]
            cnt += np.bincount(flat, minlength=W * N_CAND)
        g = cnt.reshape(W, N_CAND)
        tot = g.sum(axis=1)
        best = g.argmax(axis=1).astype(np.uint8)
        veg[y] = np.where(tot > 0, best, VEG_UNKNOWN)
        w = g[:, T_OCEAN] + g[:, T_LAKE]                    # 水体 = 开阔海 + 内陆水
        water[y] = np.where(tot > 0, np.round(w * 100.0 / np.maximum(tot, 1)), 0).astype(np.uint8)
        if log and (y % 200 == 0 or y == H - 1):
            log(f"    植被/水体 {y + 1}/{H} 行")
    if water_path:
        try:
            np.save(water_path, water)
            with open(water_path + ".tag", "w", encoding="utf-8") as f:
                json.dump({"encoding": WATER_ENCODING}, f)
            log(f"  水体占比层已缓存 {os.path.basename(water_path)}"
                f"（{water.nbytes / 1048576:.1f} MB）")
        except Exception as e:                                                # noqa: BLE001
            log(f"  ! 水体占比层缓存失败：{e}")
    if cache_path:
        try:
            np.save(cache_path, veg)
            with open(cache_path + ".tag", "w", encoding="utf-8") as f:
                json.dump({"encoding": VEG_ENCODING}, f)
            log(f"  植被层已缓存 {os.path.basename(cache_path)}（{veg.nbytes / 1048576:.1f} MB）")
        except Exception as e:                                                # noqa: BLE001
            log(f"  ! 植被层缓存失败：{e}")
    return veg, water


class _RawStrip:
    """LC100 裸数组（满分辨率原始字节）按行读窗口内的两段列。给可信的裸数组用。"""

    def __init__(self, path, lon0, lon1):
        self.mm = np.memmap(path, np.uint8, "r", shape=LC100_SHAPE)
        cA0 = int((lon0 + 180.0) * 1008.0)
        cA1 = LC100_SHAPE[1]
        self.cB1 = int((lon1 - 360.0 + 180.0) * 1008.0)
        self.colA = (cA0, cA1)
        self._b0, self._b1 = cA0, cA1
        self.width = (cA1 - cA0) + self.cB1

    def __call__(self, r: int) -> np.ndarray:
        a = self.mm[r, self._b0:self._b1]
        b = self.mm[r, 0:self.cB1] if self.cB1 else a[:0]
        return np.concatenate([a, b])


class _TifStrip:
    """LC100 压缩 TIFF 的瓦片流式解码（只解用得到的瓦片行 / 列，内存有界）。

    实测全窗约 1–2 分钟。
    """

    def __init__(self, path, lon0, lon1, log=print):
        import tifffile
        self.tf = tifffile.TiffFile(path)
        pg = self.tf.pages[0]
        assert pg.compression == 8 and pg.predictor == 1, "LC100 期望 Deflate/无预测器"
        self.pg = pg
        self.tw = pg.tilewidth
        self.th = pg.tilelength
        self.ntc = (pg.imagewidth + self.tw - 1) // self.tw
        cA0 = int((lon0 + 180.0) * 1008.0)
        cA1 = pg.imagewidth
        self.cB1 = int((lon1 - 360.0 + 180.0) * 1008.0)
        self.colA = (cA0, cA1)
        self.width = (cA1 - cA0) + self.cB1
        self._fh = open(path, "rb")
        self._cache_row = None
        self._cache = None
        log("  用瓦片流式解 LC100（Deflate 分块，只解用得到的瓦片；实测全窗约 1–2 分钟）")

    def _tile(self, iy: int, ix: int) -> np.ndarray:
        i = iy * self.ntc + ix
        self._fh.seek(self.pg.dataoffsets[i])
        raw = self._fh.read(self.pg.databytecounts[i])
        # 最后一行瓦片不满 256 行，故按 -1 推行数，不写死 (th, tw)
        return np.frombuffer(zlib.decompress(raw), np.uint8).reshape(-1, self.tw)

    def __call__(self, r: int) -> np.ndarray:
        ty = r // self.th
        if ty != self._cache_row:
            x0 = self.colA[0] // self.tw
            x1 = (self.colA[1] + self.tw - 1) // self.tw
            x2 = (self.cB1 + self.tw - 1) // self.tw
            skip = self.colA[0] - x0 * self.tw          # 首块要切掉不足一块的前缀
            head = np.concatenate([self._tile(ty, ix) for ix in range(x0, x1)], axis=1)
            head = head[:, skip:skip + (self.colA[1] - self.colA[0])]   # 末块也要切掉多余列
            if x2:
                tail = np.concatenate([self._tile(ty, ix) for ix in range(0, x2)], axis=1)[:, :self.cB1]
                self._cache = np.concatenate([head, tail], axis=1)
            else:
                self._cache = head
            self._cache_row = ty
        off = r - ty * self.th
        return self._cache[off] if off < self._cache.shape[0] else self._cache[-1]


def validate_raw(raw_path, tif_path, log=print) -> bool:
    """裸数组与 TIFF 逐点比对；对不上就说明它是残件，不能用。

    本机曾有的那份在 lat −18° 以南整片是 0（澳洲 / 新西兰 / 南部非洲全废），
    而字节数又恰好对上 —— 光看大小和北半球几个点都看不出来。故必须比"南边的点"。
    """
    pts = [(-26.0, 128.0), (-44.0, 170.0), (-20.0, 30.0), (-3.0, 115.0), (25.0, 15.0), (38.0, 116.0)]
    try:
        import tifffile
        mm = np.memmap(raw_path, np.uint8, "r", shape=LC100_SHAPE)
        with tifffile.TiffFile(tif_path) as tf:
            pg = tf.pages[0]
            ntc = (pg.imagewidth + pg.tilewidth - 1) // pg.tilewidth
            fh = open(tif_path, "rb")
            bad = []
            for lat, lon in pts:
                r = int((LC100_TOP_LAT - lat) / LC100_PX_DEG)
                c = int(((lon + 180.0) % 360.0) * 1008.0)
                iy, ix = r // pg.tilelength, c // pg.tilewidth
                i = iy * ntc + ix
                fh.seek(pg.dataoffsets[i])
                t = np.frombuffer(zlib.decompress(fh.read(pg.databytecounts[i])), np.uint8)
                t = t.reshape(-1, pg.tilewidth)
                want = int(t[r - iy * pg.tilelength, c - ix * pg.tilewidth])
                got = int(mm[r, c])
                if want != got:
                    bad.append(f"({lat:g},{lon:g}) TIFF={want} 裸数组={got}")
            fh.close()
    except Exception as e:                                                    # noqa: BLE001
        log(f"  ! 裸数组自检失败（{e}），改走 TIFF")
        return False
    if bad:
        log("  ! 裸数组与 TIFF 不符（是残件，已忽略）：" + "；".join(bad))
        return False
    log("  裸数组自检通过（6 个已知地点与 TIFF 一致）")
    return True


def _cache_ok(cache_path, encoding=VEG_ENCODING):
    """缓存旁边有编码标记、且与当前编码一致才复用（换过编码的旧缓存必须重算）。"""
    try:
        with open(cache_path + ".tag", encoding="utf-8") as f:
            return json.load(f).get("encoding") == encoding
    except Exception:                                                         # noqa: BLE001
        return False


def veg_from_landcover(W, H, cell, lon0, lon1, lat0, lat1, raw_path, tif_path, cache_path,
                       use_raw=False, log=print, water_path=None):
    """→ (veg, water)：候选标号 (H,W) uint8（VEG_UNKNOWN = 无数据）+ 水体占比 (H,W) uint8 百分数。

    两个源都没有则返回 (None, None)。水体占比的用途见 WATER_PCT 上面的说明。
    """
    say = log or (lambda *a, **k: None)
    if (cache_path and os.path.exists(cache_path) and _cache_ok(cache_path)
            and (not water_path or (os.path.exists(water_path)
                                    and _cache_ok(water_path, WATER_ENCODING)))):
        try:
            a = np.load(cache_path)
            w = np.load(water_path) if water_path else np.zeros((H, W), np.uint8)
            if a.shape == (H, W) and w.shape == (H, W):
                say(f"  植被层读缓存 {os.path.basename(cache_path)}"
                    + (f" + {os.path.basename(water_path)}" if water_path else ""))
                return a.astype(np.uint8), w.astype(np.uint8)
        except Exception:                                                     # noqa: BLE001
            pass
    src = None
    if use_raw and raw_path and os.path.exists(raw_path) and tif_path and os.path.exists(tif_path):
        if validate_raw(raw_path, tif_path, log=say):
            say("  植被层：读 LC100 裸数组")
            src = _RawStrip(raw_path, lon0, lon1)
    if src is None and tif_path and os.path.exists(tif_path):
        src = _TifStrip(tif_path, lon0, lon1, log=say)
    if src is None:
        say("  ! 没有 LC100（裸数组与 TIFF 都缺），植被类只能靠高程与掩膜推断")
        return None, None
    return _dominant_from_parts(W, H, cell, lon0, lat1, src, cache_path, log=say,
                                water_path=water_path)


# ================================================================ 分类
def landform(elev: np.ndarray, relief: np.ndarray) -> np.ndarray:
    """只按**起伏**（格内极差）给形态：平原 / 丘陵 / 高原 / 山地。

    海拔只用来分「高原」——"高而平"的面；判丘陵/山地一律看起伏：
    海拔 4500 m 的青藏内部很平（高原），海拔 2000 m 的华山很陡（山地），
    四川盆地底部 400 m 且平坦（平原）——用海拔判会把盆地判成丘陵（踩过）。

    起伏阈值（格 ≈ 6.9 × 5.3 km）：
      山地：> 600 m（7 km 内上下 600 m，坡陡、绕路、马难走）
      丘陵：> 120 m
      高原：2600 m 以上且起伏 ≤ 600（青藏），或 1200 m 以上且起伏 ≤ 400
            （蒙古高原、黄土高原、云贵高原、伊朗高原 —— 都是"面"不是"脊"）
      平原：其余
    """
    out = np.full(elev.shape, T_PLAIN, np.uint8)
    out[relief > HILL_RELIEF] = T_HILL
    out[((elev > PLATEAU_HIGH_ELEV) & (relief <= MOUNTAIN_RELIEF))
        | ((elev > PLATEAU_ELEV) & (relief <= PLATEAU_RELIEF_FLAT))] = T_PLATEAU
    out[relief > MOUNTAIN_RELIEF] = T_MOUNTAIN
    return out


def classify(elev, relief, veg, land) -> np.ndarray:
    """合成地形：**形态（平原/丘陵/高原/山地）先铺满 → 覆盖只在"非山地、非高原"的格子上生效**。

    山脊与高原面是真实地形，不该被覆盖盖掉（大兴安岭要看得见山）；平原与丘陵则露出
    真实的覆盖（西伯利亚是森林、华北是农田=平原、南洋是热带林）。这里只出三类覆盖
    ——森林／草原／（农田聚落给的）平原——**荒漠 / 绿洲 / 滩涂由调用方按气候与海岸再判**。

    三条必须防的坑：
      · **LC100 200（开阔海）的格子不许盖到陆地上** —— 里海、咸海这类内海在 LC100 里
        记 200，而我们靠 NE 湖泊把它算作陆地；若让 200 生效就会写回「海洋」（里海曾经
        就这么变成海的）。排除掉，交给后面的 NE 湖泊面判成湖泊。
      · **CAND_BARE 不写进地形** —— LC100 60（砾漠/岩漠/寒漠/盐碱滩）算不算「荒漠」要
        看气候（干旱才算），所以这里留白、交给调用方按柯本判；非干旱的裸露地表保留
        形态类（高山岩屑、冰川前缘），那本来就是起伏的事不是覆盖的事。
      · `land` 是 uint8 掩膜，**不能写 `~mask`** —— numpy 在 uint8 上按位取反，`~1 = 254`
        （真值），于是"~hard"恒真，覆盖会被整层抹成形态（v1 就这么把森林全弄没过）。
        先转 bool。

    v1 在这里还要按"纬度 + 海拔权重"把林型族定成雨林/阔叶/针叶（`climate_weights` /
    `_forest_label`）；v2 那套整段删除——林型归「森林」，四种绿改由编辑器按
    `森林 × 热量带` 派生（见 tools/display_class.py）。
    """
    land = np.asarray(land).astype(bool)
    t = np.where(land, T_PLAIN, T_OCEAN).astype(np.uint8)
    lf = landform(elev, relief)
    t[land] = lf[land]
    if veg is None:
        return t
    known = land & (veg != VEG_UNKNOWN) & (veg != T_OCEAN) & (veg != CAND_BARE)
    open_ground = (t != T_MOUNTAIN) & (t != T_PLATEAU)
    win = known & open_ground
    win = win & ~((t == T_HILL) & np.isin(veg, YIELD_TO_HILL))     # 丘陵接住草原
    is_forest = win & (veg == CAND_FOREST)
    plain_veg = win & ~is_forest
    t[plain_veg] = veg[plain_veg]
    t[is_forest] = T_FOREST
    return t


def summarise(terrain: np.ndarray) -> dict:
    n = terrain.size
    counts = np.bincount(terrain.ravel(), minlength=N_CLASS)
    return {LEGEND[i]: round(int(c) / n, 4) for i, c in enumerate(counts) if c}
