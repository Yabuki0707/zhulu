#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把编辑器的草稿（`地图/待合入/`）校验后合入唯一真源（`地图/地图数据/栅格/`）。

依据：`docs/adr/0001`（编辑器只产出行政图，地形管线定稿）、`docs/adr/0002`（真源唯一），
执行细则见 `工单-地图编辑器职责分离与存回.md` §4.2。

用法：
    python tools/import_editor.py            # 校验 → 备份 → 合入
    python tools/import_editor.py --dry-run  # 只校验，什么都不写

步骤顺序不能变（工单 §4.2）：

  1. 读草稿三件（缺一即失败）
  2. **对指纹**：草稿的 `based_on` 必须等于真源当前 `base_tag`——不等就是"基于旧底图改的"，
     直接拒绝。少了这一步，一次重跑管线之后的旧草稿会把整张图悄悄改回去。
  3. 校验：编码范围 < 65536 ｜ **地块不压海洋** ｜ **块区不越界** ｜ 编号不重复
  4. **备份**：将被覆盖的文件复制到 `地图/待合入/备份-<时间戳>/`
     （仓库不是 git 仓库，误合入没有版本控制可回滚，所以备份是硬要求）
  5. 写真源：两张 PNG 覆盖；`台账.json` 以真源那份为底，只换 `plots`／`districts` 与
     `counts.covered_cells`，重算 `base_tag`
  6. 重生成 `地图编辑器/js/data.js`（走 `tools/editor_data.py`，与 build_raster 同一写入口）
  7. 打印摘要
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import ROOT, RASTER, STAGING                       # noqa: E402
from basetag import base_tag as make_base_tag                   # noqa: E402
from editor_data import write_data_js                           # noqa: E402

F_PLOT, F_DIST, F_META = "地块编码.png", "分区编码.png", "台账.json"
APP = os.path.join(ROOT, "地图", "地图编辑器")
CODE_MAX = 65536          # R + G×256


def read_codes(path: str) -> np.ndarray:
    """24 位编码 PNG → int32 编码数组（R + G×256）。"""
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    return a[:, :, 0].astype(np.int32) + a[:, :, 1].astype(np.int32) * 256


def _sample(cells, codes, n=3):
    """把越界/压海那些格挑几个出来给坐标，光报个总数没法查。"""
    idx = np.flatnonzero(cells)[:n]
    W = codes.shape[1]
    return "、".join(f"({int(i % W)},{int(i // W)})码{int(codes.flat[i])}" for i in idx)


