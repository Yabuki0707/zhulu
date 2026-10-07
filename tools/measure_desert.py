# -*- coding: utf-8 -*-
"""复测「沙漠边界平滑」是否修掉 —— 口径与 设计笔记03 §14.11 的实测完全一致。

    python tools/measure_desert.py

三项指标（§14.11 的基线写在括号里）：
  ① 沙漠边界外侧仍是 LC100 裸地的比例（基线 25.5%，2,947 / 11,559 格）
  ② 最长一段笔直的边界（基线 30 格 = 207 km）
  ③ 同为 LC100 裸露地表，沙漠与裸地的周长/√面积（基线 沙漠 34.9 / 裸地 114.3）
  ④ 参考：干旱气候区里 LC100 裸地 → 沙漠 的覆盖率（沙漠 = 该集合，故恒为 100%）
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import GRID_TERRAIN, GRID_VEG, KOPPEN_ZIP                      # noqa: E402
import climate as CL                                                        # noqa: E402

GRID_CLIMATE_NPY = GRID_TERRAIN.replace("地形编码.png", "气候_降采样.npy")

T_OCEAN, T_LAKE, T_RIVER, T_ICE, T_DESERT, T_BARE = 0, 1, 2, 3, 4, 5
ST8 = np.ones((3, 3), np.uint8)
ST8[1, 1] = 0
CELL_KM = 0.0625 * 111.32


def perimeter(m: np.ndarray) -> int:
    """栅格周长：与「非 m」4 邻接的 m 格数（够用来做同类比较）。"""
    inside = m
    nb = ndimage.convolve(m.astype(np.uint8), np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]]),
                          mode="constant", cval=0)
    return int((inside & (nb < 4)).sum())


def main() -> int:
    t = np.array(Image.open(GRID_TERRAIN))
    veg = np.load(GRID_VEG) if os.path.exists(GRID_VEG) else None
    desert = t == T_DESERT
    bare = t == T_BARE
    print(f"沙漠 {int(desert.sum()):,} 格 ／ 裸地 {int(bare.sum()):,} 格")

    # ① 边界外侧（4 邻的"非沙漠"那一侧）里，仍是 LC100 裸地的比例
    out_nb = ndimage.convolve((~desert).astype(np.uint8), np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]]),
                              mode="constant", cval=0)
    edge = desert & (out_nb > 0)
    outside = (~desert) & (ndimage.convolve(desert.astype(np.uint8),
                                            np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]]),
                                            mode="constant", cval=0) > 0)
    # ① 那条"缝"的定义是：**同一个事实**（同气候 ∧ 同土地覆盖）的两格却分到不同类。
    #    老规则下 NE 手绘面的边就制造这种格；新规则下应当近乎为零。
    if veg is not None and os.path.exists(GRID_CLIMATE_NPY):
        k = np.load(GRID_CLIMATE_NPY)
        arid = np.isin(k, CL.ARID)
        o = int(outside.sum())
        cut = int((outside & arid & (veg == T_BARE)).sum())
        print(f"① 沙漠边界外侧 {o:,} 格：其中「同为干旱气候 ∧ 同为 LC100 裸地」"
              f"却记为别类的 {cut:,} 格（{cut / o * 100:.1f}%）")
        # 与旧基线同口径的数字（外侧仍是 LC100 裸地），留作对照：老规则 25.5%
        old_like = int((outside & (veg == T_BARE)).sum())
        print(f"   （旧口径对照）外侧仍为 LC100 裸地 {old_like:,} 格"
              f"（{old_like / o * 100:.1f}%；老规则 25.5%）"
              f" —— 现在这多半是**气候线**：外侧不在干旱区，本该是别的类")
    else:
        print("① 缺 植被_降采样.npy 或 气候_降采样.npy，跳过")

    # ② 最长一段笔直边界（8 个方向里连续同向的最长）
    best, bestrc = 0, None
    dirs = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    erc = np.argwhere(edge)
    H, W = edge.shape
    for r, c in erc:
        for dr, dc in dirs:
            n = 0
            rr, cc = int(r), int(c)
            while 0 <= rr < H and 0 <= cc < W and edge[rr, cc]:
                n += 1
                rr += dr
                cc += dc
            if n > best:
                best, bestrc = n, (int(r), int(c), dr, dc)
    print(f"② 最长笔直边界 {best} 格 = {best * CELL_KM:.0f} km"
          f"（起点 {bestrc} ；基线 30 格 = 207 km）")

    # ③ 周长/√面积
    pa, aa = perimeter(desert), int(desert.sum())
    pb, ab = perimeter(bare), int(bare.sum())
    print(f"③ 周长/√面积： 沙漠 {pa / np.sqrt(aa):.1f} ／ 裸地 {pb / np.sqrt(ab):.1f}"
          f"（基线 34.9 / 114.3）")

    # ④ 干旱区覆盖率自检（口径就是沙漠的定义）
    if os.path.exists(GRID_CLIMATE_NPY):
        k = np.load(GRID_CLIMATE_NPY)
        arid = np.isin(k, CL.ARID)
        print(f"④ 干旱气候区 {int(arid.sum()):,} 格；其中记沙漠 {int((arid & desert).sum()):,} 格"
              f"（其余是草原/高原/山地/水体 —— 沙漠只吃 LC100 判「裸地」的那部分）")
    print(f"   （对照）全图地形占比：沙漠 {desert.mean() * 100:.2f}% ／ 裸地 {bare.mean() * 100:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
