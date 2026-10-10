# -*- coding: utf-8 -*-
"""GLWD（Global Lakes and Wetlands Database）→ 两个覆盖量：**盐盘/盐漠** 与 **咸水湖**。

**要解的两件事，各用一层：**

  · **内陆盐碱地／盐漠** ← **GLWD-3** 的第 7 类「Pan, brackish/saline wetland（盐盘／咸水湿地）」。
    GLWD-3 是 30 弧秒（≈1 km）全球栅格、12 类。取法是"格内该类像素占比"，与其它层同口径。
  · **咸水湖** ← **GLWD-1** 的 `MGLD_TYPE` 字段（Meigh 的**闭合盆地**判据）：`closed`／`closedx`
    ＝内流盆地 → 湖水只出不进、盐分累积 → **咸水湖**；`open` → 淡水湖。
    实测 12/13 全对：里海/咸海/青海湖/乌布苏/呼伦湖/死海＝闭合（真是咸），
    贝加尔/斋桑＝开放（真是淡）；只把**博斯腾湖**误标成闭合（它其实经孔雀河外流）。

**为什么不用别的源**（都实测过、都判为不可用）：
  · **SoilGrids 的粗碎屑/沙粒占比** —— 分不开沙与砾（见 `地图/栅格地形数据生成器/sanddunes.py`）。
  · **UNDP GeoHub「2009 全球土壤盐分图」**（1 km，CC BY 4.0，90 MB）—— 伊朗**卡维尔盐漠读 0.01**、
    柴达木**察尔汗读 0.01**，而**卡拉库姆沙海读 0.46**（比盐漠还高）。全球土壤模型在荒漠里分辨力为零。
  · **GLWD 的 shapefile（level 1/2）没有盐度字段**（只有 Lake/Reservoir/River）。

⚠️ **GLWD-3 的已知漏项**（记在 `docs/adr/0014`）：它是 2004 年的粗产品，**察尔汗、乌斯秋尔特、
卢特、长芦盐场** 都读成"非湿地"。所以「盐漠」这一类**不会**修掉渤海湾那排盐田（那是 LC100 的
内陆水体码造成的，得靠另一条规则）。命中很好的例子：伊朗**卡维尔盐漠**、**罗布泊**（整格 25/25）。

**许可**：GLWD 由 WWF 与卡塞尔大学发布，**限非商业的科研/保护/教育用途**——本项目非商业，
可用；商业化须重新评估。见 `地图/地图数据/说明.md` §三。

**唯一的 GDAL 依赖**：GLWD-3 是 **ArcInfo 二进制网格（.adf）**，tifffile 读不了，本文件用
`rasterio`（自带 GDAL）读。所以这一层**必须走缓存**：`生成.py` 只读 `.npy`，
没有缓存就大声报错——**管线本身不依赖 GDAL**。
"""
from __future__ import annotations

import io
import os
import zipfile

import numpy as np

GLWD3_NODATA = 255
SALT_CLASS = 7                    # 盐盘／咸水湿地
GLWD3_PIX = 1.0 / 120.0           # 30 弧秒

SALINE = ("closed", "closedx")    # MGLD_TYPE 里表示内流（闭合盆地）的两个值

CACHE_TAG_PAN = "glwd3-pan-v1"
CACHE_TAG_LAKE = "glwd1-saline-v1"


