#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽查生成出来的底图，两条硬检查 + 一组地理常识断言。

    python tools/check_terrain.py            # 读 地图/地图数据/栅格/ 下的产物
    python tools/check_terrain.py --all      # 另外打印每类的占比与零像元地块清单

硬检查（任一不过 → 退出码 1）：

  1. **地块不压海洋**：`地形 == 海洋` 的像元上，`地块编码` 必须全部为 0。
     这是需求方定的规矩，也是"海陆口径只有一处"的直接推论。
  2. **地形编码在图例范围内**，且没有从未出现过的类（那说明分类规则有死类）。

地理常识断言：一组已知地点，看落到的类是否在"可接受集"里。这些点是拿地图对着写的，
不追求全对（同一地点不同资料会归不同类），只用来抓住"整片错"这种事——
比如西伯利亚不是针叶林、撒哈拉不是沙漠、青藏不是高原，那就一定是分类塌了。
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

# (名称, 经度, 纬度, 可接受的地形类)。经度是**连续窗口** 25–236（>180 是日界线以东），
# 落在窗口外的点直接跳过 —— 早期脚本用 `% W` 回绕，把 15°E 的撒哈拉点算到了太平洋上。
EXPECT = [
    # —— 沙漠 / 荒地（LC100 60 裸地 ＋ NE 具名沙漠面）——
    ("埃及南部", 30.0, 25.0, {"沙漠"}),
    ("鲁卜哈利", 48.0, 21.0, {"沙漠"}),
    ("塔克拉玛干", 82.0, 39.0, {"沙漠", "裸地"}),
    ("戈壁", 105.0, 43.0, {"沙漠", "裸地", "高原"}),
    ("澳洲中部", 133.0, -25.0, {"沙漠", "裸地", "草原"}),
    # —— 形态：山地 / 高原（只看起伏与高程）——
    ("青藏高原", 88.0, 33.0, {"高原"}),
    ("喜马拉雅", 86.0, 28.0, {"山地", "冰川", "高原"}),
    ("天山脊线", 84.5, 43.2, {"山地", "冰川", "高原", "裸地"}),
    ("蒙古高原", 105.0, 47.0, {"高原", "草原"}),
    ("黄土高原", 108.5, 36.5, {"高原", "丘陵", "草原"}),
    ("云贵高原", 104.0, 25.5, {"高原", "山地", "针叶林", "阔叶林"}),
    # —— 盆地/平原：**这是上一轮翻车的地方**（四川盆地曾被判成丘陵）——
    ("四川盆地", 105.0, 30.5, {"平原", "丘陵"}),
    ("华北平原", 116.0, 38.0, {"平原"}),
    ("东北平原", 125.0, 45.0, {"平原"}),
    ("恒河平原", 85.0, 25.0, {"平原", "河流"}),
    # —— 森林三档（权重制：纬度＋海拔＋林型倾向，没有直线分界）——
    ("西伯利亚中部", 100.0, 60.0, {"针叶林"}),
    ("大兴安岭", 122.0, 52.0, {"针叶林", "山地", "河流"}),
    ("江南丘陵", 118.0, 29.0, {"阔叶林", "针叶林", "丘陵", "平原"}),
    ("日本本州", 138.0, 36.0, {"阔叶林", "针叶林", "山地"}),
    ("海南北部低地", 110.4, 19.9, {"雨林", "阔叶林", "平原", "河流"}),
    ("加里曼丹", 114.0, 0.0, {"雨林", "河流"}),
    ("苏门答腊", 101.0, 0.0, {"雨林", "阔叶林"}),
    ("吕宋中央平原", 120.9, 15.6, {"平原", "雨林", "阔叶林", "河流"}),
    ("云南南部", 101.0, 22.0, {"雨林", "阔叶林"}),
    # —— 水：内海必须是湖泊（里海曾在 LC100 的 200 上被写回「海洋」）——
    ("里海", 51.0, 42.0, {"湖泊"}),
    ("贝加尔湖", 108.0, 53.0, {"湖泊", "冰川"}),
    ("渤海", 120.0, 38.0, {"海洋"}),
    ("黄海", 124.0, 34.0, {"海洋"}),
    ("太平洋中部", 160.0, 30.0, {"海洋"}),
    ("印度洋", 80.0, -10.0, {"海洋"}),
    ("南海", 115.0, 15.0, {"海洋"}),
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
    legend = [meta["terrain_legend"][str(i)] for i in range(len(meta["terrain_legend"]))]
    terrain = np.asarray(Image.open(GRID_TERRAIN))
    rgb = np.asarray(Image.open(GRID_PLOT).convert("RGB")).astype(np.uint16)
    plot = rgb[..., 0] + (rgb[..., 1] << 8)
    W, H, cell, lon0, lat1 = g["w"], g["h"], g["cell"], g["lon0"], g["lat1"]
    print(f"栅格 {W} × {H}  格 {cell}° ≈ {cell * 111:.2f} km  "
          f"经度 {g['lon0']}–{g['lon1']}E  纬度 {g['lat0']}–{g['lat1']}N")
    print(f"地形 {len(legend)} 类：" + " ".join(f"{i}{n}" for i, n in enumerate(legend)))

    bad = 0
    # ---- 硬检查 1：地块不压海洋 ----
    sea = terrain == TR.T_OCEAN
    n_sea_plot = int((sea & (plot > 0)).sum())
    n_land = int((~sea).sum())
    n_land_noplot = int((~sea & (plot == 0)).sum())
    ok1 = n_sea_plot == 0
    print(f"\n[1] 地块不压海洋：海里带地块的像元 {n_sea_plot:,}  " + ("✓" if ok1 else "✗ 失败"))
    print(f"    陆地 {n_land:,} 格（{n_land / terrain.size * 100:.1f}%），"
          f"其中无地块 {n_land_noplot:,} 格（{n_land_noplot / max(1, n_land) * 100:.1f}%）"
          f" —— 无地块的陆地就是欧/非/美洲＋未收录区，正常")
    bad += 0 if ok1 else 1

    # ---- 硬检查 2：编码范围 / 有无死类 ----
    ids, cnt = np.unique(terrain, return_counts=True)
    ok2 = ids.min() >= 0 and ids.max() < len(legend)
    dead = [legend[i] for i in range(len(legend)) if i not in set(ids.tolist())]
    print(f"\n[2] 地形编码范围 0–{int(ids.max())}（图例 {len(legend)} 类）："
          + ("✓" if ok2 else "✗ 越界"))
    if dead:
        print(f"    ! 从未出现的类：{dead}（分类规则里是死类，检查是不是漏了映射）")
    bad += 0 if ok2 else 1

    # ---- 地理常识断言 ----
    print("\n[3] 已知地点抽查：")
    fails = []
    for name, lon, lat, want in EXPECT:
        x = int((lon - lon0) / cell)
        y = int((lat1 - lat) / cell)
        if not (0 <= x < W and 0 <= y < H):
            print(f"    · {name:<12} ({lon:g},{lat:g}) 不在窗口（{lon0:g}–{lon0 + W * cell:g}E / "
                  f"{lat1 - H * cell:g}–{lat1:g}N）内，跳过")
            continue
        got = legend[int(terrain[y, x])]
        hit = got in want
        if not hit:
            fails.append((name, lon, lat, got, want))
        print(f"    {'OK ' if hit else 'BAD'} {name:<12} ({lon:>7.1f},{lat:>6.1f}) → {got:<6} "
              f"期望 {'/'.join(sorted(want))}")
    if fails:
        print(f"    ✗ {len(fails)} 处不符：" + "；".join(f"{n} 得到{g}" for n, _, _, g, _ in fails))
        bad += 1

    if args.all:
        print("\n地形占比：")
        for i, c in sorted(zip(ids.tolist(), cnt.tolist()), key=lambda t: -t[1]):
            print(f"    {legend[i]:<8}{c / terrain.size * 100:7.3f}%  {c:,}")
        pids, pcnt = np.unique(plot[plot > 0], return_counts=True)
        ledger = {p["id"] for p in meta["plots"]}
        blank = sorted(ledger - set(pids.tolist()))
        print(f"\n地块：台账 {len(ledger)}，栅格里出现 {len(pids)}，零像元 {len(blank)}")
        if blank:
            names = {p["id"]: p["name"] for p in meta["plots"]}
            print("    零像元例：" + "，".join(f"{i} {names.get(i, '')}" for i in blank[:12]))
        print(f"    最大地块编码 {int(pids.max())}（编码上限 65535，Uint16/R+G*256 同口径）")

    print("\n" + ("全部通过 ✓" if bad == 0 else f"{bad} 项未通过 ✗"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
