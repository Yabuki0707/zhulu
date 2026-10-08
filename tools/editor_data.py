# -*- coding: utf-8 -*-
"""`地图编辑器/js/data.js` 的唯一写入口。

为什么单独一个模块：这份文件现在由**两条路**共同维护——
`tools/build_raster.py`（管线重建后写）与 `tools/import_editor.py`（编辑器草稿合入后写）。
两边各写一遍必然分叉（旧账就是把编辑器数据拷一份到 `地图编辑器/data/`，
靠"每次构建时拷贝"保持一致，见 `docs/adr/0002`）。所以生成逻辑收在这里，两边都调它。

它只做两件事：
  1. 给四张图层的路径补上 `mapdata.URL_PREFIX`（`/数据/…`）——编辑器不猜路径；
  2. 把 payload 序列化成 `js/data.js`。

与 `tools/data.js` 无关；编辑器读的是 `地图/地图编辑器/js/data.js`。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import URL_PREFIX                       # noqa: E402

# 图层文件名 → payload 里的键
LAYERS = {
    "plot_png": "地块编码.png",
    "terrain_png": "地形编码.png",
    "climate_png": "气候编码.png",       # v2 产品层：森林那四种绿由它派生（ADR 0006）
    "dist_png": "分区编码.png",
    "ref_vec": "参考顶点.bin",
}

HEADER = ("/* 由 tools/editor_data.py 生成（build_raster.py / import_editor.py 都调它），勿手改 */\n")


def with_layer_urls(payload: dict) -> dict:
    """把四张图层的路径补成 `/数据/<文件名>`。"""
    out = dict(payload)
    for key, fn in LAYERS.items():
        out[key] = URL_PREFIX + fn
    return out


def write_data_js(payload: dict, app_dir: str | None = None) -> str:
    """写 `地图/地图编辑器/js/data.js`，返回写入的路径。

    payload 传的是"语义"部分（grid / terrain_legend / plots / palette / domains /
    districts / base_tag / land_rule），图层 URL 由本模块补。
    """
    if app_dir is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        app_dir = os.path.join(root, "地图", "地图编辑器")
    path = os.path.join(app_dir, "js", "data.js")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = json.dumps(with_layer_urls(payload), ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER)
        f.write("export const RASTER_DATA = " + body + ";\n")
    return path