def validate(meta, ledger):
    """→ (致命错误, 警告, 统计)。任何致命错误都不写一个字节。"""
    errs, warns = [], []
    W, H = meta["grid"]["w"], meta["grid"]["h"]
    png_p, png_d = os.path.join(STAGING, F_PLOT), os.path.join(STAGING, F_DIST)

    # 2. 对指纹
    cur_tag = meta.get("base_tag") or _tag_of(meta)
    if ledger.get("based_on") != cur_tag:
        errs.append(f"草稿是基于旧底图改的：草稿 based_on={ledger.get('based_on')!r}，"
                    f"真源当前 base_tag={cur_tag!r}。请重做（或先重跑 build_raster 再改）。")

    pid, bid = read_codes(png_p), read_codes(png_d)
    # 分区编码.png 存的是**地块内的局部序号**（v3，见 docs/adr/0007）。校验一律在**全局 id**
    # 上做，所以先把局部折回全局：键 = 地块×256 + 局部；地块号取自地块层**同一格**。
    # 老草稿（v2 及以前）的 districts 没有 local，那时栅格里本来就是全局 id，按原样用。
    districts = ledger.get("districts") or []
    if any("local" in b for b in districts):
        l2g = {}
        for b in districts:
            l2g[(int(b.get("plot") or 0) << 8) | int(b.get("local") or 0)] = int(b["id"])
        bid = np.array([l2g.get((int(pp) << 8) | int(ll), 0)
                        for pp, ll in zip(pid.ravel(), bid.ravel())],
                       dtype=np.int32).reshape(pid.shape)
        warns.append("分区层按 draft 台账的 (plot, local) 折回全局 id 后再校验")
    else:
        warns.append("草稿的 districts 没有 local 字段（v2 及以前的草稿）：把分区层当作全局 id 处理")
    if pid.shape != (H, W) or bid.shape != (H, W):
        errs.append(f"尺寸不符：草稿 {pid.shape[1]}×{pid.shape[0]}，真源 {W}×{H}")
        return errs, warns, {}

    # 3a. 编码范围
    for nm, a in ((F_PLOT, pid), (F_DIST, bid)):
        bad = int((a >= CODE_MAX).sum())
        if bad:
            errs.append(f"{nm} 有 {bad} 格编码 ≥ {CODE_MAX}：{_sample(a >= CODE_MAX, a)}")

    # 3b. 地块不压海洋（地形层不在草稿里，用真源那份——地形定稿，两次合入之间不会变）
    terr = np.asarray(Image.open(os.path.join(RASTER, "地形编码.png")).convert("L"), dtype=np.uint8)
    if terr.shape != (H, W):
        errs.append(f"真源地形层尺寸 {terr.shape[1]}×{terr.shape[0]} 与网格 {W}×{H} 不符")
        return errs, warns, {}
    on_ocean = (pid > 0) & (terr == 0)
    if on_ocean.any():
        errs.append(f"{int(on_ocean.sum())} 格把地块画在了海洋上：{_sample(on_ocean, pid)}")

    # 4/编号重复
    plots = ledger.get("plots") or []
    blocks = ledger.get("districts") or []
    for nm, arr in (("plots", plots), ("districts", blocks)):
        ids = [int(x["id"]) for x in arr]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            errs.append(f"草稿台账 {nm} 编号重复：{dup[:8]}")

    # 3c. 块区不越界
    owner = {int(b["id"]): int(b.get("plot") or 0) for b in blocks}
    known = {int(p["id"]) for p in plots}
    unknown = sorted({int(v) for v in np.unique(bid) if v} - set(owner))
    if unknown:
        errs.append(f"分区层里有 {len(unknown)} 个编号在草稿台账里查不到：{unknown[:8]}")
    bad_pid = sorted({int(v) for v in np.unique(pid) if v} - known)
    if bad_pid:
        errs.append(f"地块层里有 {len(bad_pid)} 个编号在草稿台账里查不到：{bad_pid[:8]}")
    stray = np.zeros(0, dtype=bool)
    if bid.size and not unknown:
        om = np.zeros(int(bid.max()) + 1, dtype=np.int32)
        for k, v in owner.items():
            if k < om.size:
                om[k] = v
        m = bid > 0
        stray = np.zeros(bid.shape, dtype=bool)
        stray[m] = om[np.clip(bid[m], 0, om.size - 1)] != pid[m]
        if stray.any():
            errs.append(f"{int(stray.sum())} 格块区越出了所属地块：{_sample(stray, bid)}")

    # 草稿台账的 districts 只有 {id, name, plot}（工单 §3.1），没有像元数——
    # 零像元块区只能从栅格看出来：台账里有、分区层里一格都没有。
    present_b = {int(v) for v in np.unique(bid) if v}
    empty_blocks = sorted(set(owner) - present_b)
    if empty_blocks:
        warns.append(f"丢弃 {len(empty_blocks)} 个零像元块区：{empty_blocks[:8]}")
    blank = sorted(known - {int(v) for v in np.unique(pid)})
    if blank:
        warns.append(f"{len(blank)} 个地块在栅格里一格都没有（保持原样，编辑器里会标「空」）")

    stats = {"covered": int((pid > 0).sum()), "block_cells": int((bid > 0).sum()),
             "plots": len(plots), "blocks": len(blocks) - len(empty_blocks),
             "empty_blocks": empty_blocks}
    return errs, warns, stats


def _legend(meta) -> list:
    """算 base_tag 用的图例摘要：**覆盖 + 形态**（与 build_raster.legend_tag 同一口径）；
    旧台账（v2 及以前）没有 cover_legend，回退读 terrain_legend。"""
    if "cover_legend" in meta:
        return ([meta["cover_legend"][str(i)] for i in range(len(meta["cover_legend"]))]
                + [meta["form_legend"][str(i)] for i in range(len(meta["form_legend"]))])
    return [meta["terrain_legend"][str(i)] for i in range(len(meta["terrain_legend"]))]


def _tag_of(meta) -> str:
    """真源台账里没有 base_tag 时按公式现算一个（老台账没存这个字段）。"""
    legend = _legend(meta)
    return make_base_tag(meta["grid"]["cell"], meta["grid"]["w"], meta["grid"]["h"],
                         len(meta["plots"]), meta["counts"]["covered_cells"],
                         [p["name"] for p in meta["plots"]], legend)


