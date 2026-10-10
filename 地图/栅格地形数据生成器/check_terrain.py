#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽查生成出来的底图：三条硬检查 + 一组地理常识断言。

    python 地图/栅格地形数据生成器/check_terrain.py            # 读 地图/地图数据/栅格/ 下的产物
    python 地图/栅格地形数据生成器/check_terrain.py --all      # 另外打印占比与零像元地块清单

硬检查（任一不过 → 退出码 1）：

  0. **显示类配色**：任意两类的最小 CIE Lab ΔE ≥ `display_class.PALETTE_MIN_DE`（9.0）。
     名字是**全函数**（见 `地图/栅格地形数据生成器/display_class.py`），所以这里不再查"规则表漏没漏组合"，
     只守"每个显示类都有独特色"这条。
  1. **地块不压海洋**：`覆盖 == 海洋` 的像元上，`地块编码` 必须全部为 0。
     这是需求方定的规矩，也是"海陆口径只有一处"的直接推论。
  2. **地形字节在契约内**：高 5 位覆盖 < 32、低 3 位形态 < 4，且**海洋格的形态位必须是 0**。
  3. **气候层在位**：`气候编码.png` 存在、形状一致、码 ≤ 31。

地理常识断言：一组已知地点，看**覆盖**落在不在"可接受集"里，并顺手打印该格的
**显示类**（覆盖 × 形态 × 气候，是玩家真正看到的名字）。这些点是拿地图对着写的，不追求
全对，只用来抓住"整片错"这种事 —— 比如西宁不是草甸、西伯利亚不是森林、青藏不是高原。

⚠️ 底图里**没有**沙漠/戈壁/寒漠/针叶林/雨林这些名字：它们是**显示类**，由「覆盖 × 形态 × 气候」
当场派生（`docs/adr/0006`、`0010`）。所以这里断言的是**覆盖**（塔克拉玛干断的是
「沙质裸地」、蒙古戈壁断的是「砾质裸地」、西伯利亚断的是「密林/疏林」），而"温带沙漠"这些
名字只出现在打印出来的显示类那一列。

