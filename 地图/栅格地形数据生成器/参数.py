# -*- coding: utf-8 -*-
"""参数.py —— 生成流程的**全部可调项**（界面与命令行都读这一份）。

分两类，界面上分成两栏，**别混**：

  · **管线参数**（`管线参数`）：改它只影响"跑得多细、跑哪几步"，**不改语义**。
    比如格边长、要不要读土地覆盖、河网密度门槛。
  · **规则门槛**（`规则门槛`）：改它**会改产物**，而且**改完就不再是契约产品** ——
    规格文档（`docs/地形覆盖判定规格.md` §8）把这些数写死了，显示类命名与断言都按它们校过。
    界面上这一栏每个数旁边都标着它出自哪条 ADR；动过之后界面顶部会挂一条黄条提醒，
    并且「恢复契约默认」一键回退。

为什么要有这一层：原来这些数散在四个模块的模块级常量里（`terrain.MOUNTAIN_RELIEF`、
`ice.MIN_FRAC`、写死在 `生成.py` 里的 `3000` 与 `2`…），想知道"这张图是按哪套数生成的"
只能去翻代码。现在它们是**一个 dataclass 的字段**，能打印、能存 JSON、能在界面上看到现值。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict, field, fields

import mapdata as MD
import rivers as RV
import terrain as TR


@dataclass
class 规则门槛:
    """**契约值**（`docs/地形覆盖判定规格.md` §8）。改了要同步 ADR＋规格，别只在这里改。"""

    # —— 形态三个数（§5；`adr/0013`）——
    山地起伏: float = TR.MOUNTAIN_RELIEF        # 起伏 > 350 m → 山地
    丘陵起伏: float = TR.HILL_RELIEF            # 起伏 > 120 m → 丘陵
    高原海拔: float = TR.PLATEAU_ELEV           # 海拔 > 1200 m 且起伏小 → 高原
    高原起伏上限: float = TR.PLATEAU_RELIEF_FLAT
    # —— 材质与湿地（§8 第 7/17 条；`adr/0012`）——
    沙占比: float = TR.SAND_PCT                 # GSDP30 有沙占比 ≥ 50% → 沙质裸地
    盐盘占比: float = TR.SALT_PCT               # GLWD-3 盐盘占比 ≥ 50% → 盐漠
    水体占比: float = TR.WATER_PCT              # 格内水占比 ≥ 30% → 算"这一格是水"
    # —— 湖海收口（§8 第 19 条；`adr/0014`）——
    湖岸收口上限格: int = 3000                  # "海洋"块大于它就当它是海（黑海 18,458 过不了）
    盐田距海格: int = 2                         # 沿海盐田/潟湖：距真海 ≤ 2 格才算
    # —— 海冰（§8 第 18 条；`adr/0014` §八）——
    海冰频率: float = 1.0                       # 30 个 3 月里被盖住的比例（1.0 = 常年）
    海冰最低纬度: float = 45.0                  # 只判这条线以北（数据自身的覆盖边界）
    # —— 干涸的湖床回水（§8 第 20 条；`adr/0014` §九）——
    干湖床接回沙砾: bool = True
    干湖床接回草甸草原: bool = True

    def 与契约值有别(self) -> list[str]:
        """→ 与 dataclass 默认值不同的字段名（界面拿它挂黄条）。"""
        base = type(self)()
        return [f.name for f in fields(self) if getattr(self, f.name) != getattr(base, f.name)]


@dataclass
class 管线参数:
    cell: float = MD.CELL                 # 格边长（度）；默认 1/19° ≈ 5.86 km
    no_terrain: bool = False              # 只出地块层（不等高程）
    no_veg: bool = False                  # 不读土地覆盖 → 地形只剩海陆两档
    raw_lc100: bool = False               # 裸数组自检通过时用它（那份残件已删，一般用不上）
    river_min: float = RV.MIN_CMS         # 画流量 ≥ 此值的河段（河网密度**唯一**的旋钮）
    中途停在第几步: int = 0               # 0 = 全跑；n > 0 = 只跑前 n 步（调试用）
    门槛: 规则门槛 = field(default_factory=规则门槛)


# ================================================================ 命令行
# 命令行与界面走的是**同一份**参数：界面把控件读成 管线参数 后调 `做命令行()`，
# 所以"界面能做的命令行也能做"，两条路不会分叉。
def 加命令行参数(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--cell", type=float, default=MD.CELL,
                    help=f"像元边长（度）；默认 1/19° ≈ 5.86 km（0.075° ≈ 8.3 km 粗一档，"
                         f"1/16° = 0.0625° ≈ 6.9 km 是 2026-10-08 之前的旧值）")
    ap.add_argument("--no-terrain", action="store_true", help="只出地块层（不读高程，不等地形）")
    ap.add_argument("--no-veg", action="store_true", help="不读 Copernicus 土地覆盖")
    ap.add_argument("--raw-lc100", action="store_true",
                    help="若裸数组存在且自检通过则用它（那份残件已删，一般用不上）")
    ap.add_argument("--river-min", type=float, default=RV.MIN_CMS, metavar="CMS",
                    help=f"画哪些河：HydroRIVERS 的多年平均流量 ≥ 此值（m³/s，默认 "
                         f"{RV.MIN_CMS:g}）。**河网密度就调这一个旋钮**："
                         f"100 → 全图约 12.9 万格；50 → 15.3 万；20 → 20.5 万（太密）；200 → 更疏。")
    ap.add_argument("--只跑到", type=int, default=0, metavar="N",
                    help="只跑前 N 步就停（调试某一步用；0 = 全跑）")
    g = ap.add_argument_group(
        "规则门槛（⚠️ 改了就**不再是契约产品**：规格 §8 把这些数写死了，见 docs/adr/0013/0014）")
    g.add_argument("--山地起伏", type=float, default=TR.MOUNTAIN_RELIEF)
    g.add_argument("--丘陵起伏", type=float, default=TR.HILL_RELIEF)
    g.add_argument("--高原海拔", type=float, default=TR.PLATEAU_ELEV)
    g.add_argument("--高原起伏上限", type=float, default=TR.PLATEAU_RELIEF_FLAT)
    g.add_argument("--沙占比", type=float, default=TR.SAND_PCT)
    g.add_argument("--盐盘占比", type=float, default=TR.SALT_PCT)
    g.add_argument("--水体占比", type=float, default=TR.WATER_PCT)
    g.add_argument("--湖岸收口上限格", type=int, default=3000)
    g.add_argument("--盐田距海格", type=int, default=2)
    g.add_argument("--海冰频率", type=float, default=1.0)
    g.add_argument("--海冰最低纬度", type=float, default=45.0)
    g.add_argument("--不接回沙砾湖床", action="store_true", help="干涸湖床回水：不接回沙质/砾质裸地")
    g.add_argument("--不接回草地湖床", action="store_true", help="干涸湖床回水：不接回草甸/草原")


def 从命令行(args: argparse.Namespace) -> 管线参数:
    return 管线参数(
        cell=args.cell, no_terrain=args.no_terrain, no_veg=args.no_veg,
        raw_lc100=args.raw_lc100, river_min=args.river_min, 中途停在第几步=args.只跑到,
        门槛=规则门槛(
            山地起伏=args.山地起伏, 丘陵起伏=args.丘陵起伏, 高原海拔=args.高原海拔,
            高原起伏上限=args.高原起伏上限, 沙占比=args.沙占比, 盐盘占比=args.盐盘占比,
            水体占比=args.水体占比, 湖岸收口上限格=args.湖岸收口上限格,
            盐田距海格=args.盐田距海格, 海冰频率=args.海冰频率, 海冰最低纬度=args.海冰最低纬度,
            干湖床接回沙砾=not args.不接回沙砾湖床,
            干湖床接回草甸草原=not args.不接回草地湖床))


def 做命令行(p: 管线参数) -> list[str]:
    """→ 与 `加命令行参数` 一一对应的 argv（界面把控件读成参数后走它起子进程）。"""
    a = ["--cell", repr(p.cell)]
    if p.no_terrain: a.append("--no-terrain")
    if p.no_veg: a.append("--no-veg")
    if p.raw_lc100: a.append("--raw-lc100")
    a += ["--river-min", repr(p.river_min)]
    if p.中途停在第几步: a += ["--只跑到", str(p.中途停在第几步)]
    m = p.门槛
    a += ["--山地起伏", repr(m.山地起伏), "--丘陵起伏", repr(m.丘陵起伏),
          "--高原海拔", repr(m.高原海拔), "--高原起伏上限", repr(m.高原起伏上限),
          "--沙占比", repr(m.沙占比), "--盐盘占比", repr(m.盐盘占比),
          "--水体占比", repr(m.水体占比), "--湖岸收口上限格", str(m.湖岸收口上限格),
          "--盐田距海格", str(m.盐田距海格), "--海冰频率", repr(m.海冰频率),
          "--海冰最低纬度", repr(m.海冰最低纬度)]
    if not m.干湖床接回沙砾: a.append("--不接回沙砾湖床")
    if not m.干湖床接回草甸草原: a.append("--不接回草地湖床")
    return a


def 存JSON(p: 管线参数, path: str) -> None:
    """把参数写成 JSON（界面用的「参数记忆」：下次打开界面时恢复上次那一套）。"""
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(p), f, ensure_ascii=False, indent=1)


def 读JSON(path: str) -> 管线参数 | None:
    """→ 参数；文件不在/读坏了/字段对不上就返回 None（界面退回契约默认值，不炸）。"""
    import json
    import os
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        m = 规则门槛(**{k: v for k, v in (d.get("门槛") or {}).items()
                       if k in {f.name for f in fields(规则门槛)}})
        return 管线参数(**{k: v for k, v in d.items() if k in {f.name for f in fields(管线参数)}
                          and k != "门槛"}, 门槛=m)
    except Exception:                                                         # noqa: BLE001
        return None