def backup(paths, stamp) -> str:
    dst = os.path.join(STAGING, "备份-" + stamp)
    os.makedirs(dst, exist_ok=True)
    for p in paths:
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dst, os.path.basename(p)))
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只校验，不写任何文件")
    args = ap.parse_args()

    print(f"待合入 {os.path.relpath(STAGING, ROOT)}")
    missing = [n for n in (F_PLOT, F_DIST, F_META) if not os.path.exists(os.path.join(STAGING, n))]
    if missing:
        print(f"  缺 {'、'.join(missing)}——三件必须齐全。先在编辑器里 ⋯ →「存到待合入目录」。")
        return 1

    meta_path = os.path.join(RASTER, F_META)
    meta = json.load(open(meta_path, encoding="utf-8"))
    ledger = json.load(open(os.path.join(STAGING, F_META), encoding="utf-8"))

    errs, warns, stats = validate(meta, ledger)
    for w in warns:
        print("  警告：" + w)
    if errs:
        print()
        for e in errs:
            print("  拒绝：" + e)
        print(f"\n校验不通过，什么都没写（{os.path.relpath(RASTER, ROOT)} 未改动）。")
        return 2
    print(f"  校验通过：地块像元 {stats['covered']:,} ｜ 块区像元 {stats['block_cells']:,}"
          f" ｜ 地块 {stats['plots']} ｜ 块区 {stats['blocks']}")
    if args.dry_run:
        print("  --dry-run：到此为止，没有写任何文件。")
        return 0

    # ---------------- 4. 备份（仓库无版本控制，这一步是硬要求） ----------------
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bdir = backup([os.path.join(RASTER, F_PLOT), os.path.join(RASTER, F_DIST),
                   meta_path, os.path.join(APP, "js", "data.js")], stamp)
    print(f"  已备份到 {os.path.relpath(bdir, ROOT)}")

    # ---------------- 5. 写真源 ----------------
    # 图例先算好再动文件：下面只要有一处抛错，真源就处在"PNG 换了、台账没换"的半写态
    legend = _legend(meta)
    shutil.copy2(os.path.join(STAGING, F_PLOT), os.path.join(RASTER, F_PLOT))
    shutil.copy2(os.path.join(STAGING, F_DIST), os.path.join(RASTER, F_DIST))
    plots = [{"id": int(p["id"]), "name": p["name"], "domain": p.get("domain") or ""}
             for p in sorted(ledger["plots"], key=lambda x: int(x["id"]))]
    # 编号规则：全局 id 照抄草稿；**局部序号**由 (plot, 草稿内顺序) 重发一遍——
    # 与 build_raster 同一条约定：局部序号是"地块内的第几个"，栅格读它、台账写全局 id。
    _loc = {}
    districts = []
    for b in sorted(ledger["districts"], key=lambda x: int(x["id"])):
        if int(b["id"]) in set(stats["empty_blocks"]):
            continue
        _pl = int(b.get("plot") or 0)
        _loc[_pl] = _loc.get(_pl, 0) + 1
        districts.append({"id": int(b["id"]), "name": b["name"], "plot": _pl,
                          "local": int(b.get("local") or _loc[_pl])})
    meta["plots"], meta["districts"] = plots, districts
    meta["counts"]["plots"] = len(plots)
    meta["counts"]["covered_cells"] = stats["covered"]
    new_tag = make_base_tag(meta["grid"]["cell"], meta["grid"]["w"], meta["grid"]["h"],
                            len(plots), stats["covered"], [p["name"] for p in plots], legend)
    meta["base_tag"] = new_tag
    meta["imported_from_editor_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  已换入 {F_PLOT}、{F_DIST} ｜ 已更新 {F_META}（地块 {len(plots)} ｜ 分区 {len(districts)}）")

    # ---------------- 6. 重生成 data.js（与 build_raster 同一写入口） ----------------
    from build_editor import load_palette
    pal = load_palette()
    # v2/v3 的新键必须**原样带过去**：data.js 是编辑器唯一的入口，漏一个键
    # 编辑器就会在启动时炸（cover_legend 缺失 → COVER_NAMES undefined）。
    import display_class as DC                                          # noqa: E402
    import climate as CL                                                # noqa: E402
    payload = {
        "grid": meta["grid"],
        "cover_legend": meta.get("cover_legend"), "form_legend": meta.get("form_legend"),
        "display_classes": DC.entries(),
        "climate_legend": {"heat": list(CL.HEAT_NAMES), "moist": list(CL.MOIST_NAMES),
                           "encoding": "热量带 × 8 + 干湿（0..31）；干湿 = 0 读作寒带",
                           "note": meta.get("climate_rule", "")},
        "plots": [dict({"id": p["id"], "name": p["name"]},
                       **({"domain": p["domain"]} if p["domain"] else {})) for p in plots],
        "palette": pal,
        "domains": [{"g": g["geo"], "d": d} for g in pal for d in g["domains"]],
        "districts": districts,
        "base_tag": new_tag,
        "land_rule": meta["land_rule"],
    }
    p = write_data_js(payload, APP)
    print(f"  已重写 {os.path.relpath(p, ROOT)}")

    # ---------------- 7. 摘要 ----------------
    print(f"\n合入完成。")
    print(f"  新 base_tag：{new_tag}")
    print(f"  备份：{os.path.relpath(bdir, ROOT)}（回滚 = 把里面四个文件拷回原位）")
    print(f"  草稿仍在 {os.path.relpath(STAGING, ROOT)}——确认无误后自行删除或移走；"
          f"留着不影响，但编辑器启动时会问「用草稿还是正式版」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
