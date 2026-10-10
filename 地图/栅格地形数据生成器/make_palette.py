# -*- coding: utf-8 -*-
"""生成 / 校验**显示类配色**：以语义锚点为球心，在 CIE Lab 空间做排斥，直到任意两类 ΔE ≥ 门槛。

    python 地图/栅格地形数据生成器/make_palette.py            # 重算，打印一份 PAINT（不写文件）
    python 地图/栅格地形数据生成器/make_palette.py --check    # 只校验 display_class.PAINT 够不够开

为什么要留这个脚本：`adr/0008` 把上一版调色脚本写成"一次性、已删"，结果是**那张表没人复现得出来**，
改色只能手调、还量不准。锚点表就在下面，语义意图（哪一族该是什么色相）写在那里，改色改这里。

算法（三步）：
  1. **排斥**：把 59/71 个点放进 Lab，凡距离 < 目标的互相推开，同时**硬钳在"离锚点 ≤ K"的球里**
     （K 是"允许多不像原来的语义色"）。这一步比"给每类挑一个最远的颜色"重要得多 ——
     后者数值上能过 ΔE，但会挑出紫色的密林、粉色的沙漠。
  2. **量化**到 8 位 RGB，回到色域。
  3. **补漏**：取整可能把某一对压到门槛以下，就只在那一对附近 ±2/通道做局部搜索修掉。
"""
from __future__ import annotations

import argparse
import itertools
import sys

import numpy as np

# ---------------------------------------------------------------- 语义锚点
# 族（色相）与族内拉开方式：
#   水 199–235 蓝 ｜ 冰 近白→灰蓝（明度拉开）｜ 森林 绿（**密林深、疏林浅**；热量带=色相偏移）
#   灌丛 橄榄（比森林偏黄、偏灰）｜ 草原 黄绿（**色相=热量带、明度=干湿三档**）
#   草甸 暖黄浅 ｜ 裸地 土黄—褐—灰（**干湿定基调，形态定深浅**）
#   沼泽 170 青灰 ｜ 盐沼 104 ｜ 滩涂 20 ｜ 绿洲 132
ANCHORS: dict[str, str] = {
    # ---- 水（蓝）----
    "海洋": "#6f9ab8", "淡湖": "#91c7de", "高原淡湖": "#6c92c6",
    "河流": "#306acf", "高原河流": "#334b99", "山地河流": "#313668",
    # ---- 冰（近白 → 灰蓝，靠明度拉开）----
    "冰川": "#f3f9fc", "高原冰川": "#d7dfe6", "山地冰川": "#a9b5c1",
    # ---- 森林（绿：**密林深、疏林浅**；形态前缀再压一档明度）----
    "热带密林": "#1d5d43", "亚热带密林": "#2e7641", "温带密林": "#4a8a35", "亚寒带密林": "#1f4721",
    "热带疏林": "#4c956e", "亚热带疏林": "#68a26f", "温带疏林": "#8db06d", "亚寒带疏林": "#426742",
    "高原热带密林": "#23503f", "高原亚热带密林": "#356b47", "高原温带密林": "#4a7d3c",
    "高原亚寒带密林": "#24442a",
    "高原热带疏林": "#3f7a63", "高原亚热带疏林": "#5c8a62", "高原温带疏林": "#7a9a62",
    "高原亚寒带疏林": "#4a6a4d",
    "山地热带密林": "#20504c", "山地亚热带密林": "#2f6b58", "山地温带密林": "#456f3c",
    "山地亚寒带密林": "#223f34",
    "山地热带疏林": "#3b7a7a", "山地亚热带疏林": "#528c78", "山地温带疏林": "#6d8f5f",
    "山地亚寒带疏林": "#456652",
    # ---- 灌丛（橄榄：偏黄、偏灰，与森林的绿分开）----
    #     ⚠️ 真沙漠气候里的灌丛读作**沙漠灌丛**（与"裸地→沙漠"分开，`adr/0011`）----
    "热带灌丛": "#8f9a4a", "亚热带灌丛": "#7d8f5c", "温带灌丛": "#9aa86a", "亚寒带灌丛": "#6b7f57",
    "高原灌丛": "#8a9163", "山地灌丛": "#5f6b45",
    "沙漠灌丛": "#b0a06a", "高原沙漠灌丛": "#9a8a5c", "山地沙漠灌丛": "#7d6f4c",
    # ---- 草原（黄绿：色相=热量带，明度=干湿三档）----
    "苔原": "#caccbf", "高原草原": "#828d53", "高山草原": "#626141",
    "热带荒漠草原": "#cdbca3", "热带干草原": "#bc9f69", "热带稀树草原": "#aa813c",
    "热带草原": "#bbc77e",
    "亚热带荒漠草原": "#cec79f", "亚热带典型草原": "#bdba68", "亚热带草丛": "#aaa23c",
    "温带荒漠草原": "#cad7a6", "温带典型草原": "#a8bd66", "温带草甸草原": "#90aa3c",
    "亚寒带草原": "#73ac3c",
    # ---- 草甸（暖黄，浅）----
    "热带草甸": "#d7c071", "亚热带草甸": "#eadc9d", "温带草甸": "#e8daba",
    "高原草甸": "#d7d184", "山地草甸": "#ab984a",
    # ---- 湿地与海岸 ----
    "沼泽": "#669991", "寒沼": "#bacdcd", "盐沼": "#98ac91", "滩涂": "#baa9a0",
    # ---- 裸地（土黄—褐—灰：**材质定色族、热量带定暖冷、形态定深浅**）----
    #     ⚠️ v7 起「沙漠」与「戈壁」按**材质**分（`adr/0012`）：沙质＝沙黄，砾质＝褐灰。
    #     热量带在族内靠色相/明度拉：热带偏橙红、亚寒带偏灰白。
    "热带沙漠": "#dcab52", "亚热带沙漠": "#d5b272", "温带沙漠": "#c5a262", "亚寒带沙漠": "#b6a486",
    "沙质裸地": "#cdbf9c",
    "高原沙漠": "#bd9c42", "山地沙漠": "#916f3b",
    "热带戈壁": "#b28a60", "亚热带戈壁": "#a8896a", "温带戈壁": "#9b7f62", "亚寒带戈壁": "#9a8770",
    "砾质裸地": "#b5b0a6",
    "高原戈壁": "#8d6c53", "山地戈壁": "#644d40", "寒漠": "#a9a293",
    # ---- 派生 ----
    "绿洲": "#3da451",
    # ---- v9 追加（`adr/0014`）：海冰／咸水湖／盐漠／火山 ----
    "海冰": "#a9cfe0", "咸湖": "#4f8fb0", "高原咸湖": "#3f7a9c",
    "盐漠": "#cfcabb", "高原盐漠": "#bdb7a4", "山地盐漠": "#9c9684",
    "火山": "#5d4a44",
}

