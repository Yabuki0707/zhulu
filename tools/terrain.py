# -*- coding: utf-8 -*-
"""地形分类（**覆盖** × **形态**）：高程 + 起伏 + Copernicus LC100 土地覆盖 + Natural Earth 掩膜。

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
低地的四种林型（雨林／季雨林／常绿阔叶林／落叶阔叶林／针叶林）由
`森林 × 热量带 × 干湿` 当场派生（`tools/display_class.py` 的按轴词表，v4 起共 59 类显示类），
存储里只有「森林」。山地与高原的森林另有「山地/高原 + 林型」四类（形态优先，见 `0008`）。

代价是一条已知的小偏差：低纬的人工针叶林（马尾松、杉木、日本人工林——LC100 也标成
针叶林）在气候看来是亚热带，会显示成常绿阔叶。实测面积极小，且换气候数据不必重做地形
——这正是这一层分离要买的东西。

### 地形表（v3：**一个字节两个半字节**——高 4 位覆盖、低 4 位形态；见 docs/adr/0007）

    覆盖（高 4 位，12 值）  0海洋 1湖泊 2河流 3冰川 ｜ 4森林 5草原 6荒漠 7沼泽 8滩涂 9盐沼 10草甸 11绿洲
    形态（低 4 位， 4 值）  0平原 1丘陵 2高原 3山地（海洋格写 0 当 don't-care）

**为什么必须拆**（`docs/adr/0007`，需求方看图报的）：

v2 让形态与覆盖**抢同一个值**，规则是"形态赢"。实测后果：全图形态类 520,660 格里有
**514,976 格（98.9%）底下藏着一个 LC100 覆盖**；西北窗口（96–108°E/32–40.5°N）更是
**100%**——那一片 LC100 说草原 19,471 格、裸地 9,845、森林 4,230、农田 3,050，
图上却只显示"高原 20,705"。于是：

  · **河湟谷地不见了**：西宁那格 2321 m、起伏 140 m → 判「高原」，而 LC100 说它是农田；
  · **陇右整片是高原**：天水、定西同样被形态吃掉覆盖；
  · **沙漠/苔原分不出来**：`沙漠 = 荒漠 ∧ 干旱`、`苔原 = 草原 ∧ 寒带`，可高原上的格
    根本没有覆盖可以相乘。

拆开之后一格可以同时是「高原 ∧ 草原」「山地 ∧ 森林」「高原 ∧ 草甸（河谷）」，上面
三件事一起解掉。两个半字节**共用原来那一个字节**，不加新图。

拆开后顺带作废两条 v2 的规则（现在都成了可表达的组合）：

  · `YIELD_TO_HILL`（丘陵接住草原）——"丘陵 ∧ 草原"现在能直接存，不必让位；
  · `open_ground`（山地/高原不吃覆盖）——现在"山地 ∧ 森林"能直接存。

**LC100 的农田与聚落 → 覆盖「草甸」**（v2 是"农田 → 平原"）：v2 让农田与形态抢位，只好
强行归平原；两轴分开之后它不再与平原竞争，于是回到覆盖轴上——这也正是"河湟谷地要有"
那一条的正解。

**名字是「草甸」**，这是需求方在同一天里改了三次之后定下的词（农田 → 田野 → **草甸**）。
第一次改（农田 → 田野）买到的东西是不再像在给土地贴**土地利用**标签——需求方原话是
"平原又不是全部都要利用"，这一层说的是**地表本身**，不是"人在种它"。第二次改（田野 →
草甸）是把它再往"地表本身"推一步：草甸是**地表的说法**，一个覆盖类不该替玩家回答
"这块地有没有开垦过"（那是地块层的属性，不是像元层的）。
⚠️ 它与覆盖 5「草原」只差一层植被密度，图上靠**配色**分开（草甸 `#e8e4a8` 偏黄、草原
`#b9c68a` 偏绿），显示类里也各自有名字——别把两者并成一个类。

绿洲仍是独立覆盖类（= LC100 农田 ∧ 真沙漠气候），保留在图例里。

**改这张表 = 改数据契约**：编码直接写进 `栅格/地形编码.png`，编辑器 `js/config.js`
的 `TER_COLORS` 与 `js/data.js` 的 `cover_legend`/`form_legend` 必须同步；`base_tag`
含图例摘要，改表会让编辑器里的本地草稿全部失效。
"""
from __future__ import annotations

import json
import os
import zlib

import numpy as np

# ---- 覆盖：地形字节的**高 4 位**（12 值） ----
COVER_LEGEND = ["海洋", "湖泊", "河流", "冰川", "森林", "草原", "荒漠", "沼泽", "滩涂",
                "盐沼", "草甸", "绿洲"]
