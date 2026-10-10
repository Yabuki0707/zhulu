# -*- coding: utf-8 -*-
"""地表**材质**：沙 vs 砾／岩 —— GSDP30（全球 30 m 沙丘形态图）→ 每格「有沙占比」。

**为什么不用土壤数据。** 先试的是 ISRIC SoilGrids 2.0 的粗碎屑（`cfvo` ≥2 mm 体积千分比）与
沙粒占比（`sand`），**实测不可用**：全球 1 km 聚合版在本图窗口内，塔克拉玛干（纯沙海）读
177‰ 而蒙古戈壁（砾漠）读 171‰ —— 分不开；换成 `sand` 更糟，塔克拉玛干读 303‰（真沙海应
900‰ 以上）。原因是沙漠里实测土壤剖面极少，模型在那一带基本是区域均值回归，边界是假的。
**沙是与不是沙，遥感看得见、土壤模型猜不着**，所以改用光学遥感产品。

**用什么。** GSDP30（Global Sand Dune Pattern map, 30 m，Gao et al.，Zenodo
doi:10.5281/zenodo.13907012，**CC BY 4.0**，须署名）。331 个 460.8 km 见方的瓦片（EPSG:3857，
30 m，15360²），Landsat 合成的深度学习分类。**它的图例自己就是二元判据**（`ClassificationScheme.xlsx`）：

    0 新月形  1 复合新月形  2 线形  3 复合线形  4 穹丘  5 星状  6 网状  7 枝状  8 沙席  10 抛物线
    ── 以上十类 = **沙**（沙丘与沙席）
    9  Others = 「**没有被沙覆盖的地面**，如非沙地表上的农田、**砾石**、**裸岩**」= **非沙**
    255 = 无数据（水体、冰川、非研究区）

**判据因此是数据自带的，不是我们划的**：一格的有沙占比 ≥ `SAND_MIN_PCT` 读作沙质（沙漠），
否则读作砾／岩质（戈壁）。占比是「沙像素 / 有效像素」，与 LC100 的取样口径一致。

**实测校准**（NE 自然地理区的命名沙漠面，见下方 `_probe` 的同类做法）：
    沙海——塔克拉玛干 93% ｜ 辛普森 97% ｜ 鲁卜哈利 84% ｜ 大沙沙漠 82% ｜ 大维多利亚 74%
          ｜ 内夫得 70% ｜ 塔尔 53% ｜ 卡拉库姆 51%
    砾漠——大漠（蒙古戈壁）7.7% ｜ 努比亚 6.5% ｜ 卢特 8.3% ｜ 卡维尔盐漠 5.4% ｜ 内盖夫 0%
    撒哈拉整片 26%——**这是对的**：撒哈拉只有约五分之一是沙，其余是砾漠与岩漠。
"""
from __future__ import annotations

import io
import math
import os
import zipfile

import numpy as np

NODATA = 255
# 图例里属于「沙」的类：0–8 的十种沙丘形态之外，10 是抛物线沙丘。**9 不在其中**（非沙）。
SAND_CLASSES = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10)
_SAND_LUT = np.zeros(256, bool)
_SAND_LUT[list(SAND_CLASSES)] = True

PX = 30.0                      # 瓦片像素边长（米，EPSG:3857）
R = 6378137.0                  # 球半径（Web 墨卡托）
CACHE_TAG = "gsdp30-sandfrac-v1"


def merc_x(lon_deg):
    return np.asarray(lon_deg, np.float64) * math.pi / 180.0 * R


def merc_y(lat_deg):
    return R * np.log(np.tan(math.pi / 4.0 + np.radians(np.asarray(lat_deg, np.float64)) / 2.0))


def inv_merc_y(y):
    return np.degrees(2.0 * np.arctan(np.exp(np.asarray(y, np.float64) / R)) - math.pi / 2.0)


def _tiles(zf):
    """列出瓦片与其墨卡托范围（瓦片名是按左上角经纬度命名的，但**以 TIFF 标签为准**）。"""
    import tifffile
    out = []
    for n in zf.namelist():
        if not n.lower().endswith(".tif"):
            continue
        with tifffile.TiffFile(io.BytesIO(zf.read(n))) as tf:
            pg = tf.pages[0]
            _, _, _, x0, y0, _ = pg.tags["ModelTiepointTag"].value
            h, w = pg.shape[0], pg.shape[1]
        out.append((float(x0), float(y0), w, h, n))
    return out