# ================================================================ 盐盘／盐漠（GLWD-3）
def salt_pan_fraction(W, H, cell, lon0, lat1, adf_dir, cache_path=None, log=print):
    """→ (H, W) uint8：每格「盐盘／咸水湿地」占比（百分数）；无数据处 255。

    用 `rasterio` 的**窗口读取 + 面积平均重采样**：源是等经纬度栅格，格也是等经纬度矩形，
    所以一次 `read(window=..., out_shape=(H,W), resampling=average)` 就是精确的格内占比，
    不必把 933 MB 的整张图读进来。
    """
    say = log or (lambda *a, **k: None)
    if cache_path and os.path.exists(cache_path) and _cache_ok(cache_path, CACHE_TAG_PAN):
        try:
            a = np.load(cache_path)
            if a.shape == (H, W):
                say(f"  盐盘层读缓存 {os.path.basename(cache_path)}")
                return a.astype(np.uint8)
        except Exception:                                                     # noqa: BLE001
            pass
    if not adf_dir or not os.path.exists(os.path.join(adf_dir, "hdr.adf")):
        say(f"  ! 缺 GLWD-3（{adf_dir}），盐盘层全给无数据（内陆盐漠 将不出现）")
        return np.full((H, W), GLWD3_NODATA, np.uint8)
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.windows import from_bounds
    except ImportError:
        say("  ! 没装 rasterio，读不了 GLWD-3 的 .adf —— 盐盘层跳过"
            "（`python -m pip install rasterio`；管线本身不需要它，只需要它的缓存）")
        return np.full((H, W), GLWD3_NODATA, np.uint8)

    lon1, lat0 = lon0 + W * cell, lat1 - H * cell
    say(f"  读 GLWD-3 盐盘类（ArcInfo 网格，30 弧秒，经 rasterio/GDAL）")
    # ⚠️ **本图窗口跨 180° 经线**（25°E–226°E），而 GLWD 是 −180…180 的常规经纬栅格：
    #   一次 `from_bounds(25, …, 226, …)` 会要一个宽 201° 的窗口、右侧越出源图，
    #   读出来是歪的（实测只有 67 万格"有值"，明显不对）。所以**按两段读再拼**：
    #   25…180 与 −180…−134（＝180…226 的日界线以东部分）。
    SUB = 4                                   # 每格取 4×4 个子样，算"是第 7 类"的比例
    parts = []
    for a, b in ((lon0, 180.0), (-180.0, lon1 - 360.0)):
        if b <= a:
            continue
        with rasterio.open(adf_dir) as ds:
            win = from_bounds(a, lat0, b, lat1, ds.transform)
            w = int(round((b - a) / cell * SUB))
            parts.append(ds.read(1, window=win, out_shape=(H * SUB, w),
                                 resampling=Resampling.nearest))
    if not parts:
        say("  ! GLWD-3 窗口读取失败")
        return np.full((H, W), GLWD3_NODATA, np.uint8)
    ones = np.concatenate(parts, axis=1)[:, :W * SUB]
    if ones.shape[1] < W * SUB:                           # 拼不满就补齐（边缘）
        ones = np.pad(ones, ((0, 0), (0, W * SUB - ones.shape[1])), constant_values=GLWD3_NODATA)
    hit = (ones == SALT_CLASS).astype(np.float32)
    frac = np.zeros((H, W), np.float32)
    for r in range(SUB):
        for c in range(SUB):
            frac += hit[r::SUB, c::SUB]
    frac = frac / float(SUB * SUB) * 100.0
    out = np.full((H, W), GLWD3_NODATA, np.uint8)
    ok = np.zeros((H, W), bool)
    for r in range(SUB):
        for c in range(SUB):
            ok |= ones[r::SUB, c::SUB] != GLWD3_NODATA
    out[ok] = np.clip(np.rint(frac[ok]), 0, 100).astype(np.uint8)
    n = int(((out != GLWD3_NODATA) & (out >= 50)).sum())
    say(f"  盐盘占比：有值 {int(ok.sum()):,} 格；占比 ≥50% 的 {n:,} 格")
    if cache_path:
        np.save(cache_path, out)
        _save_tag(cache_path, CACHE_TAG_PAN)
    return out


