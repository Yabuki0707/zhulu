#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽查生成出来的底图：三条硬检查 + 一组地理常识断言。

    python tools/check_terrain.py            # 读 地图/地图数据/栅格/ 下的产物
    python tools/check_terrain.py --all      # 另外打印占比与零像元地块清单

硬检查（任一不过 → 退出码 1）：

  1. **地块不压海洋**：`覆盖 == 海洋` 的像元上，`地块编码` 必须全部为 0。
     这是需求方定的规矩，也是"海陆口径只有一处"的直接推论。
  2. **地形字节在契约内**：高 4 位覆盖 < 12、低 4 位形态 < 5，且**海洋格的形态位必须是 0**。
  3. **气候层在位**：`气候编码.png` 存在、形状一致、码 ≤ 31。

地理常识断言：一组已知地点，看**覆盖**落在不在"可接受集"里，并顺手打印该格的
**显示类**（覆盖 × 形态 × 气候，是玩家真正看到的名字）。这些点是拿地图对着写的，不追求
全对，只用来抓住"整片错"这种事 —— 比如西宁不是农田、西伯利亚不是森林、青藏不是高原。

⚠️ v3 起底图里**没有**沙漠/裸地/针叶林/阔叶林/雨林/苔原这些名字（`docs/adr/0006`、`0007`）：
它们是显示类，由「覆盖 × 形态 × 气候」当场派生。所以这里断言的是**覆盖**（撒哈拉/塔克拉玛干
断的是「荒漠」，西伯利亚断的是「森林」），而"沙漠/针叶林"这些名字只出现在打印出来的
显示类那一列里。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import GRID_META, GRID_PLOT, GRID_TERRAIN, under      # noqa: E402
import terrain as TR                                              # noqa: E402
import climate as CL                                              # noqa: E402
import display_class as DC                                        # noqa: E402

C = TR.COVER_LEGEND