def read_sand_fraction(W, H, cell, lon0, lat1, zip_path, cache_path=None, log=print):
    """→ (H, W) uint8：每格**有沙占比**（百分数，0–100）；无有效像素处 255。

    做法：游戏格是**经纬度矩形**，在 Web 墨卡托里仍是**轴对齐矩形**，所以一格落在瓦片里的
    就是一块矩形区域 —— 用「按行求和 + 前缀和」取矩形和，是**精确**的，不是抽样估计。
    """
    say = log or (lambda *a, **k: None)
    if cache_path and os.path.exists(cache_path) and _cache_ok(cache_path):
        try:
            a = np.load(cache_path)
            if a.shape == (H, W):
                say(f"  沙丘占比读缓存 {os.path.basename(cache_path)}")
                return a.astype(np.uint8)
        except Exception:                                                     # noqa: BLE001
            pass
    if not zip_path or not os.path.exists(zip_path):
        say(f"  ! 缺 GSDP30（{os.path.basename(zip_path or '')}），材质层全给无数据"
            "（沙漠/戈壁 将退化成同一个名字）")
        return np.full((H, W), NODATA, np.uint8)

    zf = zipfile.ZipFile(zip_path)
    tiles = _tiles(zf)
    lon_left_all = [t[0] / R * 180.0 / math.pi for t in tiles]
    say(f"  读 GSDP30 沙丘形态（{len(tiles)} 片 EPSG:3857 瓦片，30 m，CC BY 4.0）")

    sand = np.zeros((H, W), np.int32)
    valid = np.zeros((H, W), np.int32)
    nl = lon0
    nr = lon0 + W * cell                 # 右界（≈226°，日界线以东）
    bs = cell                            # 每米卡托经度跨度：lon 线性，直接换算
    for ti, (x0, y0, w, h, name) in enumerate(tiles):
        L0 = x0 / R * 180.0 / math.pi
        L1 = (x0 + w * PX) / R * 180.0 / math.pi
        if L1 < nl or L0 > nr:
            continue
        top = float(inv_merc_y(y0))
        bot = float(inv_merc_y(y0 - h * PX))
        if bot > lat1 or top < lat1 - H * cell:
            continue
        # 覆盖到的游戏行列（各留 1 格余量，避免共边格漏掉）
        c0 = max(0, int(math.floor((L0 - nl) / bs)) - 1)
        c1 = min(W, int(math.floor((L1 - nl) / bs)) + 2)
        r0 = max(0, int(math.floor((lat1 - top) / bs)) - 1)
        r1 = min(H, int(math.floor((lat1 - bot) / bs)) + 2)
        if c0 >= c1 or r0 >= r1:
            continue
        a = tifffile_imread(zf, name)
        sf = _SAND_LUT[a]                     # bool：是沙
        vf = a != NODATA
        for gr in range(r0, r1):
            la_hi = lat1 - gr * bs            # 该格上边界纬度
            la_lo = la_hi - bs
            y_hi, y_lo = float(merc_y(la_hi)), float(merc_y(la_lo))
            rr0 = max(0, int(math.floor((y0 - y_hi) / PX)))
            rr1 = min(h, int(math.ceil((y0 - y_lo) / PX)))
            if rr0 >= rr1:
                continue
            rowsum_s = sf[rr0:rr1].sum(axis=0, dtype=np.int32)
            rowsum_v = vf[rr0:rr1].sum(axis=0, dtype=np.int32)
            cs_s = np.concatenate(([0], np.cumsum(rowsum_s)))
            cs_v = np.concatenate(([0], np.cumsum(rowsum_v)))
            cols = np.arange(c0, c1)
            lo = merc_x(nl + cols * bs)
            hi = merc_x(nl + (cols + 1) * bs)
            cc0 = np.clip(((lo - x0) / PX).astype(np.int64), 0, w)
            cc1 = np.clip(np.ceil((hi - x0) / PX).astype(np.int64), 0, w)
            sand[gr, cols] += cs_s[cc1] - cs_s[cc0]
            valid[gr, cols] += cs_v[cc1] - cs_v[cc0]
        del a, sf, vf
        if log and (ti + 1) % 40 == 0:
            say(f"      … {ti + 1}/{len(tiles)} 片")

    out = np.full((H, W), NODATA, np.uint8)
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.rint(sand.astype(np.float64) / np.maximum(valid, 1) * 100.0)
    ok = valid > 0
    out[ok] = np.clip(frac[ok], 0, 100).astype(np.uint8)
    say(f"  沙丘占比：有值 {int(ok.sum()):,} 格 / 无数据 {int((~ok).sum()):,} 格"
        + (f"；有沙>0 的格 {int((out[ok] > 0).sum()):,}" if ok.any() else ""))
    if cache_path:
        np.save(cache_path, out)
        import json
        with open(cache_path + ".tag", "w", encoding="utf-8") as f:
            json.dump({"encoding": CACHE_TAG}, f)
    return out


def tifffile_imread(zf, name):
    import tifffile
    return tifffile.imread(io.BytesIO(zf.read(name)))


def _cache_ok(cache_path):
    try:
        import json
        with open(cache_path + ".tag", encoding="utf-8") as f:
            return json.load(f).get("encoding") == CACHE_TAG
    except Exception:                                                         # noqa: BLE001
        return False


