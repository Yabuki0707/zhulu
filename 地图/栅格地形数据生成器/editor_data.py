# -*- coding: utf-8 -*-
"""`地图编辑器/js/data.js` 的唯一写入口。

为什么单独一个模块：这份文件现在由**两条路**共同维护——
`地图/栅格地形数据生成器/生成.py`（管线重建后写）与 `tools/import_editor.py`（编辑器草稿合入后写）。
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

HEADER = ("/* 由 地图/栅格地形数据生成器/editor_data.py 生成（生成.py / import_editor.py 都调它），勿手改 */\n")


def payload_from_meta(meta: dict, palette: list) -> dict:
    """`台账.json` + 调色板 → data.js 的 payload。**两个写入方都调这一个函数。**

    为什么必须收成一处：`生成.py`（管线重建后写）与 `import_editor`（草稿合入后写）
    原先各自拼一份 payload，于是**同一份台账会写出两份键不同的 data.js**——实测的区别是
    `import_editor` 那份漏了 `block_rule`、键序也不同。这两个键眼下没有 JS 消费者（是给人看
    的口径说明），所以漏了不报错，但"两份产物必然分叉"这件事本身就是 `docs/adr/0002` 要禁的
    （base_tag 的图例已经因为两边各拼一份而分叉过一次，见 `build_raster.LEGEND_FOR_TAG`）。

    `plots` 一律取台账原样（`{"id","name","domain"}`，domain 允许空串）：
    以前 `import_editor` 会把空的 domain 键省掉，于是同一份台账在两边是**两种形状**——
    编辑器 seedPlots 要按 `p.domain !== undefined` 判，形状一变就是一条静默分支。
    """
    import climate as CL                                              # noqa: E402
    import display_class as DC                                        # noqa: E402
    cg = meta.get("cover_legend") or meta.get("terrain_legend") or {}
    cover = [cg[str(i)] for i in range(len(cg))]
    fg = meta.get("form_legend") or {}
    form = [fg[str(i)] for i in range(len(fg))]
    return {
        "grid": meta["grid"],
        "cover_legend": cover,
        "form_legend": form,
        # 气候层：两轴的名字与编码（v2 起气候是**产品层**，见 docs/adr/0006）
        "climate_legend": {"heat": list(CL.HEAT_NAMES), "moist": list(CL.MOIST_NAMES),
                           "encoding": "热量带 × 8 + 干湿（0..31）；干湿 = 0 读作寒带",
                           "note": meta.get("climate_rule", "")},
        # 显示类 = 覆盖 × 形态 × 气候 的组合 = 地形（v4）：类清单 + 组合查表
        **DC.payload(),
        "plots": [{k: v for k, v in p.items()
                   if k in ("id", "name", "domain")} for p in meta.get("plots", [])],
        "palette": palette,
        "domains": [{"g": g["geo"], "d": d} for g in palette for d in g["domains"]],
        "districts": meta.get("districts", []),
        "block_rule": meta.get("block_rule", ""),
        "base_tag": meta.get("base_tag", ""),
        "land_rule": meta.get("land_rule", ""),
    }


def write_from_meta(meta_path: str, app_dir: str | None = None) -> tuple[str, str]:
    """从 `台账.json` **原地重写** data.js。→ (写出的路径, base_tag)。

    为什么单独有这个入口：改了显示类的名字或配色（`地图/栅格地形数据生成器/display_class.py`）之后，
    真源那几张图**一个字节都不用变**，要变的只有 data.js。跑一遍完整管线（读 ETOPO、
    LC100、柯本，十几分钟）只为刷新一张查表，纯属浪费；而"从台账重算"的路径与
    `生成.py` 收尾那一步调的是同一个函数，产物一致。
    用法：`python 地图/栅格地形数据生成器/editor_data.py`
    """
    import json                                                       # noqa: E402
    import os                                                         # noqa: E402
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from 附录C import load_palette                             # noqa: E402
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    path = write_data_js(payload_from_meta(meta, load_palette()), app_dir)
    return path, meta.get("base_tag", "")


def with_layer_urls(payload: dict) -> dict:
    """把四张图层的路径补成 `/数据/<文件名>`。"""
    out = dict(payload)
    for key, fn in LAYERS.items():
        out[key] = URL_PREFIX + fn
    return out


def write_data_js(payload: dict, app_dir: str | None = None) -> str:
    """写 `地图/地图编辑器/js/data.js`，返回写入的路径。

    payload 传的是"语义"部分（grid / cover_legend / form_legend / climate_legend /
    display_classes / display_lut / plots / palette / domains / districts / block_rule /
    base_tag / land_rule）。**别自己拼 payload**：两个写入方统一走 `payload_from_meta()`，
    图层 URL 由本模块补。
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


if __name__ == "__main__":
    # 原地刷新 data.js（改了显示类名字/配色之后用；不动真源那几张图）
    from mapdata import GRID_META
    p, tag = write_from_meta(GRID_META)
    print(f"已重写 {p}（base_tag {tag}）")