⚠️ 显示类（2026-10-10）由 24 → 59 → 57 → 71 → 77 → **81 类**：名字来自 `display_class.label()`
的**按轴词表**（全函数，任何组合都有名字）；v6 起**林名不写叶型**（叶型就是热量带的函数），
v7 起**裸地按材质分沙／砾**（`adr/0012`）。逐条的判定规则一律以 `docs/地形覆盖判定规格.md` 为准。
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
    # —— 覆盖：裸地拆成**沙质裸地 / 砾质裸地**（v7；LC100 60 只说"裸"，材质由 GSDP30 定）——
    # 这五条的期望是**收紧**的：分得开才是这次改动的兑现，写成"两个都行"就等于没断。
    # ⚠️ 这一点原来写的是 (30,25)「埃及南部·东部沙漠」—— **是我写错了**：30°E 在尼罗河以西，
    # 属**西部**沙漠，那里有大沙海的沙带（GSDP30 该格 100% 有沙）。改到红海丘陵（真正的砾漠）。
    ("埃及东部沙漠·红海丘陵（砾漠）", 33.5, 26.5, {"砾质裸地"}, None),
    ("鲁卜哈利（沙海 erg）", 48.0, 21.0, {"沙质裸地"}, None),
    ("塔克拉玛干（沙海 erg）", 82.0, 39.0, {"沙质裸地"}, None),
    ("蒙古戈壁（砾漠 reg）", 105.0, 43.0, {"砾质裸地", "草原"}, None),
    # 巴丹吉林：**在戈壁区里的沙丘**。v6 的判据（半干旱 → 戈壁）会把它叫成戈壁，
    # 材质判据把它读回沙质 —— 这一条守着"这次到底改对了没有"。
    ("巴丹吉林（戈壁区里的沙丘）", 102.0, 40.0, {"沙质裸地"}, None),
    # 澳洲内陆的灌木林（LC100「灌木」）：v6 之前被并进草原显示成「亚热带草原」，
    # 现在有自己的名字。这一条守着"灌丛不再被叫草原"。
    ("澳洲中部", 133.0, -25.0, {"灌丛", "沙质裸地", "砾质裸地", "草原"}, None),
    # —— 覆盖：草甸（真沙漠气候里判成「绿洲」；高原上仍叫「草甸」——它不按形态派生）——
    ("和田绿洲", 79.9, 37.1, {"绿洲", "草甸", "沙质裸地", "砾质裸地"}, None),
    ("尼罗河三角洲", 31.0, 30.8, {"绿洲", "草甸", "淡湖", "咸湖", "沙质裸地", "砾质裸地"}, None),
    # —— **西北专项**（需求方报"河湟谷地没有、陇右整片高原"）——
    # 河湟谷地：**草甸 ∧ 高原** —— 看得见才是重点（adr/0007）
    ("西宁·河湟谷地", 101.78, 36.62, {"草甸", "草原", "密林", "疏林", "灌丛"},
     {"高原", "丘陵", "山地"}),
    ("天水·陇右", 105.72, 34.58, {"草甸", "草原"}, {"高原", "丘陵", "山地"}),
    ("定西·陇中", 104.63, 35.58, {"草甸", "草原"}, None),
    ("武威·河西", 102.64, 37.93, {"草原", "沙质裸地", "砾质裸地", "绿洲"}, None),
    ("银川·宁夏", 106.23, 38.49, {"绿洲", "草甸", "沙质裸地", "砾质裸地"}, None),
    ("兰州", 103.83, 36.06, {"河流", "草甸", "草原"}, None),
    # —— 形态：山地 / 高原（只看起伏与高程）——
    ("青藏高原", 88.0, 33.0, {"草原", "沙质裸地", "砾质裸地", "冰川"}, {"高原", "山地"}),
    # 喜马拉雅南坡 3547 m 那一格 LC100 说森林——**数据是对的**（远低于树线）。
    ("喜马拉雅", 86.0, 28.0, {"密林", "疏林", "冰川", "草原", "沙质裸地", "砾质裸地"}, {"山地", "高原"}),
    ("蒙古高原", 105.0, 47.0, {"草原", "沙质裸地", "砾质裸地"}, {"高原", "丘陵"}),
    # 黄土高原上的「高原密林」是子午岭，真的（1558 m）。
    ("黄土高原", 108.5, 36.5, {"密林", "疏林", "草原", "草甸", "沙质裸地", "砾质裸地"}, None),
    # —— 盆地 / 平原 ——
    ("四川盆地", 105.0, 30.5, {"草甸", "密林", "疏林"}, {"平原", "丘陵"}),
    ("华北平原", 116.0, 38.0, {"草甸"}, {"平原"}),
    ("东北平原", 125.0, 45.0, {"草甸", "草原"}, {"平原", "丘陵"}),
    ("恒河平原", 85.0, 25.0, {"草甸", "河流"}, None),
    # —— 覆盖：森林（v6 起按郁闭度拆成**密林 / 疏林**；叶型是显示层的事）——
    ("西伯利亚中部", 100.0, 60.0, {"密林", "疏林"}, None),
    ("大兴安岭", 122.0, 52.0, {"密林", "疏林", "草原"}, None),
    ("江南丘陵", 118.0, 29.0, {"密林", "疏林", "草甸"}, None),
    ("日本本州", 138.0, 36.0, {"密林", "疏林", "草甸"}, None),
    ("加里曼丹", 114.0, 0.0, {"密林", "疏林", "河流"}, None),
    ("苏门答腊", 101.0, 0.0, {"密林", "疏林"}, None),
    # —— 水 ——
    # 里海是**咸水湖**（GLWD-1 闭合盆地）：v9 起它读「咸水湖」而不是「湖泊」——改对了。
    ("里海（咸湖，含东南岸）", 51.0, 42.0, {"咸湖"}, None),
    ("里海东南岸（原来残留「海洋」）", 53.0, 41.0, {"咸湖"}, None),
    # —— v9 的四个新类（`docs/adr/0014`）——
    ("贝加尔湖（淡湖，对照）", 108.0, 53.0, {"淡湖"}, None),
    ("青海湖（闭塞咸湖）", 100.2, 36.9, {"咸湖"}, None),
    ("伊朗·卡维尔盐漠", 54.5, 34.5, {"盐漠"}, None),
    ("罗布泊盐漠", 90.5, 40.5, {"盐漠"}, None),
    ("富士山（火山）", 138.73, 35.36, {"火山"}, None),
    ("拉普捷夫海（海冰）", 120.0, 76.0, {"海冰"}, None),
    ("渤海（无海冰——NSIDC 产品不含它）", 119.5, 38.5, {"海洋"}, None),
    # 长芦盐场（天津汉沽—沧州黄骅）：LC100 把蒸发池记成"内陆水体"，原来读「湖泊」；
    # v9 起按"LC100 内陆水体 ∧ 距海 ≤2 格 ∧ 非 GLWD 湖"归**盐沼**（需求方报的"沿海的湖泊"）。
    ("渤海湾·黄骅盐田（→盐沼）", 117.6, 38.28, {"盐沼"}, None),
    # —— v10：**干涸的湖床回水**（`docs/adr/0014` §九）——
    # GLWD-1 说这里是湖、而今天的 LC100 说那是干湖床（裸地/草原/农田）时，接回「湖」。
    # 咸海是主犯：改之前它读**砾质裸地**（2,089 格里 1,984 格是砾质裸地 → 咸湖）。
    ("咸海·大咸海（回水后的咸湖）", 58.5, 45.0, {"咸湖"}, None),
    ("咸海·小咸海（北）", 61.0, 46.3, {"咸湖"}, None),
    # 同一类"今天已萎缩/干涸"的内流湖，顺带修回：
    ("乌尔米耶湖（伊朗，内流咸湖）", 45.5, 37.7, {"咸湖"}, None),
    ("巴伦托列伊湖（外贝加尔，内流）", 115.8, 50.1, {"咸湖"}, None),
    ("巴尔喀什湖（西半，微咸）", 73.5, 45.6, {"咸湖"}, None),
    # **水库必须没被算成湖**（GLWD 水库面画得比今天的水面大）：布拉茨克水库那一片是真的密林。
    ("布拉茨克水库（水库面不算湖，林子保住）", 103.5, 55.2,
     {"密林", "疏林", "灌丛", "草原", "河流"}, None),
    ("贝加尔湖（淡湖）", 108.0, 53.0, {"淡湖", "冰川"}, None),
    ("渤海", 120.0, 38.0, {"海洋"}, None),
    ("黄海", 124.0, 34.0, {"海洋"}, None),
    ("印度洋", 80.0, -10.0, {"海洋"}, None),
    ("南海", 115.0, 15.0, {"海洋"}, None),
]