(C_OCEAN, C_LAKE, C_RIVER, C_ICE, C_FOREST, C_GRASS, C_WASTE, C_MARSH, C_TIDAL, C_SALTM,
 C_FARM, C_OASIS) = range(12)
N_COVER = len(COVER_LEGEND)

# ---- 形态：地形字节的**低 4 位**（4 值，实际只用 2 位） ----
# ⚠️ 只有 4 个值，是因为运行态那条 32 位记录里形态只分到 **2 位**（见 docs/adr/0007）。
# 原来那个"无（水冰格）"被删掉了：海洋格的形态位一律写 平原（0）当 don't-care——
# 覆盖=海洋 已经足够识别海洋，再给形态留一个"无"就会把形态撑到 5 个值、2 位装不下
# （这正是子代理验收时抓到的那个 bug：山地的 4 溢出进了热量带，10.9 万格错位）。
# 湖泊与冰川**保留**它们的 landform（于是"高原湖泊"这类说法仍然成立）。
FORM_LEGEND = ["平原", "丘陵", "高原", "山地"]
(F_PLAIN, F_HILL, F_PLATEAU, F_MOUNTAIN) = range(4)
N_FORM = len(FORM_LEGEND)

VEG_UNKNOWN = 255                 # 植被层里"没有样本/无法归类"的哨兵（uint8）

# ---- 植被层的候选标号：与**覆盖**同码，另加两个内部哨兵（哨兵不进地形层） ----
CAND_BARE = 12                    # LC100 60「无植被～稀疏植被」：干旱区才算荒漠，交给调用方
CAND_FOREST = 13                  # LC100 110–126 的任意林型：一律记「森林」
N_CAND = 14
VEG_ENCODING = "cover-v3"         # 换了编码就往缓存旁边写这个标记，对不上就不复用

# ---------------------------------------------------------------- 地形字节的打包
# 一个字节两个半字节：`码 = 覆盖 × 16 + 形态`。这样**不加新图**——编辑器少一套画布，
# 而两者本来就永远一起读。海洋格的形态位恒写 0（平原）当 don't-care——**不给它留一个"无"**：
# 那样形态会变成 5 个值，而运行态那条 32 位记录里形态只分到 2 位（ADR 0007）。


def pack(cover: np.ndarray, form: np.ndarray) -> np.ndarray:
    """(覆盖, 形态) → 一个字节（覆盖在**高** 4 位）。"""
    return ((cover.astype(np.uint16) << 4) | (form.astype(np.uint16) & 0x0F)).astype(np.uint8)


def unpack(ter: np.ndarray):
    """一个字节 → (覆盖, 形态)。"""
    t = ter.astype(np.uint8)
    return (t >> 4).astype(np.uint8), (t & 0x0F).astype(np.uint8)
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
    20: C_GRASS,                       # 灌丛 → 草原（杂类，不单列）
    30: C_GRASS,
    40: C_FARM, 50: C_FARM,            # LC100 的农田 / 聚落 → 覆盖「**草甸**」——这一层说的是
                                       #   **地表本身**，不是给平原贴一张土地利用标签
                                       #   （需求方原话："平原又不是全部都要利用"）。
                                       #   名字的来历见模块开头（农田 → 田野 → 草甸）。
    60: CAND_BARE, 70: C_ICE,
    80: C_LAKE, 90: C_MARSH,
    100: C_GRASS,                      # 苔原植被（moss/lichen）→ 草原；显示时按热量带派生「苔原」
    111: CAND_FOREST, 112: CAND_FOREST, 113: CAND_FOREST, 114: CAND_FOREST,
    115: CAND_FOREST, 116: CAND_FOREST, 121: CAND_FOREST, 122: CAND_FOREST,
    123: CAND_FOREST, 124: CAND_FOREST, 125: CAND_FOREST, 126: CAND_FOREST,
}

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
    """LC100 码 → 候选标号（12 个覆盖标号 + 2 个内部哨兵）；无对应给 VEG_UNKNOWN。

    林型只落到"族"，不在这里按纬度定性 —— 定性要纬度+海拔一起算权重（见 classify）。
    """
    lut = np.full(256, VEG_UNKNOWN, np.uint8)
    for c, t in LC100_DIRECT.items():
        lut[c] = t
    lut[LC100_SEA] = C_OCEAN
    for c in LC100_NODATA:
        lut[c] = VEG_UNKNOWN
    return lut


