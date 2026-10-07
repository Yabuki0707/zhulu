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

### 森林怎么定（**权重制，不是纬度一刀切**）

纬度一刀切会在图上切出一条笔直的横线（试过：23.5° 那条线横穿两广/云南，一眼假）。
改成三个连续权重，再乘林型倾向，取分数最高者：

    trop   = clamp((24 − |lat|) / 6)  ×  clamp(1 − 海拔 / 1500)      # 热带性：近赤道、低海拔
    boreal = max(clamp((|lat| − 40) / 10), clamp((海拔 − 1300) / 1200))  # 寒温性：高纬或高海拔
    temp   = max(0, 1 − trop − boreal)                              # 温带性

    | LC100 林型（族） | 雨林 | 阔叶林 | 针叶林 |
    |---|---|---|---|
    | 常绿阔叶（112/122） | 1.00 | 0.35 | 0.00 |
    | 阔叶（114/124）     | 0.45 | 1.00 | 0.25 |
    | 混交（115–126）     | 0.05 | 0.75 | 0.90 |
    | 针叶（111–123）     | 0.05 | 0.60 | 1.00 |

    分数 = 倾向 × (trop, temp, boreal)，取最大者当标签。

好处：①界线跟着海拔与真实林型走（云贵横断的针叶林、滇南山谷、江南丘陵各归各位），
不再有直线；②海拔一起算进去，热带性随高度衰减，山地把热带与温带自然隔开；
③"亚热带常绿针叶"（马尾松、杉木、日本人工林，LC100 也标成针叶林）在低纬低海拔处
必然打分给阔叶林，不会整片变泰加。

### 地形表（16 类；2026-10-07 深夜 按需求方意见定稿）

    0 海洋 1 湖泊 2 河流 3 冰川 4 沙漠 5 裸地 6 高原 7 山地 8 丘陵 9 平原
    10 针叶林 11 阔叶林 12 雨林 13 草原 14 沼泽 15 苔原

相对 设计笔记03 §14.7 的 20 类：

  · **农田、聚落并入平原**：农田是**土地利用**不是地形（同一片平原今年种麦明年抛荒，
    底层不该跟着变），LC100 的 40 农田在 6.9 km 格上也没有辨识度；聚落更不该占一个
    地形类 —— 城应当是地图上的**点**或地块属性。**农田一律平原，不因坡地改判**。
  · **灌丛并入草原**：LC100 的 20 是个杂类（地中海硬叶灌丛、荒漠灌丛、次生灌丛混在一起），
    与草原视觉分不开、模拟上也同价（都能走、都低产、都可牧）。荒地因此收敛为
    **沙漠 / 裸地 / 草原 / 苔原** 四种，不再多分——6.9 km 一格，"戈壁 vs 砾漠 vs 盐碱"
    在数据里本来就是同一个码（LC100 60），硬拆是假精度。
  · **裸地保留且是真类**：LC100 的 60「无植被～稀疏植被」= 砾漠、岩漠、寒漠、盐碱滩
    （**不是**具名大沙漠，那些由 NE 沙漠面盖成「沙漠」）。
  · **山地 / 高原不用 NE 具名多边形定形**：那里的"高原/山脉"是手绘椭圆块（一条条褐色团），
    既不跟真实山系走也不像地形。形态全部交给高程 + 起伏。

