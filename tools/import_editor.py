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
     （合入是「覆盖真源」的动作；两个仓虽是 git 仓库，也不拿它当兜底，所以备份是硬要求）
  5. 写真源：两张 PNG 覆盖；`台账.json` 以真源那份为底，只换 `plots`／`districts` 与
     `counts.covered_cells`，重算 `base_tag`
  6. 重生成 `地图编辑器/js/data.js`（走 `地图/栅格地形数据生成器/editor_data.py`，与 build_raster 同一写入口）
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

# ⚠️ 路径表（mapdata）与底图指纹（basetag）在 **地图/栅格地形数据生成器/** 里 ——
#    2026-10-10 地形流程那一整包搬去了那里，本文件留在 tools/（它做的是行政图那半）。
#    所以先把那一包挂上 sys.path，再 import 它里面的共用模块。
_GEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "地图", "栅格地形数据生成器")
sys.path.insert(0, _GEN)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import ROOT, RASTER, STAGING                       # noqa: E402
from basetag import base_tag as make_base_tag                   # noqa: E402
import editor_data as ED                                        # noqa: E402

F_PLOT, F_DIST, F_META = "地块编码.png", "分区编码.png", "台账.json"
APP = os.path.join(ROOT, "地图", "地图编辑器")
CODE_MAX = 65536          # R + G×256


def read_codes(path: str, gray: bool = False) -> np.ndarray:
    """PNG → 编码数组。

    · `gray=False`（默认）：**24 位**编码，`R + G×256`。用于 `地块编码.png`，以及
      v2 及以前那份"全局块区 id"的 `分区编码.png`。
    · `gray=True`：**8 位单通道**，值就是值。用于 v3 起的 `分区编码.png`——它存的是
      **地块内的局部序号**（1..32），见 `docs/adr/0007`。

    ⚠️ 为什么要分两个解码器（2026-10-09 修的真 bug）：那份分区图**是 8 位灰度**
    （`Image.fromarray(dist_local, "L")`），而它以前一直按 24 位读 —— 灰度图三通道同值，
    于是每个局部序号被算成 `v + v×256 = 257v`：局部 1 变成 257、局部 2 变成 514，
    `(plot<<8)|257v` 会**进位到下一个地块**，恰好撞上别的块区，于是
    "块区越出了所属地块 1,262,380 格"、2151 个块区被当成"零像元"丢掉。
    恒等草稿（真源原样回灌）本该校验通过，这条就是被它抓出来的。

    编辑器导出的那张分区图是 canvas 出的 **RGBA**（R=G=B=值），灰度管线出的是 **L**；
    两种都取 R 通道，并**要求三通道一致**——不一致说明这张真的是 24 位编码。
    """
    im = Image.open(path)
    if not gray:
        a = np.asarray(im.convert("RGB"), dtype=np.uint8)
        return a[:, :, 0].astype(np.int32) + a[:, :, 1].astype(np.int32) * 256
    a = np.asarray(im.convert("RGB"), dtype=np.int32)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    if not (np.array_equal(r, g) and np.array_equal(g, b)):
        raise ValueError(
            f"{os.path.basename(path)} 的 R/G/B 三通道不一致：它应当是一张 8 位单通道图"
            f"（管线写 L 模式，编辑器导出的 RGBA 三通道同值）。这张看起来是 24 位编码 ——"
            f"说明草稿的 districts 带了 local、而图其实还是老口径，两边对不上。")
    return r


def _single_channel(im) -> bool:
    """这张图是不是"**一个值**"的编码（8 位灰度，或 canvas 导出时三通道同值的 RGBA）？

    管线写的是 `Image.fromarray(x, "L")`（模式 `L`）；编辑器由 canvas 导出，是 RGBA 但
    R=G=B=值。两种都要认，且要与 24 位（R=低位、G=高位）区分开——判据是"三通道是否恒等"，
    不用看图模式（RGBA 那种模式看不出来）。
    """
    if im.mode in ("L", "I", "I;16", "P", "1"):
        return True
    a = np.asarray(im.convert("RGB"))
    return bool(np.array_equal(a[..., 0], a[..., 1]) and np.array_equal(a[..., 1], a[..., 2]))


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
                    f"真源当前 base_tag={cur_tag!r}。请重做（或先重跑 生成.py 再改）。")

    districts = ledger.get("districts") or []
    has_local = any("local" in b for b in districts)
    pid = read_codes(png_p)
    # ---- 分区层的编码口径：**让图自己说话，再拿台账对证**，两边不一致就拒绝（不许猜）----
    # v3 起分区图是 8 位单通道（存地块内的局部序号）；v2 及以前是 24 位（存全局 id）。
    # ⚠️ 判据**不能只看台账**：一张 8 位图配一份没有 local 的台账，按 24 位读会得到 257v
    # （最大 65535 < 65536，编码范围那条检查抓不到），最后报成"块区越界"，很难查。
    # 反过来（图是 24 位而台账有 local）以前靠 read_codes 抛 ValueError，现在也走这条友好拒绝。
    single = _single_channel(Image.open(png_d))
    if single != has_local:
        errs.append(
            f"{F_DIST} 的口径与草稿台账不符：图是"
            f"{'8 位单通道（地块内局部序号）' if single else '24 位（全局块区 id）'}，"
            f"而草稿的 districts {'带' if has_local else '不带'} local 字段。"
            f"两边必须是同一代：v3 起分区图存局部序号（8 位灰度）、台账带 local；"
            f"v2 及以前图存全局 id（24 位）、台账没有 local。")
    bid = read_codes(png_d, gray=has_local)
    if pid.shape != bid.shape:
        errs.append(f"两张草稿 PNG 尺寸不一致：{F_PLOT} {pid.shape[1]}×{pid.shape[0]}，"
                    f"{F_DIST} {bid.shape[1]}×{bid.shape[0]}")
        return errs, warns, {}
    if has_local:
        l2g = {}
        for b in districts:
            plot, loc = int(b.get("plot") or 0), int(b.get("local") or 0)
            # ⚠️ **未挂地块的块区（plot=0）不建键**：栅格里它本来就写作 0（渲染成灰、不落笔），
            # 而 `(0<<8)|0 = 0` 会把**全图所有无块区的像元（含海洋与未收录陆地）**都折成它，
            # 于是统计里混进 700 万格"块区像元"、其余 plot=0 的块区互相覆盖后当成零像元丢掉。
            if plot <= 0 or loc <= 0:
                continue
            l2g[(plot << 8) | loc] = int(b["id"])
        bid = np.array([l2g.get((int(pp) << 8) | int(ll), 0)
                        for pp, ll in zip(pid.ravel(), bid.ravel())],
                       dtype=np.int32).reshape(pid.shape)
        warns.append("分区层按 draft 台账的 (plot, local) 折回全局 id 后再校验")
    else:
        warns.append("草稿的 districts 没有 local 字段（v2 及以前的草稿）：把分区层当作全局 id 处理")
    if pid.shape != (H, W):
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
    """算 base_tag 用的图例摘要：**覆盖 + 形态**（与 生成.py 的 legend_tag 同一口径）；
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
    from 附录C import load_palette
    pal = load_palette()
    # 与 生成.py 收尾那一步**调同一个构造函数**：两边各拼一份 payload 必然分叉
    # （实测 import_editor 那份漏了 block_rule、键序也不同）。见 editor_data.payload_from_meta。
    p = ED.write_data_js(ED.payload_from_meta(meta, pal), APP)
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