# (名称, 经度, 纬度, 可接受的**显示类**集) —— 断的是玩家看到的名字（覆盖 × 形态 × 气候）。
# **为什么单开一张表**：下面那两条的**覆盖**是「草原」/「裸地」，而名字才是要守的东西——
# 「苔原」在存储里是覆盖 12、也可以是"草原 ∧ 干湿 0"派生出来的，用覆盖断不了（见 adr/0009）。
EXPECT_DISPLAY = [
    # 亚寒带的低地草地：LC100 记成 30（草本植被），与温带草原**同一个码**。
    # **不声称它是苔原**——亚寒带低地上草甸与苔原并存，LC100 分不出来（`adr/0009`）。
    # ⚠️ v8 起期望放宽到三支：楚科奇内地那格海拔 523 m、**起伏 518 m**，是真正的陡地，
    # 新门槛（350 m）把它正名为**高山草原**；旧门槛 600 m 把它压成丘陵，正是本次要修的错。
    # 这一条的**本意**是"名字里不许出现苔原"（极冷的草地不给单独名字），那一条没变。
    ("楚科奇·亚寒带草地", 175.0, 66.0, {"亚寒带草原", "高山草原", "高原草原"}),
    ("泰梅尔·亚寒带草地", 100.0, 73.0, {"亚寒带草原"}),
    # 寒带（柯本 ET/EF）的草地**不给单独的名字**，按形态与热量带照常命名（`adr/0011`）：
    # 极冷气候下的草地在平地上读「亚寒带草原」，在高原上读「高原草原」，在山上读「高山草原」
    # —— **没有一个带"苔原"二字**，于是「苔原」在整个图例里只有一个来源。
    ("雅库特北·亚寒带草原", 130.0, 71.0, {"亚寒带草原"}),
    # 「苔原」只归**覆盖 = 苔原**那一支（LC100 苔藓/地衣，实测 1.2 万格）。这个点在北极的北地群岛。
    ("北地群岛·苔原", 100.2, 78.4, {"苔原"}),
    # **青藏高原改对了**：覆盖是草原、柯本 ET、形态是高原 → 「高原草原」，不再是苔原。
    ("青藏高原·高原草原", 88.0, 33.0, {"高原草原"}),
    # **沙与砾分开是 v7 的兑现**（`adr/0012`）：沙海读「热带沙漠／温带沙漠」，砾漠读「…戈壁／寒漠」。
    # v6 及之前这两个词由**干湿**定（干旱→沙漠、半干旱→戈壁），而塔克拉玛干与蒙古戈壁在柯本里
    # **同属 BWk**，必然有一个叫错。下面三条**同时**断材质与热量带。
    ("鲁卜哈利·热带沙漠", 48.0, 21.0, {"热带沙漠"}),
    ("塔克拉玛干·温带沙漠", 82.0, 39.0, {"温带沙漠"}),
    # 蒙古戈壁是砾漠；它在蒙古高原上，形态可能读高原，故两种都收（形态那一轴由 [4] 守着）。
    ("蒙古戈壁·温带戈壁", 105.0, 43.0, {"温带戈壁", "高原戈壁"}),
    # 真沙漠气候里的**灌丛**读「沙漠灌丛」——与沙/砾那两支必须不是同一个名字（`adr/0011` 铁律）。
    # 半干旱区（哈萨克、内蒙）有草有灌木的**仍然是草原**——守着"别把 ARID 当 DESERT 用"。
    ("哈萨克·半干旱", 67.0, 48.0, {"温带典型草原", "温带草甸草原", "温带荒漠草原"}),
    # **那条人造纬线没了**：南回归线以南（-25°）的干旱区草地仍读**热带**荒漠草原。
    # v6 及之前这里会切成「亚热带荒漠草原」——分的是一条精确的 23.5° 直线（`adr/0011`）。
    ("澳洲中部·无纬线", 133.0, -25.0, {"热带荒漠草原", "沙漠灌丛", "热带疏林"}),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="另打印占比与零像元地块")
    args = ap.parse_args()

    for p in (GRID_META, GRID_TERRAIN, GRID_PLOT):
        if not os.path.exists(p):
            print(f"缺 {p}：先跑 python 地图/栅格地形数据生成器/生成.py", file=sys.stderr)
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
    print(f"地形字节 = 覆盖×8 + 形态（覆盖在高 5 位）；实测最大 {int(terr_byte.max())}")

    bad = 0
    # ---- 硬检查 0：显示类的**配色契约**（v4：名字是全函数，所以这里只守"每类独特色"） ----
    n_cls, min_de = DC.verify(log=lambda s: None)
    ok0 = min_de >= DC.PALETTE_MIN_DE
    print(f"\n[0] 显示类 {n_cls} 类（名字与配色见 地图/栅格地形数据生成器/display_class.py）：任意两类最小 "
          f"CIE Lab ΔE {min_de:.1f}" + ("✓" if ok0 else
          f"✗ 小于契约的 {DC.PALETTE_MIN_DE:g}（跑 python 地图/栅格地形数据生成器/display_class.py 看是哪几对）"))
    bad += 0 if ok0 else 1
    # ---- 硬检查 1：地块不压海洋 ----
    sea = cover == TR.C_OCEAN
    n_sea_plot = int((sea & (plot > 0)).sum())
    n_non_sea = int((~sea).sum())
    ok1 = n_sea_plot == 0
    print(f"\n[1] 地块不压海洋：海里带地块的像元 {n_sea_plot:,}  " + ("✓" if ok1 else "✗ 失败"))
    # ⚠️ 「非海洋」不等于「陆地」：**海冰**（覆盖 16，v9 起的 72.6 万格）是冻住的海面，
    #   它的形态位与气候码都是 don't-care（管线对海冰只有一个恒名，编辑器两个单轴层也都跳过它）。
    #   所以两个数分开报 —— 混在一起会让"陆地"凭空多 7.7%。
    ice = cover == TR.C_SEAICE
    n_land = int((~sea & ~ice).sum())
    print(f"    陆地 {n_land:,} 格（{n_land / cover.size * 100:.1f}%）；"
          f"另有**海冰** {int(ice.sum()):,} 格（冻住的海面，不算陆地）。"
          f"非海洋格合计 {n_non_sea:,} 格")
    print(f"    陆地里无地块 {int((~sea & ~ice & (plot == 0)).sum()):,} 格"
          f" —— 那就是欧/非/美洲＋未收录区，正常")
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

    # ---- v5：显示类断言（「苔原」与「沙漠」这两个名字用**覆盖**断不了，见 EXPECT_DISPLAY） ----
    print("\n[5] 显示类断言（沙漠按材质分沙/砾 + 热量带 / 苔原只归一源 / 沙漠灌丛不叫沙漠 / 无纬线）：")
    for name, lon, lat, want in EXPECT_DISPLAY:
        x = int((lon - lon0) / cell)
        y = int((lat1 - lat) / cell)
        if not (0 <= x < W and 0 <= y < H):
            print(f"    · {name:<14} 不在窗口内，跳过")
            continue
        if kod is None:
            print(f"    ? {name:<14} 缺气候层，跳过")
            continue
        cv, fm = int(cover[y, x]), int(form[y, x])
        disp = DC.label(cv, fm, int(heat[y, x]), int(moist[y, x]))
        hit = disp in want
        print(f"    {'OK ' if hit else 'BAD'} {name:<14} ({lon:>7.1f},{lat:>6.1f}) → "
              f"{cover_leg[cv]}∧{form_leg[fm]} → {disp}"
              + ("" if hit else f"（期望 {'／'.join(sorted(want))}）"))
        if not hit:
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