# ================================================================ 咸水湖（GLWD-1）
def saline_lakes(W, H, cell, lon0, lat1, zip_path, cache_path=None, log=print):
    """→ (H, W) uint8 掩膜（1 = 该格心落在"闭合盆地湖"面内）。

    只读 `MGLD_TYPE ∈ {closed, closedx}` 的面，**逐格心命中**（与海陆口径同一套做法）。
    """
    say = log or (lambda *a, **k: None)
    if cache_path and os.path.exists(cache_path) and _cache_ok(cache_path, CACHE_TAG_LAKE):
        a = np.load(cache_path)
        if a.shape == (H, W):
            say(f"  咸水湖读缓存 {os.path.basename(cache_path)}")
            return a.astype(np.uint8)
    if not zip_path or not os.path.exists(zip_path):
        say(f"  ! 缺 GLWD-1（{zip_path}），咸水湖跳过（湖一律读淡水湖）")
        return np.zeros((H, W), np.uint8)
    import shapefile
    from shapely.geometry import shape
    from shapely import contains_xy
    z = zipfile.ZipFile(zip_path)
    nm = next(n for n in z.namelist() if n.lower().endswith(".shp"))
    sf = shapefile.Reader(shp=io.BytesIO(z.read(nm)), dbf=io.BytesIO(z.read(nm[:-4] + ".dbf")),
                          encoding="latin-1", encodingErrors="replace")
    flds = [f[0] for f in sf.fields[1:]]
    i_t = flds.index("MGLD_TYPE")
    out = np.zeros((H, W), np.uint8)
    LON = lon0 + (np.arange(W) + 0.5) * cell
    LAT = lat1 - (np.arange(H) + 0.5) * cell
    hit_polys = 0
    for sr in sf.iterShapeRecords():
        if (sr.record[i_t] or "").strip().lower() not in SALINE:
            continue
        g = shape(sr.shape.__geo_interface__)
        b = g.bounds
        if b[2] < lon0 or b[0] > lon0 + W * cell or b[3] < lat1 - H * cell or b[1] > lat1:
            continue
        c0 = max(0, int((b[0] - lon0) / cell) - 1)
        c1 = min(W, int((b[2] - lon0) / cell) + 2)
        r0 = max(0, int((lat1 - b[3]) / cell) - 1)
        r1 = min(H, int((lat1 - b[1]) / cell) + 2)
        if c0 >= c1 or r0 >= r1:
            continue
        LO, LA = np.meshgrid(LON[c0:c1], LAT[r0:r1])
        m = contains_xy(g, LO.ravel(), LA.ravel()).reshape(r1 - r0, c1 - c0)
        out[r0:r1, c0:c1][m] = 1
        hit_polys += 1
    say(f"  咸水湖（GLWD-1 闭合盆地湖）：{hit_polys} 个面 → {int(out.sum()):,} 格")
    if cache_path:
        np.save(cache_path, out)
        _save_tag(cache_path, CACHE_TAG_LAKE)
    return out


CACHE_TAG_POLY = "glwd1-polys-v2"     # v2：掩膜 0/1 → **分型码**（1 湖 2 水库）

LAKE, RESERVOIR = 1, 2                # 分型码。⚠️ 判类别只看 `TYPE`，
                                      # `MGLD_TYPE` 是**盆地属性**（closed/closedx/open/res/""，
                                      # 2,326 个面在那儿是空的），别拿它当类别用。