**改这张表 = 改数据契约**：地形编码直接写进 `栅格/地形编码.png`，编辑器 `js/config.js`
的 `TER_COLORS` 与 `js/data.js` 的 `terrain_legend` 必须同步。
"""
from __future__ import annotations

import json
import os
import zlib

import numpy as np

LEGEND = ["海洋", "湖泊", "河流", "冰川", "沙漠", "裸地", "高原", "山地", "丘陵", "平原",
          "针叶林", "阔叶林", "雨林", "草原", "沼泽", "苔原"]
(T_OCEAN, T_LAKE, T_RIVER, T_ICE, T_DESERT, T_BARE, T_PLATEAU, T_MOUNTAIN, T_HILL, T_PLAIN,
 T_FOR_NEEDLE, T_FOR_BROAD, T_FOR_RAIN, T_GRASS, T_MARSH, T_TUNDRA) = range(16)

N_CLASS = len(LEGEND)
VEG_UNKNOWN = 255                 # 植被层里"没有样本/无法归类"的哨兵（uint8）

# ---- 植被层的候选标号：16 类 + 4 个"林型族"（族要在 classify 里按权重才定性） ----
FAM_EGBROAD = 16                  # 常绿阔叶（112 / 122）
FAM_NEEDLE = 17                   # 针叶（111 / 113 / 121 / 123）
FAM_BROAD = 18                    # 阔叶（114 / 124）
FAM_MIXED = 19                    # 混交（115 / 116 / 125 / 126）
N_CAND = 20
FAM_NAMES = {FAM_EGBROAD: "常绿阔叶系", FAM_NEEDLE: "针叶系", FAM_BROAD: "阔叶系", FAM_MIXED: "混交系"}
VEG_ENCODING = "family-v1"        # 换了编码就往缓存旁边写这个标记，对不上就不复用

# ---------------------------------------------------------------- LC100 常量
LC100_SHAPE = (141120, 362880)    # 80 N → 60 S / 180 W → 180 E
LC100_PX_DEG = 1.0 / 1008.0       # 实测 0.0009920634920634888 = 1/1008（≈ 100 m）
LC100_TOP_LAT = 80.0
LC100_SEA = 200                   # 开阔海
LC100_NODATA = (0, 255)           # 0 = 无输入数据；255 = 产品 nodata

LC100_DIRECT = {
    20: T_GRASS,                       # 灌丛 → 草原（需求方：杂类，不单列）
    30: T_GRASS,
    40: T_PLAIN, 50: T_PLAIN,          # 农田 / 聚落 → 平原
    60: T_BARE, 70: T_ICE,
    80: T_LAKE, 90: T_MARSH, 100: T_TUNDRA,
    111: FAM_NEEDLE, 113: FAM_NEEDLE, 121: FAM_NEEDLE, 123: FAM_NEEDLE,
    114: FAM_BROAD, 124: FAM_BROAD,
    115: FAM_MIXED, 116: FAM_MIXED, 125: FAM_MIXED, 126: FAM_MIXED,
    112: FAM_EGBROAD, 122: FAM_EGBROAD,
}

# ---------------------------------------------------------------- 气候权重
TROP_LAT = 24.0                   # 热带性起算纬度（|lat| 到此为 0）
TROP_LAT_SPAN = 6.0               # 再往南 6° 到满
TROP_ELEV = 1500.0                # 热带性的海拔衰减尺度
BOREAL_LAT = 40.0                 # 寒温性起算纬度
BOREAL_LAT_SPAN = 10.0
BOREAL_ELEV = 1300.0              # 寒温性的海拔起算
BOREAL_ELEV_SPAN = 1200.0
# 各林型族对 (雨林, 阔叶林, 针叶林) 的倾向
# 在"缓坡"上让位给丘陵的土地覆盖类。**只让草原**：
#   · 农田不让 —— 需求方定的，农田是平原（坡地农田也一样，那是土地利用）；
#   · 森林不让 —— 西伯利亚的针叶林压在缓坡上，让位就把泰加林整片抹了；
#   · 裸地/灌丛不让 —— 300 m 的碎石坡本来就该记「裸地」；
#   · 草原让 —— "丘陵草原"是最典型的地貌（哈萨克丘陵、蒙古高原边缘），
#     而丘陵若不吃下这块，就会只剩 LC100 无数据的 0.05%，成了死类。
YIELD_TO_HILL = (T_GRASS,)

FAM_AFFINITY = {
    FAM_EGBROAD: (1.00, 0.35, 0.00),
    FAM_BROAD: (0.45, 1.00, 0.25),
    FAM_MIXED: (0.05, 0.75, 0.90),
    FAM_NEEDLE: (0.05, 0.60, 1.00),
}
FOREST_LABEL = (T_FOR_RAIN, T_FOR_BROAD, T_FOR_NEEDLE)      # 与倾向三元组同序

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


def _dominant_from_parts(W, H, cell, lon0, lat1, read_strip, cache_path, rs=8, cs=3, log=print):
    """逐格取 rs × cs 个样本的**主导候选**（16 类 + 4 族）。read_strip(row) → 该行窗口内的列。"""
    x = np.arange(W)
    lon_s = lon0 + (x[:, None] + (np.arange(cs)[None, :] + 0.5) / cs) * cell      # (W, cs)
    cols = np.round(_lc_cols(lon_s)).astype(np.int64)
    colA0, colA1 = read_strip.colA
    idx = np.where(lon_s <= 180.0, cols - colA0, (colA1 - colA0) + cols)
    idx = np.clip(idx, 0, read_strip.width - 1)
    lut = _lut()

    veg = np.full((H, W), VEG_UNKNOWN, np.uint8)
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
        tot = cnt.reshape(W, N_CAND).sum(axis=1)
        best = cnt.reshape(W, N_CAND).argmax(axis=1).astype(np.uint8)
        veg[y] = np.where(tot > 0, best, VEG_UNKNOWN)
        if log and (y % 200 == 0 or y == H - 1):
            log(f"    植被 {y + 1}/{H} 行")
    if cache_path:
        try:
            np.save(cache_path, veg)
            with open(cache_path + ".tag", "w", encoding="utf-8") as f:
                json.dump({"encoding": VEG_ENCODING}, f)
            log(f"  植被层已缓存 {os.path.basename(cache_path)}（{veg.nbytes / 1048576:.1f} MB）")
        except Exception as e:                                                # noqa: BLE001
            log(f"  ! 植被层缓存失败：{e}")
    return veg


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


def _cache_ok(cache_path):
    """缓存旁边有编码标记、且与当前编码一致才复用（换过编码的旧缓存必须重算）。"""
    try:
        with open(cache_path + ".tag", encoding="utf-8") as f:
            return json.load(f).get("encoding") == VEG_ENCODING
    except Exception:                                                         # noqa: BLE001
        return False


def veg_from_landcover(W, H, cell, lon0, lon1, lat0, lat1, raw_path, tif_path, cache_path,
                       use_raw=False, log=print):
    """→ (H, W) uint8 候选标号（VEG_UNKNOWN = 无数据）；两个源都没有则返回 None。"""
    say = log or (lambda *a, **k: None)
    if cache_path and os.path.exists(cache_path) and _cache_ok(cache_path):
        try:
            a = np.load(cache_path)
            if a.shape == (H, W):
                say(f"  植被层读缓存 {os.path.basename(cache_path)}")
                return a.astype(np.uint8)
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
        return None
    return _dominant_from_parts(W, H, cell, lon0, lat1, src, cache_path, log=say)


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


def climate_weights(lat: np.ndarray, elev: np.ndarray):
    """→ (trop, temp, boreal) 三个 (H, W) float32 权重，逐点相加为 1。

    热带性看"近赤道 + 低海拔"，寒温性看"高纬 + 高海拔"，其余是温带。
    连续权重取代了原先"|lat| < 23.5 一刀切"——那条线在图上是一条笔直的横线。
    """
    trop = np.clip((TROP_LAT - np.abs(lat)) / TROP_LAT_SPAN, 0, 1) \
        * np.clip(1.0 - elev / TROP_ELEV, 0, 1)
    boreal = np.maximum(np.clip((np.abs(lat) - BOREAL_LAT) / BOREAL_LAT_SPAN, 0, 1),
                        np.clip((elev - BOREAL_ELEV) / BOREAL_ELEV_SPAN, 0, 1))
    temp = np.clip(1.0 - trop - boreal, 0, 1)
    return trop.astype(np.float32), temp.astype(np.float32), boreal.astype(np.float32)


def _forest_label(veg, lat, elev):
    """林型族 → 雨林/阔叶林/针叶林：分数 = 该族的气候倾向 × (trop, temp, boreal)。

    注意是**逐格**在三档里取最大（哪个档赢取决于这一格的纬度与海拔），
    不是拿倾向三元组本身取最大 —— 后者会把结论写死成一个固定标签。
    """
    trop, temp, boreal = climate_weights(lat, elev)
    label = np.full(veg.shape, VEG_UNKNOWN, np.uint8)
    # best 从 −1 起：常绿阔叶在寒温带的三档分数可能正好是 0（它对针叶的倾向就是 0），
    # 用 0 起步的话"m > best"不成立，那一格会留着 VEG_UNKNOWN（255）漏进地形层。
    best = np.full(veg.shape, -1.0, np.float32)
    lab3 = np.asarray(FOREST_LABEL, np.uint8)
    for fam, aff in FAM_AFFINITY.items():
        s0 = aff[0] * trop
        s1 = aff[1] * temp
        s2 = aff[2] * boreal
        m = np.maximum(np.maximum(s0, s1), s2)
        idx = np.where(m == s0, 0, np.where(m == s1, 1, 2)).astype(np.uint8)
        win = (veg == fam) & (m > best)
        best[win] = m[win]
        label[win] = lab3[idx][win]
    return label


def classify(elev, relief, veg, land, lat) -> np.ndarray:
    """合成地形（Natural Earth 的水体/沙漠/苔原细化由调用方在之后叠加）。

    优先级：**形态（平原/丘陵/高原/山地）先铺满 → 土地覆盖只在"非山地、非高原"的格子上生效**。
    山脊与高原面是真实地形，不该被森林盖掉（大兴安岭要看得见山）；平原与丘陵则露出
    真实的土地覆盖（西伯利亚是针叶林、华北是农田=平原、南洋是雨林）。

    两条必须防的坑：
      · **土地覆盖为"海洋"（LC100 200）的格子不许盖到陆地上** —— 里海、咸海这类内海在
        LC100 里记 200，而我们靠 NE 湖泊把它算作陆地；若让 200 生效就会写回「海洋」
        （里海曾经就这么变成海的）。排除掉，交给后面的 NE 湖泊面判成湖泊。
      · `land` 是 uint8 掩膜，**不能写 `~mask`** —— numpy 在 uint8 上做按位取反，
        `~1 = 254`（真值），于是"~hard"恒真，土地覆盖会被整层抹成地形形态
        （本轮就是这么把森林全弄没的）。先转 bool。
    """
    land = np.asarray(land).astype(bool)
    t = np.where(land, T_PLAIN, T_OCEAN).astype(np.uint8)
    lf = landform(elev, relief)
    t[land] = lf[land]
    if veg is None:
        return t
    known = land & (veg != VEG_UNKNOWN) & (veg != T_OCEAN)
    open_ground = (t != T_MOUNTAIN) & (t != T_PLATEAU)
    win = known & open_ground
    yield_hill = (t == T_HILL) & np.isin(veg, YIELD_TO_HILL)     # 丘陵接住草原
    win = win & ~yield_hill
    is_forest_family = win & (veg >= FAM_EGBROAD)
    plain_veg = win & ~is_forest_family
    t[plain_veg] = veg[plain_veg]
    if is_forest_family.any():
        lab = _forest_label(veg, lat, elev)
        t[is_forest_family] = lab[is_forest_family]
    return t


def summarise(terrain: np.ndarray) -> dict:
    n = terrain.size
    counts = np.bincount(terrain.ravel(), minlength=N_CLASS)
    return {LEGEND[i]: round(int(c) / n, 4) for i, c in enumerate(counts) if c}