def _dominant_from_parts(W, H, cell, lon0, lat1, read_strip, cache_path, rs=8, cs=3, log=print,
                         water_path=None):
    """逐格取 rs × cs 个样本的**主导候选**（12 个覆盖标号 + 2 个内部哨兵）。read_strip(row) → 该行列。

    同时算出**水体占比**层（LC100 的 80 内陆水 ∪ 200 开阔海 占有效样本的百分比）。
    为什么不另读一遍：LUT 已经把这两个码映射成 C_LAKE/C_OCEAN，所以水体计数就是
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
        w = g[:, C_OCEAN] + g[:, C_LAKE]                    # 水体 = 开阔海 + 内陆水
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
    """只按**起伏**（格内极差）给形态码（= FORM_LEGEND 的下标，0..3）：平原 0 / 丘陵 1 / 高原 2 / 山地 3。

    海拔只用来分「高原」——"高而平"的面；判丘陵/山地一律看起伏：
    海拔 4500 m 的青藏内部很平（高原），海拔 2000 m 的华山很陡（山地），
    四川盆地底部 400 m 且平坦（平原）——用海拔判会把盆地判成丘陵（踩过）。

    起伏阈值（格 ≈ 5.9 × 5.9 km）：
      山地：> 600 m（6 km 内上下 600 m，坡陡、绕路、马难走）
      丘陵：> 120 m
      高原：2600 m 以上且起伏 ≤ 600（青藏），或 1200 m 以上且起伏 ≤ 400
            （蒙古高原、黄土高原、云贵高原、伊朗高原 —— 都是"面"不是"脊"）
      平原：其余

    ⚠️ v3 起它**只出形态**，不再与覆盖抢同一个值：陇右（1500–2500 m、起伏 200–400 m）
    照样判「高原」，但那里的覆盖（LC100 的草原/农田）现在**看得见了**——
    这正是 `docs/adr/0007` 要修的东西。**不要把这里的阈值当成"西北画错了"的解**。
    """
    out = np.full(elev.shape, F_PLAIN, np.uint8)
    out[relief > HILL_RELIEF] = F_HILL
    out[((elev > PLATEAU_HIGH_ELEV) & (relief <= MOUNTAIN_RELIEF))
        | ((elev > PLATEAU_ELEV) & (relief <= PLATEAU_RELIEF_FLAT))] = F_PLATEAU
    out[relief > MOUNTAIN_RELIEF] = F_MOUNTAIN
    return out


def classify(elev, relief, veg, land):
    """→ **(cover, form) 两张 uint8**（v3：两个轴，谁都不吃谁）。

    · **形态**全交给高程 + 起伏（`landform`），陆地格一律有值，水冰格为 0（无）。
    · **覆盖**来自 LC100：森林 / 草原 / 农田 / 沼泽 / 湖泊 / 冰川…；`CAND_BARE`
      （LC100 60 砾漠岩漠）**不在这里定性**——算不算「荒漠」要气候说了算，交给调用方。
      荒漠 / 绿洲 / 滩涂 三类同样由调用方按气候与海岸后置覆盖。

    三条必须防的坑：
      · **LC100 200（开阔海）的格子不许盖到陆地上** —— 里海、咸海这类内海在 LC100 里
        记 200，而我们靠 NE 湖泊把它算作陆地；若让 200 生效就会写回「海洋」（里海曾经
        就这么变成海的）。排除掉，交给后面的 NE 湖泊面判成湖泊。
      · `land` 是 uint8 掩膜，**不能写 `~mask`** —— numpy 在 uint8 上按位取反，`~1 = 254`
        （真值），于是"~hard"恒真，覆盖会被整层抹掉（v1 就这么把森林全弄没过）。先转 bool。
      · 陆地默认覆盖给**草原**（LC100 无数据时最不坏的猜测：既不是水面也不是森林）。

    v2 里那两条"谁吃谁"的规则（`YIELD_TO_HILL` 丘陵接住草原、`open_ground` 山地/高原
    不吃覆盖）**整段删除**：两轴分开之后，"丘陵 ∧ 草原""山地 ∧ 森林"本来就能直接存。
    """
    land = np.asarray(land).astype(bool)
    form = np.zeros(elev.shape, np.uint8)
    form[land] = landform(elev, relief)[land]
    cover = np.full(elev.shape, C_OCEAN, np.uint8)
    cover[land] = C_GRASS
    if veg is None:
        return cover, form
    known = land & (veg != VEG_UNKNOWN) & (veg != C_OCEAN) & (veg != CAND_BARE)
    cover[known & (veg == CAND_FOREST)] = C_FOREST
    passthru = known & (veg != CAND_FOREST)
    cover[passthru] = veg[passthru]          # 0..10 的覆盖码直通（湖泊/冰川/沼泽/农田…）
    return cover, form