# (名称, 经度, 纬度, 可接受的**覆盖**集, 可接受的**形态**集或 None)
# 经度是**连续窗口** 25–226（>180 是日界线以东），落在窗口外的点直接跳过 ——
# 早期脚本用 `% W` 回绕，把 15°E 的撒哈拉点算到了太平洋上。
EXPECT = [
    # —— 覆盖：荒漠（= 干旱区的裸露与稀疏植被）——
    ("埃及南部", 30.0, 25.0, {"荒漠"}, None),
    ("鲁卜哈利", 48.0, 21.0, {"荒漠"}, None),
    ("塔克拉玛干", 82.0, 39.0, {"荒漠"}, None),
    ("戈壁", 105.0, 43.0, {"荒漠", "草原"}, None),
    ("澳洲中部", 133.0, -25.0, {"荒漠", "草原"}, None),
    # —— 覆盖：农田（真沙漠气候里就是「绿洲」，高原上就是「河谷农田」）——
    ("和田绿洲", 79.9, 37.1, {"绿洲", "农田", "荒漠"}, None),
    ("尼罗河三角洲", 31.0, 30.8, {"绿洲", "农田", "湖泊", "荒漠"}, None),
    # —— **西北专项**（需求方报"河湟谷地没有、陇右整片高原"）——
    ("西宁·河湟谷地", 101.78, 36.62, {"农田", "草原", "森林"}, {"高原", "丘陵", "山地"}),
    ("天水·陇右", 105.72, 34.58, {"农田", "草原"}, {"高原", "丘陵", "山地"}),
    ("定西·陇中", 104.63, 35.58, {"农田", "草原"}, None),
    ("武威·河西", 102.64, 37.93, {"草原", "荒漠", "绿洲"}, None),
    ("银川·宁夏", 106.23, 38.49, {"绿洲", "农田", "荒漠"}, None),
    ("兰州", 103.83, 36.06, {"河流", "农田", "草原"}, None),
    # —— 形态：山地 / 高原（只看起伏与高程）——
    ("青藏高原", 88.0, 33.0, {"草原", "荒漠", "冰川"}, {"高原", "山地"}),
    # 喜马拉雅南坡 3547 m 那一格 LC100 说森林——**数据是对的**（远低于树线）。
    # 拆开之后"森林"第一次能长在山上，见下面那个"树线以上只有 60 格"的旁注。
    ("喜马拉雅", 86.0, 28.0, {"森林", "冰川", "草原", "荒漠"}, {"山地", "高原"}),
    ("蒙古高原", 105.0, 47.0, {"草原", "荒漠"}, {"高原", "丘陵"}),
    # 黄土高原上的「高原森林」是子午岭，真的（1558 m）。
    ("黄土高原", 108.5, 36.5, {"森林", "草原", "农田", "荒漠"}, None),
    # —— 盆地 / 平原 ——
    ("四川盆地", 105.0, 30.5, {"农田", "森林"}, {"平原", "丘陵"}),
    ("华北平原", 116.0, 38.0, {"农田"}, {"平原"}),
    ("东北平原", 125.0, 45.0, {"农田", "草原"}, {"平原", "丘陵"}),
    ("恒河平原", 85.0, 25.0, {"农田", "河流"}, None),
    # —— 覆盖：森林（针叶/阔叶/雨林在存储层已合一，只有显示层才按热量带分开）——
    ("西伯利亚中部", 100.0, 60.0, {"森林"}, None),
    ("大兴安岭", 122.0, 52.0, {"森林", "草原"}, None),
    ("江南丘陵", 118.0, 29.0, {"森林", "农田"}, None),
    ("日本本州", 138.0, 36.0, {"森林", "农田"}, None),
    ("加里曼丹", 114.0, 0.0, {"森林", "河流"}, None),
    ("苏门答腊", 101.0, 0.0, {"森林"}, None),
    # —— 水 ——
    ("里海", 51.0, 42.0, {"湖泊"}, None),
    ("贝加尔湖", 108.0, 53.0, {"湖泊", "冰川"}, None),
    ("渤海", 120.0, 38.0, {"海洋"}, None),
    ("黄海", 124.0, 34.0, {"海洋"}, None),
    ("印度洋", 80.0, -10.0, {"海洋"}, None),
    ("南海", 115.0, 15.0, {"海洋"}, None),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="另打印占比与零像元地块")
    args = ap.parse_args()

    for p in (GRID_META, GRID_TERRAIN, GRID_PLOT):
        if not os.path.exists(p):
            print(f"缺 {p}：先跑 python tools/build_raster.py", file=sys.stderr)
            return 1
    meta = json.load(open(GRID_META, encoding="utf-8"))
    g = meta["grid"]
    cover_leg = [meta["cover_legend"][str(i)] for i in range(len(meta["cover_legend"]))]
    form_leg = [meta["form_legend"][str(i)] for i in range(len(meta["form_legend"]))]
    terr_byte = np.asarray(Image.open(GRID_TERRAIN))
    cover, form = TR.unpack(terr_byte)
    rgb = np.asarray(Image.open(GRID_PLOT).convert("RGB")).astype(np.uint16)
    plot = rgb[..., 0] + (rgb[..., 1] << 8)
    W, H, cell, lon0, lat1 = g["w"], g["h"], g["cell"], g["lon0"], g["lat1"]
    print(f"栅格 {W} × {H}  格 {cell}° ≈ {cell * 111:.2f} km  "
          f"经度 {g['lon0']}–{g['lon1']}E  纬度 {g['lat0']}–{g['lat1']}N")
    print(f"覆盖 {len(cover_leg)} 类：" + " ".join(f"{i}{n}" for i, n in enumerate(cover_leg)))
    print(f"形态 {len(form_leg)} 类：" + " ".join(f"{i}{n}" for i, n in enumerate(form_leg)))
    print(f"地形字节 = 覆盖×16 + 形态；实测最大 {int(terr_byte.max())}")

    bad = 0
    # ---- 硬检查 1：地块不压海洋 ----
    sea = cover == TR.C_OCEAN
    n_sea_plot = int((sea & (plot > 0)).sum())
    n_land = int((~sea).sum())
    ok1 = n_sea_plot == 0
    print(f"\n[1] 地块不压海洋：海里带地块的像元 {n_sea_plot:,}  " + ("✓" if ok1 else "✗ 失败"))
    print(f"    陆地 {n_land:,} 格（{n_land / cover.size * 100:.1f}%），"
          f"其中无地块 {int((~sea & (plot == 0)).sum()):,} 格 —— 那就是欧/非/美洲＋未收录区，正常")
    bad += 0 if ok1 else 1

    # ---- 硬检查 2：字节契约（覆盖 <12、形态 <5、海洋形态 = 0） ----
    ok2 = (int(cover.max()) < TR.N_COVER and int(form.max()) < TR.N_FORM
           and int(form[sea].max(initial=0)) == 0)
    print(f"\n[2] 地形字节：覆盖 0–{int(cover.max())}（<{TR.N_COVER}）、形态 0–{int(form.max())}"
          f"（<{TR.N_FORM}）、海洋形态=0："
          + ("✓" if ok2 else "✗ 越界"))
    if not ok2:
        bad += 1
    dead = [cover_leg[i] for i in range(TR.N_COVER)
            if int((cover == i).sum()) == 0 and i != 0]
    if dead:
        print(f"    ! 从未出现的覆盖类：{dead}（分类规则里是死类，检查是不是漏了映射）")

    # ---- 硬检查 3：气候层（v2 起是产品层，不是中间层） ----
    klim_png = under("栅格", "气候编码.png")
    if not os.path.exists(klim_png):
        print("\n[3] 气候编码.png 缺失 —— 地形表把气候那一半交还给了它（ADR 0006）✗")
        bad += 1
        kod = None
    else:
        kod = np.asarray(Image.open(klim_png))
        ok3 = kod.shape == cover.shape and int(kod.max()) <= 31
        heat, moist = CL.unpack(kod)
        landm = ~sea
        n_polar = int((landm & (moist == 0)).sum())
        print(f"\n[3] 气候层：形状 {kod.shape}，码 0–{int(kod.max())}（上限 31）："
              + ("✓" if ok3 else "✗ 越界或形状不符"))
        print(f"    热量带：" + "，".join(
            f"{n} {int((landm & (heat == i)).sum()):,}" for i, n in enumerate(CL.HEAT_NAMES)))
        print(f"    干湿：" + "，".join(
            f"{n} {int((landm & (moist == i)).sum()):,}"
            for i, n in enumerate(CL.MOIST_NAMES) if (landm & (moist == i)).any()))
        print(f"    干湿=0（读作寒带）的陆地 {n_polar:,} 格 = 陆地的 "
              f"{n_polar / max(1, int(landm.sum())) * 100:.1f}%")
        bad += 0 if ok3 else 1

    # ---- 地理常识断言（打印**显示类**，那才是玩家看到的名字） ----
    print("\n[4] 已知地点抽查（现 = 覆盖 ∧ 形态 → 显示类）：")
    fails = []
    for name, lon, lat, want_c, want_f in EXPECT:
        x = int((lon - lon0) / cell)
        y = int((lat1 - lat) / cell)
        if not (0 <= x < W and 0 <= y < H):
            print(f"    · {name:<14} 不在窗口内，跳过")
            continue
        cv, fm = int(cover[y, x]), int(form[y, x])
        got_c, got_f = cover_leg[cv], form_leg[fm]
        disp = (DC.label(cv, fm, int(heat[y, x]), int(moist[y, x]))
                if kod is not None else "（无气候层）")
        hit = got_c in want_c and (want_f is None or got_f in want_f)
        if not hit:
            fails.append((name, lon, lat, got_c, got_f, disp, want_c, want_f))
        print(f"    {'OK ' if hit else 'BAD'} {name:<14} ({lon:>7.1f},{lat:>6.1f}) → "
              f"{got_c}∧{got_f} → {disp}")
    if fails:
        print(f"    ✗ {len(fails)} 处不符："
              + "；".join(f"{n} 得到{c}∧{f}→{d}" for n, _, _, c, f, d, _, _ in fails))
        bad += 1

    if args.all:
        print("\n覆盖占比：")
        cc = np.bincount(cover.ravel(), minlength=TR.N_COVER)
        for i in np.argsort(-cc):
            if not cc[i]:
                continue
            print(f"    {cover_leg[i]:<6}{cc[i] / cover.size * 100:7.3f}%  {int(cc[i]):,}")
        print("形态占比：")
        fc = np.bincount(form.ravel(), minlength=TR.N_FORM)
        for i in np.argsort(-fc):
            if not fc[i]:
                continue
            print(f"    {form_leg[i]:<6}{fc[i] / form.size * 100:7.3f}%  {int(fc[i]):,}")
        pids, pcnt = np.unique(plot[plot > 0], return_counts=True)
        ledger = {p["id"] for p in meta["plots"]}
        blank = sorted(ledger - set(pids.tolist()))
        print(f"\n地块：台账 {len(ledger)}，栅格里出现 {len(pids)}，零像元 {len(blank)}")
        print(f"    最大地块编码 {int(pids.max())}（编码上限 8,191，13 位同口径）")
        print(f"    块区：台账 {len(meta['districts'])} 个，栅格里最大的**局部序号** "
              f"{int(np.asarray(Image.open(under('栅格', '分区编码.png'))).max())}（上限 255）")

    print("\n" + ("全部通过 ✓" if bad == 0 else f"{bad} 项未通过 ✗"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
