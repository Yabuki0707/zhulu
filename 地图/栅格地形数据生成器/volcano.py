# -*- coding: utf-8 -*-
"""火山：Smithsonian GVP「Volcanoes of the World」全新世火山 → 每格一个 0/1 掩膜。

**为什么是点。** 火山本来就是**一座一座的点**，不是面：GVP 的全新世（Holocene）清单给 1,214 座，
本图窗口内 **604 座**，带坐标与 `Volcanic_Landform`（Composite/Shield/Caldera/Cluster…）。
落到我们 5.86 km 的格上，就是"这座格上有活火山"。

⚠️ **这是点类，不是面类**：所以「火山」在图上会是**孤立的单格**，不会连成片。
要成片的**熔岩台地／火山岩区**（长白山玄武岩台地、富士山、腾冲、五大连池那类），
得用岩性面数据（GLiM／GLHYMPS 2.0，ODbL）——那是 160 万面、GB 级的下载，本次不做，
记在 `docs/adr/0014` 的"明确不做"里。

数据取法：`地图/栅格地形数据生成器/fetch_map_data.py` 的 `--group volcano`（GVP 的 WFS 接口直接给 GeoJSON）。
许可：Smithsonian GVP，**CC BY 4.0**（须署名）。
"""
from __future__ import annotations

import json
import os

import numpy as np

CACHE_TAG = "gvp-holocene-v1"


def read_volcanoes(W, H, cell, lon0, lat1, geojson_path, cache_path=None, log=print):
    """→ (H, W) uint8 掩膜（1 = 该格有全新世火山）。"""
    say = log or (lambda *a, **k: None)
    if cache_path and os.path.exists(cache_path) and _cache_ok(cache_path):
        a = np.load(cache_path)
        if a.shape == (H, W):
            say(f"  火山读缓存 {os.path.basename(cache_path)}")
            return a.astype(np.uint8)
    if not geojson_path or not os.path.exists(geojson_path):
        say(f"  ! 缺 GVP 火山点（{geojson_path}），火山类不会出现")
        return np.zeros((H, W), np.uint8)

    with open(geojson_path, encoding="utf-8") as f:
        gj = json.load(f)
    out = np.zeros((H, W), np.uint8)
    lon1, lat0 = lon0 + W * cell, lat1 - H * cell
    n = 0
    for ft in gj.get("features", []):
        c = ft.get("geometry", {}).get("coordinates")
        if not c:
            continue
        lon, lat = float(c[0]), float(c[1])
        if not (lon0 <= lon < lon1 and lat0 <= lat < lat1):
            continue
        x, y = int((lon - lon0) / cell), int((lat1 - lat) / cell)
        if 0 <= x < W and 0 <= y < H:
            out[y, x] = 1
            n += 1
    say(f"  火山（GVP 全新世，落在窗口内）：{n} 座 → {int(out.sum())} 格")
    if cache_path:
        np.save(cache_path, out)
        with open(cache_path + ".tag", "w", encoding="utf-8") as f:
            json.dump({"encoding": CACHE_TAG}, f)
    return out


def _cache_ok(p):
    try:
        with open(p + ".tag", encoding="utf-8") as f:
            return json.load(f).get("encoding") == CACHE_TAG
    except Exception:                                                         # noqa: BLE001
        return False