# ================================================================ 自检（CLI）
# **拿 NE 自然地理区的「命名沙漠面」当校验器**：这些面的名字里就写着材质——Erg／Sand Sea／
# 沙海是沙，Hamada（石漠）／Reg（砾漠）／Kavir（盐漠）不是沙。投影或图例一旦取错，下面会红。
#
# ⚠️ **不要拿单个点当校验**：沙海内部有砾质走廊，随便取一点可能正好落在走廊里（试过——大沙
# 沙漠的一个点读 0.2%，而整个面读 82%）。所以校验一律取面的面积中位，不取点。
#
# 期望区间是**数据集自己的图例推出来的**，不是照着测出来的数字反填的。撒哈拉给 (12, 40)
# 是刻意的：它整片只有约五分之一是沙，若哪天它读到 80% 就说明投影错了。
PROBES = [
    ("塔克拉玛干沙漠", 70, 100, "沙海"),
    ("辛普森沙漠", 70, 100, "沙海"),
    ("大沙沙漠", 60, 100, "沙海"),
    ("大维多利亚沙漠", 60, 100, "沙海"),
    ("鲁卜哈利沙漠", 60, 100, "沙海"),
    ("內夫得沙漠", 55, 100, "沙海"),
    ("塔尔沙漠", 40, 100, "沙海"),
    ("大漠", 0, 25, "砾漠（蒙古戈壁）"),
    ("努比亞沙漠", 0, 25, "砾漠"),
    ("盧特沙漠", 0, 25, "砾漠"),
    ("內蓋夫", 0, 15, "砾漠／黄土"),
    ("東部沙漠", 0, 15, "砾漠"),
    ("撒哈拉沙漠", 12, 40, "沙只占约五分之一"),
]


def _measure_polygon(zf, tiles, geom, step=0.05):
    """一个面内的有沙占比（只统计落在瓦片里的样本）。"""
    from shapely import contains_xy
    b = geom.bounds
    lons = np.arange(max(b[0], 25.0), min(b[2], 226.0), step)
    lats = np.arange(max(b[1], -48.1), min(b[3], 82.0), step)
    if lons.size == 0 or lats.size == 0:
        return None
    LO, LA = np.meshgrid(lons, lats)
    m = contains_xy(geom, LO.ravel(), LA.ravel())
    if m.sum() < 50:
        return None
    X = merc_x(LO.ravel()[m])
    Y = merc_y(LA.ravel()[m])
    tot = totv = 0
    for x0, y0, w, h, name in tiles:
        k = (X >= x0) & (X < x0 + w * PX) & (Y <= y0) & (Y > y0 - h * PX)
        if not k.any():
            continue
        a = tifffile_imread(zf, name)
        ix = ((X[k] - x0) // PX).astype(np.int64)
        iy = ((y0 - Y[k]) // PX).astype(np.int64)
        v = a[iy, ix]
        ok = v != NODATA
        totv += int(ok.sum())
        tot += int(_SAND_LUT[v[ok]].sum())
    return (tot / totv * 100.0, totv) if totv >= 100 else None


def _probe(zip_path, ne_zip, log=print):
    import io as _io
    import shapefile
    from shapely.geometry import shape
    zf = zipfile.ZipFile(zip_path)
    tiles = _tiles(zf)
    zz = zipfile.ZipFile(ne_zip)
    shp = shapefile.Reader(shp=_io.BytesIO(zz.read("ne_10m_geography_regions_polys.shp")),
                           dbf=_io.BytesIO(zz.read("ne_10m_geography_regions_polys.dbf")))
    fl = [f[0] for f in shp.fields[1:]]
    IF, IZ = fl.index("FEATURECLA"), fl.index("NAME_ZH")
    geoms = {}
    for sr in shp.iterShapeRecords():
        if sr.record[IF] == "Desert":
            geoms.setdefault(sr.record[IZ], shape(sr.shape.__geo_interface__))
    bad = 0
    for name, lo, hi, note in PROBES:
        g = geoms.get(name)
        if g is None:
            log(f"  ! NE 里找不到「{name}」"); bad += 1; continue
        r = _measure_polygon(zf, tiles, g)
        if r is None:
            log(f"  ! {name}：样本不足"); bad += 1; continue
        got, n = r
        mark = "✓" if lo <= got <= hi else "✗"
        if mark == "✗":
            bad += 1
        log(f"  {mark} {name:12s}{got:6.1f}%  期望 {lo}–{hi}%  （{note}，n={n}）")
    log(f"  {'全部通过 ✓' if not bad else f'!! {bad} 项不符'}")
    return bad


if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mapdata as MD
    ap = argparse.ArgumentParser(description="GSDP30 沙丘形态自检（对 NE 命名沙漠面）")
    ap.add_argument("--zip", default=MD.DUNE_ZIP)
    ap.add_argument("--ne", default=MD.NE_REGIONS)
    a = ap.parse_args()
    print(f"源文件：{a.zip}\n存在：{os.path.exists(a.zip)}")
    _probe(a.zip, a.ne)

