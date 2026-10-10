# -*- coding: utf-8 -*-
"""管线.py —— **流程本身**：一张阶段表 ＋ 一个上下文 ＋ 日志/计时。

原来这是一个 700 行的 `main()`（`地图/栅格地形数据生成器/生成.py`）：变量在几百行之外被赋值，
"顺序即语义"这件事只能靠人读完整段代码才看得出来。现在：

  · **顺序显式成一张表**（下面的 `阶段表`）：每行是「做什么 / 为什么在这一步 / 什么时候跳过」；
  · **每步一个模块**（`阶段/*.py`），拿同一个 `上下文` 读写它那一部分状态；
  · 每步的**耗时与状态**打一行出来，界面上就是那张会亮的清单（`界面.py` 解析 `[3/6]` 这种行）。

⚠️ **阶段顺序是语义的一部分**（后一步压前一步）：比如「海洋收口」必须在「内海/大湖」之前，
「干涸湖床回水」必须在「咸湖」之前。改顺序＝改产物，改完要把 `docs/地形覆盖判定规格.md` §4
那张表一起改（那张表就是照这张表抄的）。
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from 契约 import CELL0, LON0, LON1, LAT0, LAT1, UNITS_JSON, OUT, T_OCEAN
from 参数 import 管线参数
from 阶段 import 陆地与地块, 高程与覆盖, 气候与派生, 水与河, 收口与湖海, 落盘与契约


@dataclass
class 上下文:
    """跑一趟管线要的**全部状态**。阶段之间只通过它说话（别的都是阶段内的局部变量）。

    字段分三组：① 参数与日志；② 网格几何（全流程只算一次）；③ 各阶段产物／中间层。
    没被某个阶段用到的字段就一直是 None —— 这不是"脏"，是"这一步还没跑到"。
    """

    # ① 参数与日志
    参数: 管线参数 = field(default_factory=管线参数)
    log: Callable[..., None] = print

    # ② 网格几何（建上下文时一次算好）
    W: int = 0
    H: int = 0
    LON: np.ndarray = None          # (H, W) 格心经度
    LAT: np.ndarray = None          # (H, W) 格心纬度

    # ③ 各阶段的状态
    层级: str = ""                  # 基础单元.json 里的区划层级键（`d["k"]`）
    单元们: list = None
    种子: list = None
    陆地: np.ndarray = None         # 陆地掩膜（bool）—— 全管线唯一的海陆口径
    地块码: np.ndarray = None
    块区临时: np.ndarray = None
    块区码: np.ndarray = None
    块区局部: np.ndarray = None
    块区台账: list = None
    地形: np.ndarray = None         # **覆盖**那一轴（名字沿用旧代码，见 terrain.py 的说明）
    形态: np.ndarray = None
    高程: np.ndarray = None
    起伏: np.ndarray = None
    植被: np.ndarray = None
    水体: np.ndarray = None
    气候类: np.ndarray = None
    热量带: np.ndarray = None
    干湿: np.ndarray = None
    盐盘: np.ndarray = None
    闭合盆地: np.ndarray = None
    湖面: np.ndarray = None         # GLWD-1 分型码：0 非湖 / 1 湖 / 2 水库
    火山点: np.ndarray = None
    海冰层: np.ndarray = None
    覆盖格数: int = 0
    原始覆盖格数: int = 0
    零像元地块: int = 0
    占比: dict = field(default_factory=dict)
    形态占比: dict = field(default_factory=dict)
    覆盖计数: np.ndarray = None
    形态计数: np.ndarray = None
    参考信息: dict = None
    指纹: str = ""
    台账: dict = None

    def __post_init__(self):
        # 覆盖数组的初值：**全是海洋**；形态全 0。`--no-terrain` 时它们一直是这样，
        # 落盘那一步照样出图（"只有海陆两档"的退化地形），与旧行为一致。
        if self.地形 is None:
            self.地形 = np.full((self.H, self.W), T_OCEAN, dtype=np.uint8)
        if self.形态 is None:
            self.形态 = np.zeros((self.H, self.W), dtype=np.uint8)

    # 给阶段用的一行小工具：`ctx.say("…")` == `ctx.log("   " + "…")`（缩进统一两格）
    def say(self, msg: str) -> None:
        self.log("  " + msg)


# ================================================================ 阶段表
# 一行一阶段：名称 / 模块 / 说明 / **跳过条件**（参数为真时跳过）/ 入口函数
阶段 = []
for _名称, _模块, _说明, _跳过, _fn in [
    ("陆地与地块", 陆地与地块,
     "NE 的陆地/湖泊/冰川区 → 陆地掩膜；基础单元.json → 地块码 + 块区底稿",
     None, 陆地与地块.run),
    ("高程与覆盖", 高程与覆盖,
     "ETOPO 高程/起伏、LC100 覆盖、GSDP30 沙砾、GLWD 盐盘/盆地/湖面、NSIDC 海冰、GVP 火山",
     "no_terrain", 高程与覆盖.run),
    ("气候与派生", 气候与派生,
     "柯本 → 热量带 × 干湿（出 气候编码.png）；气候派生覆盖：绿洲、盐漠",
     "no_terrain", 气候与派生.run),
    ("水与河", 水与河,
     "冰川/湖泊、河网（supercover 点燃 + 修形）、碎水补面、盐沼/滩涂",
     "no_terrain", 水与河.run),
    ("收口与湖海", 收口与湖海,
     "海洋收口 → 内海/大湖 → 湖岸收口 → 盐田 → 干涸湖床回水 → 咸湖 → 火山 → 海冰",
     None, 收口与湖海.run),
    ("落盘与契约", 落盘与契约,
     "地形编码.png、参考顶点、契约断言、底图.bin、台账.json、data.js",
     None, 落盘与契约.run),
]:
    阶段.append({"名称": _名称, "模块": _模块, "说明": _说明, "跳过": _跳过, "函数": _fn})


# ================================================================ 建上下文 / 跑
def 建上下文(参数: 管线参数 | None = None, log: Callable[..., None] = print) -> 上下文:
    """→ 上下文（含网格几何）。缺 基础单元.json 时**直接抛**（上层报错退出，别跑一半）。"""
    p = 参数 or 管线参数()
    if not os.path.exists(UNITS_JSON):
        raise FileNotFoundError(
            f"缺 基础单元.json：先跑 python tools/build_editor.py --dump-units（它出单元与种子地块）")
    os.makedirs(OUT, exist_ok=True)
    cell = p.cell
    W = int(round((LON1 - LON0) / cell))
    H = int(round((LAT1 - LAT0) / cell))
    ctx = 上下文(参数=p, log=log, W=W, H=H)
    ctx.LON, ctx.LAT = np.meshgrid(LON0 + (np.arange(W) + 0.5) * cell,
                                   LAT1 - (np.arange(H) + 0.5) * cell)
    log(f"栅格 {W} × {H} = {W * H / 1e6:.1f} M 像元；像元 {cell}° ≈ {cell * 111:.1f} km")
    _看门槛(ctx)
    return ctx


def _看门槛(ctx: 上下文) -> None:
    """动过契约门槛就在开头吼一声 —— 免得"改了门槛忘了改文档"这种账赖到数据头上。"""
    diff = ctx.参数.门槛.与契约值有别()
    if diff:
        ctx.log("  ⚠️ **规则门槛不是契约值**：" + "、".join(diff)
                + "（规格 §8 与 ADR 里写的是契约值；这一趟的产物**不算契约产品**）")


def 跑(ctx: 上下文, 只跑到: int = 0) -> int:
    """按阶段表跑完（或跑到第 N 步）。→ 0；出异常就往上层抛（界面会把它显示在日志里）。"""
    n = len(阶段)
    for i, s in enumerate(阶段, 1):
        if 只跑到 and i > 只跑到:
            ctx.log(f"[{i}/{n}]（--只跑到 {只跑到}：以下跳过）{s['名称']}")
            break
        跳过 = s["跳过"]
        if 跳过 and getattr(ctx.参数, 跳过):
            ctx.log(f"[{i}/{n}] {s['名称']} —— 跳过（参数 {跳过} 开着）")
            continue
        ctx.log(f"[{i}/{n}] {s['名称']} —— {s['说明']}")
        t0 = time.perf_counter()
        s["函数"](ctx)
        ctx.log(f"[{i}/{n}] {s['名称']} 完成（{time.perf_counter() - t0:.1f} s）")
    return 0