TARGET = 12.0     # 排斥的目标距离（比门槛大一点，留量化余量）
ALLOW = 8.0       # 锚点允许被推多远（K）：0 = 一点不许改色，越大越失真


def srgb2lab(rgb: np.ndarray) -> np.ndarray:
    v = np.asarray(rgb, float) / 255.0
    lin = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], -1)


def lab2rgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200
    inv = lambda t: np.where(t ** 3 > 0.008856, t ** 3, (t - 16 / 116) / 7.787)
    x, y, z = inv(fx) * 0.95047, inv(fy), inv(fz) * 1.08883
    m = np.array([[3.2404542, -1.5371385, -0.4985314],
                  [-0.9692660, 1.8760108, 0.0415560],
                  [0.0556434, -0.2040259, 1.0572252]])
    lin = np.stack([x, y, z], -1) @ m.T
    v = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.maximum(lin, 0) ** (1 / 2.4) - 0.055)
    return v * 255.0


def hx(h: str) -> tuple[int, int, int]:
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


def tohex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(round(x)) for x in c)


def _clamp_sphere(lab, base, k):
    v = lab - base
    n = np.linalg.norm(v, axis=1)
    over = n > k
    lab[over] = base[over] + v[over] / n[over][:, None] * k
    return lab


def relax(base, k=ALLOW, target=TARGET, iters=3000, step=0.4):
    n = len(base)
    iu, ju = np.triu_indices(n, 1)
    lab = base.copy()
    for _ in range(iters):
        d = np.linalg.norm(lab[iu] - lab[ju], axis=1)
        near = d < target
        if not near.any():
            break
        u = (lab[iu][near] - lab[ju][near]) / d[near][:, None]
        push = u * ((target - d[near]) * 0.5)[:, None]
        f = np.zeros_like(lab)
        np.add.at(f, iu[near], push)
        np.add.at(f, ju[near], -push)
        lab = _clamp_sphere(lab + step * f, base, k)
        lab = _clamp_sphere(srgb2lab(np.clip(lab2rgb(lab), 0, 255).round()), base, k)
    return lab


