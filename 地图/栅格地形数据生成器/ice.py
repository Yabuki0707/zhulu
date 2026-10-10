# -*- coding: utf-8 -*-
"""海冰：NSIDC「Sea Ice Index v3」逐月范围面 → 每格的**结冰频率**。

**为什么是"频率"而不是"某个月的面"。** 该产品给的是**逐年逐月**的范围面（没有现成的"中位"文件，
见 `地图/栅格地形数据生成器/fetch_map_data.py` 的清单），所以我们拿 1981–2010 的 **30 个 3 月**（北半球冰最多的月份）
逐面叠合：**30 年里有一半以上的年份，这个格被冰盖住** → 读作「海冰」。这是一条**数据自带**的
判据（频率），不是我们划的一条线。

⚠️ **渤海海冰不在这个产品里**：NSIDC 是被动微波、网格 25 km，渤海最宽处才 ~70 km 且只是冬季
边缘结冰，那里常年读成"没有冰"。**渤海冬季封冰对古代军事（走冰、封航）很要紧**，那一份得另找
（中国海洋局的海冰预报没有全球开放栅格）。这是本层**已知的覆盖缺口**，记在 `docs/adr/0014`。

**投影**：该产品是 NSIDC 极射赤面投影（Hughes 1980 椭球），不是经纬度——所以格心要先投影过去
（直接用 shapefile 自带的 .prj，免得椭球参数抄错）。许可：NOAA/NSIDC 公有领域（美国联邦数据）。
"""
from __future__ import annotations

import io
import os
import zipfile

import numpy as np

CACHE_TAG = "nsidc-seaicemar-v1"
# 只算这个纬度以北：北冰洋的冰不会跑到 45°N 以南（渤海那点碎冰本来也不在产品里）。
LAT_MIN = 45.0


def read_sea_ice(W, H, cell, lon0, lat1, zips, cache_path=None, min_frac=1.0, log=print,
                 clean=True):
    """→ (H, W) uint8 掩膜：30 个 3 月范围面里，**命中频率 ≥ min_frac** 的格为 1。

    **默认 min_frac = 1.0（＝"常年"）**：30 个 3 月里**每一年**都被冰盖住才算。理由两条：
      · **语义干净**——"常年海冰"是个说得清的东西，"一半年份有冰"不是；
      · **NSIDC 的"extent"是含 15% 稀疏冰的宽范围**（不是密实冰），门槛取满能把那条毛边压薄。
    实测：≥50% → 826,482 格，**=100% → 736,590 格**。

    **clean=True 会做形态学清理**（需求方报"质量太差"）：25 km 的粗网格采样到 5.86 km 的格上，
    边界全是毛刺、冰区里还夹着 3 万个针孔。所以：**填掉 < 200 格的洞、去掉 < 50 格的碎块**。
    这一条是**显示整形**（不是判据），写在这里免得下一个人以为毛边是数据本来的样子。
    """
    say = log or (lambda *a, **k: None)
    if cache_path and os.path.exists(cache_path) and _cache_ok(cache_path):
        a = np.load(cache_path)
        if a.shape == (H, W):
            say(f"  海冰读缓存 {os.path.basename(cache_path)}")
            return a.astype(np.uint8)
    zips = [p for p in (zips or []) if p and os.path.exists(p)]
    if not zips:
        say("  ! 缺 NSIDC 海冰范围面，海冰类不会出现")
        return np.zeros((H, W), np.uint8)

    import shapefile
    from pyproj import CRS, Transformer
    from shapely.geometry import shape
    from shapely import contains_xy

    # 只取 LAT_MIN **以北**的格心（行序自北向南，所以是**第 0 行起、到 LAT_MIN 那一行为止**），
    # 投影一次、30 个面共用。
    # ⚠️ 这里踩过一次：写成 `arange(r0, H)` 就把纬度带取反了（取成 45°N 以**南**），
    # 结果只捞到鄂霍次克海那条 44–45°N 的冰缘（实测 2,766 格），北极主体一格没有 ——
    # 由 `check_terrain` 的「拉普捷夫海读成海洋」那一条抓住。
    r1 = min(H, int(np.floor((lat1 - LAT_MIN) / cell)) + 1)
    LAT = lat1 - (np.arange(0, r1) + 0.5) * cell
    LON = lon0 + (np.arange(W) + 0.5) * cell
    LON = np.where(LON > 180.0, LON - 360.0, LON)
    LO, LA = np.meshgrid(LON, LAT)
    z = zipfile.ZipFile(zips[0])
    prj = next((n for n in z.namelist() if n.lower().endswith(".prj")), None)
    crs = CRS.from_wkt(z.read(prj).decode("latin-1")) if prj else CRS.from_epsg(3411)
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    X, Y = tr.transform(LO.ravel(), LA.ravel())
    say(f"  读 NSIDC 海冰范围面 {len(zips)} 个（3 月，1981–2010），投影 {crs.name[:38]}")

    cnt = np.zeros(LO.size, np.int32)
    for i, p in enumerate(zips):
        zz = zipfile.ZipFile(p)
        nm = next(n for n in zz.namelist() if n.lower().endswith(".shp"))
        sf = shapefile.Reader(shp=io.BytesIO(zz.read(nm)),
                              dbf=io.BytesIO(zz.read(nm[:-4] + ".dbf")),
                              encoding="latin-1", encodingErrors="replace")
        for sr in sf.iterShapeRecords():
            b = sr.shape.bbox
            m = (X >= b[0]) & (X <= b[2]) & (Y >= b[1]) & (Y <= b[3])
            if not m.any():
                continue
            g = shape(sr.shape.__geo_interface__)
            cnt[m] += contains_xy(g, X[m], Y[m])
        if (i + 1) % 10 == 0:
            say(f"      … {i + 1}/{len(zips)} 个面")
    freq = cnt / float(len(zips))
    hit = (freq >= min_frac).reshape(LO.shape)
    if clean:
        from scipy import ndimage as nd
        # 填小洞（<200 格）与去碎块（<50 格）——只作用于**这一层自己的掩膜**，不碰别的轴
        filled = nd.binary_fill_holes(hit)
        holes = filled & ~hit
        hl, hn = nd.label(holes)
        if hn:
            hs = nd.sum(np.ones_like(hl), hl, range(1, hn + 1))
            for i, sz in enumerate(hs, start=1):
                if sz < 200:
                    hit |= (hl == i)
        lab, n = nd.label(hit)
        if n:
            sizes = nd.sum(np.ones_like(lab), lab, range(1, n + 1))
            drop = {i for i, sz in enumerate(sizes, start=1) if sz < 50}
            if drop:
                hit &= ~np.isin(lab, list(drop))
    out = np.zeros((H, W), np.uint8)
    out[0:r1] = hit.astype(np.uint8)
    say(f"  海冰（{len(zips)} 个 3 月里 ≥{min_frac:.0%} 被冰盖住）：{int(out.sum()):,} 格")
    if cache_path:
        np.save(cache_path, out)
        import json
        with open(cache_path + ".tag", "w", encoding="utf-8") as f:
            json.dump({"encoding": CACHE_TAG}, f)
    return out


def _cache_ok(p):
    try:
        import json
        with open(p + ".tag", encoding="utf-8") as f:
            return json.load(f).get("encoding") == CACHE_TAG
    except Exception:                                                         # noqa: BLE001
        return False
