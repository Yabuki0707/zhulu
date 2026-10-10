# -*- coding: utf-8 -*-
"""落盘与契约 —— 生成流程的第 6 步。

本文件由 `_拆分.py` 从原来的单坨 `生成.py` **逐字搬**出来，只做了两件机械事：
缩进回退 4 格、跨阶段的状态名换成 `ctx.xxx`。**改判据要连着 `管线.py` 的阶段表一起看**
（顺序即语义：后一步压前一步）。
"""
from __future__ import annotations

from __future__ import annotations

import json
import numpy as np
import os
import shutil

from PIL import Image
from basetag import base_tag as make_base_tag
from display_class import note as _disp_note
from editor_data import write_data_js, payload_from_meta
from mapdata import ROOT
from mapdata import URL_PREFIX
from refvec import build_ref_vector
from 栅格工具 import assert_contract
from 栅格工具 import tang_rings
from 栅格工具 import write_runtime
from 附录C import load_palette
import climate as CL
import terrain as TR

from 契约 import (
    FORM_LEGEND, F_CLIM, F_DIST, F_META, F_PLOT, F_REFV, F_TERRAIN, LAT0, LAT1, LEGEND_FOR_TAG,
    LON0, LON1, OUT, TERRAIN_LEGEND,
)


def run(ctx) -> None:
    """跑这一步。日志走 `ctx.log`（界面上是实时日志框）。"""
    Image.fromarray(TR.pack(ctx.地形, ctx.形态), "L").save(os.path.join(OUT, F_TERRAIN),
                                                     optimize=True)

    # ---------------- 参考层：矢量顶点（不再是栅格掩膜） ----------------
    tang = tang_rings(ctx.参数.cell)
    ctx.参考信息 = build_ref_vector(ctx.单元们, ctx.层级, ctx.参数.cell, LON0, LAT1, tang, os.path.join(OUT, F_REFV))

    ctx.覆盖计数 = np.bincount(ctx.地形.ravel(), minlength=len(TERRAIN_LEGEND))
    ctx.占比 = {TERRAIN_LEGEND[i]: round(int(c) / ctx.地形.size, 4)
             for i, c in enumerate(ctx.覆盖计数) if c}
    ctx.形态计数 = np.bincount(ctx.形态.ravel(), minlength=len(FORM_LEGEND))
    form_ratio = {FORM_LEGEND[i]: round(int(c) / ctx.形态.size, 4)
                  for i, c in enumerate(ctx.形态计数) if c}
    # **数据契约断言**放在落盘之前（ADR 0006）：4 位覆盖、14 位地块、8 位块区局部码，
    # 余量都不大，而"余量用尽"的后果是静默截断——宁可让管线在这一步红掉。
    from display_class import note as _disp_note
    assert_contract(ctx.地形, ctx.形态, ctx.地块码, ctx.块区台账, ctx.热量带, ctx.干湿, ctx.气候类, ctx.LAT, ctx.陆地, log=print)
    write_runtime(ctx.地形, ctx.形态, ctx.地块码, ctx.块区局部, ctx.热量带, ctx.干湿, ctx.W, ctx.H, ctx.参数.cell,
                  os.path.join(os.path.dirname(OUT), "运行态"), log=print)
    # 底图指纹：写进台账，也写进 data.js。import_editor 要靠它判断草稿是否基于旧底图
    # （工单 §3.3、§4.2 第 2 步），所以必须在 meta 落盘**之前**算出来。
    # ⚠️ 图例一律走 LEGEND_FOR_TAG（覆盖＋形态），与 import_editor._legend 同口径——见那里的说明。
    ctx.指纹 = make_base_tag(ctx.参数.cell, ctx.W, ctx.H, len(ctx.种子), ctx.覆盖格数,
                             [s["n"] for s in ctx.种子], LEGEND_FOR_TAG)
    ctx.台账 = {
        "grid": {"lon0": LON0, "lon1": LON1, "lat0": LAT0, "lat1": LAT1, "cell": ctx.参数.cell,
                 "w": ctx.W, "h": ctx.H,
                 "note": "经度折回连续（>180 为日界线以东）；行序自北向南"},
        "cover_legend": {str(i): n for i, n in enumerate(TERRAIN_LEGEND)},
        "form_legend": {str(i): n for i, n in enumerate(FORM_LEGEND)},
        "cover_ratio": ctx.占比,
        "form_ratio": form_ratio,
        "plot_id_encoding": "R + G*256（0 = 无地块）",
        "dist_id_encoding": "8 位灰度 = **地块内的局部序号**（0 = 无块区）；全局块区 id 见台账 districts 的 (plot, local)",
        "terrain_encoding": "8 位灰度 = 覆盖（**高 5 位**）× 8 + 形态（低 3 位）；解包见 地图/栅格地形数据生成器/terrain.py 的 unpack（docs/adr/0007、0014）。最大字节 251",
        "land_rule": "陆地 = Natural Earth 10m 陆地 ∪ 湖泊 ∪ 冰川区（格心命中）；"
                     "地形层的「海洋」是该掩膜的补集，地块层也被它裁过",
        "cover_rule": "覆盖 = LC100 土地覆盖**一码一类、纯直通**（郁闭林→密林、疏林→疏林、"
                      "灌木→灌丛、草本→草原、耕地/建成区→草甸、冰雪→冰川、"
                      "内陆水→淡湖、草本湿地→沼泽、苔藓地衣→苔原）；"
                      "**裸地（LC100 60）按材质再拆两类**——GSDP30 有沙占比 ≥ 50% 读「沙质裸地」，"
                      "否则「砾质裸地」（沙与砾分不开：塔克拉玛干与蒙古戈壁在柯本里同属 BWk，"
                      "见 docs/adr/0012）；"
                      "**v9 又加四类**（`adr/0014`）："
                      "海冰 = NSIDC 1981–2010 的 30 个 3 月里 ≥50% 盖住该格；"
                      "咸湖 = 湖 ∧ GLWD-1 闭合盆地（同片水整体定咸淡）；"
                      "盐漠 = 无植被地表 ∧ GLWD-3 第 7 类盐盘占格内多数；"
                      "火山 = GVP 全新世火山点落在该格。"
                      "**v10 一条**（`adr/0014` §九）：干涸的湖床回水 —— GLWD-1 的**湖**面内"
                      "（水库不算）、今天读沙质/砾质裸地或草甸/草原的格，接回「湖」（咸海那一片）。"
                      "另有三个**派生类**："
                      "绿洲 = 耕地/建成区 ∧ 真沙漠 BWh/BWk；盐沼 = 草本湿地 ∧ 贴海；"
                      "滩涂 = 贴海 ∧ 格内水占比 ≥ 30%。"
                      "**沙漠/戈壁/寒漠/盐漠/咸湖 这些名字不存储**，"
                      "由「覆盖 × 形态 × 气候」派生（见 ADR 0006、0010、0012、0014）",
        "climate_rule": "气候 = 柯本两轴：热量带（热带/亚热带/温带/亚寒带）"
                        "× 干湿（干旱/半干旱/冬干/冬雨/夏雨/季风/常湿）。**热量带一律由柯本自己的码给、"
                        "不做任何几何切分**（`adr/0011`）：A 组 ＋ 热的 B 组（BWh/BSh，年均 ≥ 18℃）→ 热带；"
                        "C 组 → 亚热带；D 组暖半 ＋ 冷的 B 组（BWk/BSk）→ 温带；D 组冷半 → 亚寒带。"
                        "**寒带不占热量带取值**，由干湿码 0 表示；海洋格上的气候码无意义",
        "display_rule": _disp_note(),
        "river_rule": "河流 = HydroRIVERS v1.0（流量 ≥ 默认 100 m³/s）∪ Natural Earth 河线，"
                      "按 supercover 逐格点燃（4 邻接连通）；再补「水体占比 ≥ 30% 且与水面相连」"
                      "的碎水格（河口/三角洲，逐格众数会把它们藏成陆地）。河线穿过的格不算海洋",
        "water_rule": TR.water_frac_note(),
        "climate": {"source": "Beck et al. 2023, Scientific Data 10:724（CC BY 4.0）",
                    "member": CL.KOPPEN_MEMBER,
                    "grid": "1 km（0.00833333°），现值期 1991–2020",
                    "arid": list(CL.ARID),
                    "heat_names": list(CL.HEAT_NAMES),
                    "moist_names": list(CL.MOIST_NAMES),
                    "encoding": "热量带 × 8 + 干湿（0..31）；干湿 = 0 读作寒带"},
        "ref_encoding": "参考顶点.bin：ZLRV1 魔数 + 环表 + 格坐标×8 的 uint16 顶点对",
        "base_tag": ctx.指纹,
        "districts": ctx.块区台账,
        "block_rule": "块区 = 地块的下一级行政单元（中华＝县；世界暂无二级，每地块 1 个占位）。"
                      "与地块层在同一个 contains_xy 循环里写出，故块区必然落在其声明地块内；"
                      "管线只出底稿，定稿在编辑器里改",
        "counts": {"units": len(ctx.单元们), "plots": len(ctx.种子), "covered_cells": ctx.覆盖格数,
                   "covered_before_mask": ctx.原始覆盖格数, "land_cells": int(ctx.陆地.sum())},
        "ref": ctx.参考信息,
        # domain 由编辑器日后指派（工单 §4.1）：这里先留空串，字段必须在，
        # 否则 import_editor 合入时"有/无该键"两种形状混进同一份台账。
        "plots": [{"id": i + 1, "name": s["n"], "domain": ""} for i, s in enumerate(ctx.种子)],
    }
    with open(os.path.join(OUT, F_META), "w", encoding="utf-8") as f:
        json.dump(ctx.台账, f, ensure_ascii=False, separators=(",", ":"))
    for fn in (F_PLOT, F_TERRAIN, F_CLIM, F_DIST, F_REFV, F_META):
        p = os.path.join(OUT, fn)
        print(f"  {fn:<16}{os.path.getsize(p) / 1048576:6.2f} MB")
    print("地形占比:", ctx.占比)

    # ---------------- 输出：编辑器读的那份 data.js ----------------
    # **图不再拷给编辑器**：真源只有 地图数据/栅格/ 一处（见 docs/adr/0002），
    # 编辑器由 serve.py 的 /数据/ 虚拟挂载去读它。这里只写它要的 js/data.js。
    from 附录C import load_palette
    from editor_data import write_data_js, payload_from_meta
    pal = load_palette()
    APP = os.path.join(ROOT, "地图", "地图编辑器")
    # 上一代把参考层烧成 县界参考.png 的产物已废弃：留着只会让人以为它还在用
    stale = os.path.join(OUT, "县界参考.png")
    if os.path.exists(stale):
        os.remove(stale)
        print(f"  已删除废弃产物 {os.path.relpath(stale, ROOT)}")
    # 旧版编辑器副本目录：ADR 0002 之后不该再存在，顺手清掉（否则它又变成第二份真源）
    old_copy = os.path.join(APP, "data")
    if os.path.isdir(old_copy):
        shutil.rmtree(old_copy)
        print(f"  已删除编辑器副本 {os.path.relpath(old_copy, ROOT)}（真源唯一，见 docs/adr/0002）")

    payload = payload_from_meta(ctx.台账, pal)
    p = write_data_js(payload, APP)
    print(f"  {os.path.relpath(p, ROOT)}"
          f"（图走 {URL_PREFIX} 虚拟挂载 → 地图数据/栅格/）")