def min_de(labs: np.ndarray) -> tuple[float, tuple]:
    n = len(labs)
    iu, ju = np.triu_indices(n, 1)
    d = np.linalg.norm(labs[iu] - labs[ju], axis=1)
    k = int(np.argmin(d))
    return float(d[k]), (iu[k], ju[k])


def repair(colors: np.ndarray, labs: np.ndarray, floor: float):
    """量化之后的补漏：只动低于门槛的那些对，±2/通道局部搜索，认提升全局最小值的改法。"""
    n = len(colors)
    for _ in range(6):
        worst, (a, b) = min_de(labs)
        if worst >= floor:
            break
        best = None
        for idx in (a, b):
            origin = colors[idx].copy()
            for dr in range(-2, 3):
                for dg in range(-2, 3):
                    for db in range(-2, 3):
                        cand = np.clip(origin + (dr, dg, db), 0, 255)
                        old = labs[idx]
                        labs[idx] = srgb2lab(cand)
                        w, _ = min_de(labs)
                        if best is None or w > best[0]:
                            best = (w, idx, cand, labs[idx].copy())
                        labs[idx] = old
        if best is None or best[0] <= worst:
            break
        _, idx, cand, lab = best
        colors[idx], labs[idx] = cand, lab
    return colors, labs


def build(names: list[str]) -> dict[str, str]:
    base = np.stack([srgb2lab(hx(ANCHORS[n])) for n in names])
    lab = relax(base)
    colors = np.clip(lab2rgb(lab), 0, 255).round()
    labs = srgb2lab(colors)
    colors, labs = repair(colors, labs, 9.0)
    return {n: tohex(c) for n, c in zip(names, colors)}


def report(paint: dict[str, str], log=print) -> float:
    names = list(paint)
    labs = np.stack([srgb2lab(hx(paint[n])) for n in names])
    w, (a, b) = min_de(labs)
    disp = np.linalg.norm(labs - np.stack([srgb2lab(hx(ANCHORS[n])) for n in names]), axis=1)
    log(f"  {len(names)} 类；任意两类最小 ΔE = {w:.2f}（{names[a]} ／ {names[b]}）；"
        f"锚点位移中位 {np.median(disp):.2f} / 最大 {disp.max():.2f}")
    return w


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验当前 display_class.PAINT")
    ap.add_argument("--floor", type=float, default=9.0)
    args = ap.parse_args()
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))

    if args.check:
        import display_class as dc
        rep = dc.check_palette(args.floor, log=print)
        return 0 if not rep["bad"] else 1

    import display_class as dc
    # ⚠️ 不用 `dc.classes()`：它断言 PAINT 与类集一致，而重算配色的**前提**正是 PAINT 已经过时。
    # 直接按 `_order()` × `label()` 枚举名字（与 classes() 同一套口径）。
    want: list[str] = []
    for c, f, h, m in dc._order():
        n = dc.label(c, f, h, m)
        if n not in want:
            want.append(n)
    missing = [n for n in want if n not in ANCHORS]
    extra = [n for n in ANCHORS if n not in want]
    assert not missing and not extra, f"锚点与显示类对不上：缺 {missing} 多 {extra}"
    paint = build(want)
    w = report(paint, log=lambda s: None)
    print(f"# {len(paint)} 类，最小 ΔE {w:.2f}（门槛 {args.floor:g}）；"
          f"锚点允许多跑 {ALLOW:g}")
    for n in want:
        print(f'    "{n}": "{paint[n]}",')
    return 0 if w >= args.floor else 1


if __name__ == "__main__":
    raise SystemExit(main())