# ================================================================ 湖面清单（GLWD-1，全部面）
def lake_polygons(W, H, cell, lon0, lat1, zip_path, cache_path=None, log=print):
    """→ (H, W) uint8 **分型码**（0 = 非湖，1 = 湖，2 = 水库）。**"什么算湖"的唯一口径。**

    **为什么需要它**：NE 把里海、咸海、贝加尔、死海、五大湖放在它的**海洋层**里，于是按 NE 的
    海陆口径它们全成了"海洋"；原来靠"LC100 说内陆水体"往回捞，但 LC100 在里海的**浅滩**说那是
    陆地（草本湿地/草原），于是里海里残留 439 格"海洋"（实测其中 393 格落在 GLWD 的里海面内）。
    GLWD-1 是全球湖沼库，窗口内的面**没有一个其实是海**——所以拿它当湖面清单，既不误伤真海
    （黑海/地中海不在里面），又能把里海整块捞回来。

    **v2 起分型**：湖面还要用来把**干涸的湖床接回水**（咸海那一片，见 `生成.py`），
    而**水库的面普遍画得比今天的水面大**（布拉茨克/卡布拉巴萨/下卡马），跟着它走会把湖边的
    **真林子**变成假湖（实测 699 格，其中 290 格是密林）。所以要能区分"湖"与"水库"。
    """
    say = log or (lambda *a, **k: None)
    if cache_path and os.path.exists(cache_path) and _cache_ok(cache_path, CACHE_TAG_POLY):
        a = np.load(cache_path)
        if a.shape == (H, W):
            say(f"  湖面清单读缓存 {os.path.basename(cache_path)}")
            return a.astype(np.uint8)
    if not zip_path or not os.path.exists(zip_path):
        say(f"  ! 缺 GLWD-1（{zip_path}），湖面清单跳过（内海仍靠 LC100 兜底）")
        return np.zeros((H, W), np.uint8)
    import shapefile
    from shapely.geometry import shape
    from shapely import contains_xy
    z = zipfile.ZipFile(zip_path)
    nm = next(n for n in z.namelist() if n.lower().endswith(".shp"))
    sf = shapefile.Reader(shp=io.BytesIO(z.read(nm)), dbf=io.BytesIO(z.read(nm[:-4] + ".dbf")),
                          encoding="latin-1", encodingErrors="replace")
    flds = [f[0] for f in sf.fields[1:]]
    i_type = flds.index("TYPE")
    out = np.zeros((H, W), np.uint8)
    LON = lon0 + (np.arange(W) + 0.5) * cell
    LON = np.where(LON > 180.0, LON - 360.0, LON)
    LAT = lat1 - (np.arange(H) + 0.5) * cell
    n_poly = n_res = 0
    for sr in sf.iterShapeRecords():                 # ⚠️ 别在这个循环里再开一次 iterShapeRecords：
        t = (sr.record[i_type] or "").strip()        #    读取器是迭代器，会被吃掉（踩过）
        code = RESERVOIR if t == "Reservoir" else (LAKE if t == "Lake" else 0)
        if not code:
            continue
        g = shape(sr.shape.__geo_interface__)
        b = g.bounds
        if b[2] < lon0 or b[0] > lon0 + W * cell or b[3] < lat1 - H * cell or b[1] > lat1:
            continue
        c0 = max(0, int((b[0] - lon0) / cell) - 1)
        c1 = min(W, int((b[2] - lon0) / cell) + 2)
        r0 = max(0, int((lat1 - b[3]) / cell) - 1)
        r1 = min(H, int((lat1 - b[1]) / cell) + 2)
        if c0 >= c1 or r0 >= r1:
            continue
        LO, LA = np.meshgrid(LON[c0:c1], LAT[r0:r1])
        m = contains_xy(g, LO.ravel(), LA.ravel()).reshape(r1 - r0, c1 - c0)
        sub = out[r0:r1, c0:c1]
        sub[m] = code
        out[r0:r1, c0:c1] = sub
        n_res += code == RESERVOIR
        n_poly += 1
    n_lake = int((out == LAKE).sum())
    n_r = int((out == RESERVOIR).sum())
    say(f"  湖面清单（GLWD-1）：{n_poly - n_res} 个湖面 + {n_res} 个水库面 → "
        f"湖 {n_lake:,} 格 / 水库 {n_r:,} 格")
    if cache_path:
        np.save(cache_path, out)
        _save_tag(cache_path, CACHE_TAG_POLY)
    return out


def _save_tag(p, tag):
    import json
    with open(p + ".tag", "w", encoding="utf-8") as f:
        json.dump({"encoding": tag}, f)


def _cache_ok(p, tag):
    try:
        import json
        with open(p + ".tag", encoding="utf-8") as f:
            return json.load(f).get("encoding") == tag
    except Exception:                                                         # noqa: BLE001
        return False
