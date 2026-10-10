# -*- coding: utf-8 -*-
"""栅格工具.py —— 地形流程的**底层动作**：矢量烧进栅格、河线修形、运行态打包、契约断言。

这些函数都以**参数**收栅格数组（不认 `ctx`），所以阶段与检查脚本都能直接调；它们由 `_拆分.py`
从原 `生成.py` **逐字搬来**（只把 `burn`/`burn_lines` 两个闭包改成显式收 `ctx`）。

判断"某个函数该放这儿还是放阶段里"：它**要不要读管线状态**？
  · 不要（只认传进来的数组）→ 就是工具，放这里；
  · 要（读 ctx.地形 / ctx.陆地…）→ 那是**一步流程**，放 `阶段/`。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import zipfile

import numpy as np
from PIL import Image
from scipy import ndimage as nd
from shapely.geometry import MultiPolygon, Polygon, shape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import climate as CL                                                    # noqa: E402
import display_class as DC                                              # noqa: E402
import mapdata as MD                                                     # noqa: E402
import terrain as TR                                                    # noqa: E402
from basetag import legend_tag as _bt_legend_tag, name_tag as _bt_name_tag   # noqa: E402
from geo_wrap import wrap_into, supercover                               # noqa: E402
from mapdata import HARTWELL_ZIP                                         # noqa: E402
from 契约 import *   # noqa: F401,F403,E402  （工具模块的底层动作要用到契约里的一批常量）

def assert_contract(terrain, form, plot_id, districts, heat, moist, klim, lat, land, log=print):
    """数据契约断言（`docs/adr/0006` + `0007`）。**红一条就抛，不许静默落盘。**

    为什么值得为它们开一个函数：v3 把覆盖压到 4 位、形态压到 4 位、地块压到 **13** 位、
    块区压到 8 位局部码，余量都不大；而"余量用尽"这件事一旦发生，后果是**静默截断**
    （溢出回绕写进 PNG，图上根本看不出是哪一格坏了）。所以宁可让管线在最后一步红掉。

    第 5 条（无气候洞）最隐蔽：干湿码 0 同时表示「寒带」与「无气候数据」，空洞会被读成
    寒带。**它第一次上线就把这条拦下来了**：原先以为那些洞都在极地（只看过纬度最高的 3 格
    就写了"实测全在 81.7–81.8°N"），实测 11,352 格里有阿拉斯加、波罗的海、堪察加，
    纬度最低到 9.4°N——柯本把水体与冰盖 mask 成 nodata，而 NE 说那是陆。修法是
    `CL.fill_land_nodata` 补洞，这条断言守着它不再长回来。

    第 6 条（显示类覆盖全组合）是 v3 新加的：拆成两轴之后，`(覆盖, 形态)` 的组合数从 14
    涨到 16×4，**规则表漏一个组合**的后果是编辑器里显示 "地形 undefined"（v1 真的发生过：
    调色板里存了下标而不是颜色串）。
    """
    bad = []
    if int(terrain.max()) >= 1 << 5:
        bad.append(f"覆盖码最大 {int(terrain.max())} ≥ 32（高 5 位装不下）")
    if form is not None and int(form.max()) >= 1 << 4:
        bad.append(f"形态码最大 {int(form.max())} ≥ 16（低 4 位装不下）")
    if form is not None and int(form[terrain == T_OCEAN].max(initial=0)) != 0:
        bad.append("海洋格的形态位不是 0（海洋没有形状可言）")
    if int(plot_id.max()) > 4095:
        bad.append(f"地块编号最大 {int(plot_id.max())} > 4,095（12 位装不下）")
    if heat is not None and int(heat.max()) > 3:
        bad.append(f"热量带最大 {int(heat.max())} > 3（2 位装不下）")
    if moist is not None and int(moist.max()) > 7:
        bad.append(f"干湿码最大 {int(moist.max())} > 7（3 位装不下）")
    per_plot = {}
    for d in districts:
        per_plot[d["plot"]] = per_plot.get(d["plot"], 0) + 1
    worst = max(per_plot.values()) if per_plot else 0
    if worst > 255:
        bad.append(f"单个地块下辖块区最多 {worst} > 255（8 位局部码装不下）")
    if klim is not None:
        n, minlat = CL.polar_nodata(klim, lat, land)
        if n:
            bad.append(f"陆地上还有 {n} 格无气候数据（最小 |纬度| {minlat:.1f}°）——"
                       f"干湿码 0 会把它静默读成「寒带」；先补洞（CL.fill_land_nodata）")
    if form is not None:
        # 第 6 条（显示类）v4 起换了口径：名字是**全函数**（地图/栅格地形数据生成器/display_class.py 的按轴词表），
        # 不再有"规则表漏了哪个组合"这回事，也没有"被前面通配规则吃掉的死规则"——**没有规则**。
        # 改成守两件真会错的事：
        #   · `display_lut` 必须**覆盖全部组合**（`DC.N_COMBO`，v7 起 16×4×32 = 2048；编辑器只查这张表，940 万格全走它）；
        #   · **任意两类的最小 ΔE ≥ 9**（"每个显示类都有独特色"不能只靠肉眼）。
        _n_cls, min_de = DC.verify(log=log)
        if min_de < DC.PALETTE_MIN_DE:
            bad.append(f"显示类配色最小 ΔE {min_de:.1f} < {DC.PALETTE_MIN_DE}"
                       f"（见 python 地图/栅格地形数据生成器/display_class.py 的 ΔE 报告）")
        if heat is not None and moist is not None:
            DC.usage(TR.pack(terrain, form), CL.pack(heat, moist), log=log)
    log(f"  契约断言：覆盖 <32 ✓  形态 <4 ✓  海洋形态=0 ✓  地块 ≤4,095 ✓  "
        f"热量带 ≤3 / 干湿 ≤7 ✓  每地块块区 ≤255（实测最多 {worst}）✓  "
        f"陆地无气候洞 ✓  显示类 LUT 全覆盖 + 配色最小 ΔE ≥ {DC.PALETTE_MIN_DE:g} ✓")
    assert not bad, "数据契约被破坏：\n  · " + "\n  · ".join(bad)


# ---------------------------------------------------------------- 读取

# ---------------------------------------------------------------- 读取

def ne_features(path: str):
    """path：原始件完整路径（文件名见 地图/栅格地形数据生成器/mapdata.py，都中文）"""
    if not os.path.exists(path):
        print(f"  ! 缺 {os.path.basename(path)}，跳过", file=sys.stderr)
        return []
    import shapefile
    z = zipfile.ZipFile(path)
    shp = [n for n in z.namelist() if n.endswith(".shp")][0]
    sf = shapefile.Reader(shp=io.BytesIO(z.read(shp)), dbf=io.BytesIO(z.read(shp[:-4] + ".dbf")))
    return [(shape(sr.shape.__geo_interface__), sr.record.as_dict()) for sr in sf.iterShapeRecords()]


def unit_polys(u, k):
    polys = []
    for rr in u["g"]:
        rng = lambda r: [(r[i] / k, r[i + 1] / k) for i in range(0, len(r), 2)]
        polys.append(Polygon(rng(rr[0]), [rng(h) for h in rr[1:]]))
    return MultiPolygon(polys) if len(polys) > 1 else polys[0]


def wraps(g):
    """几何在连续经度窗口下的分段：沿窗口两条缝切开再整段平移。
    绝不能逐点折回——那会切穿几何，把它拉成横贯全图的带（本轮色条的根因）。"""
    return wrap_into(g, LON0, LON1)


def bbox_cells(g, cell, W, H):
    x0, y0, x1, y1 = g.bounds
    c0 = max(0, int(np.floor((x0 - LON0) / cell)) - 1)
    c1 = min(W, int(np.ceil((x1 - LON0) / cell)) + 1)
    r0 = max(0, int(np.floor((LAT1 - y1) / cell)) - 1)
    r1 = min(H, int(np.ceil((LAT1 - y0) / cell)) + 1)
    return c0, c1, r0, r1


def encode_id(a: np.ndarray) -> np.ndarray:
    """uint16 编码 → 24 位 RGB（R + G*256）。canvas 会把 16 位灰度降成 8 位，故不用灰度。"""
    rgb = np.zeros((a.shape[0], a.shape[1], 3), dtype=np.uint8)
    rgb[..., 0] = a & 0xFF
    rgb[..., 1] = (a >> 8) & 0xFF
    return rgb



def seal_river_gaps(terrain: np.ndarray, value: int, water, log=print) -> int:
    """把同一条河被**折线端点错位**切出的 ≤3 格缝接上。返回封了几处。

    为什么 `burn_lines` 之后还需要这一步：NE 的 `rivers_lake_centerlines` 是**概化**过的
    线网，它自己在湖泊两端与支流汇口处会把线切断，而两条折线的端点并不重合。实测长江的
    MultiLineString 就分 3 段，淮河入江口那处两端点差 **2 格**（119.56E 32.25N）——
    4 邻接断开，屏幕上就是"断流"。`burn_lines` 只保证**单条折线内部** 4 邻接连通，
    管不了折线与折线之间的缝（修完那一层，全图 4 邻接碎段 6,834 → 265，剩下的 265 里
    有 10 处是这种端点缝）。

    判据取**保守**（宁漏不滥，接错了比断着更难看）：

      · 只在**骨架端点**之间连 —— 端点是"线头"；线的腰部不能当端点用。
      · 只连 ≤3.5 格（≈24 km）的缝；其中 ≤2 格的无条件连，>2 格的**要有一端的朝向
        指着对方**（否则可能把两条本来不相干的河接上）。
      · 每个线头最多用一次（按距离贪心，先近后远）。
      · 桥经过的格子若已是**海洋或湖泊**就不封：海是真正的分隔；湖与河同为蓝色，
        视觉上本来就不算断（把湖改成河反而是改错了东西）。
    """
    from scipy import ndimage
    from skimage.morphology import skeletonize

    H, W = terrain.shape
    riv = terrain == value
    if int(riv.sum()) < 3:
        return 0
    st4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], np.uint8)
    st8 = np.ones((3, 3), np.uint8)
    st8[1, 1] = 0
    lab, n0 = ndimage.label(riv, structure=st4)
    skel = skeletonize(riv)
    ends = np.argwhere(skel & (ndimage.convolve(skel.astype(np.uint8), st8,
                                                mode="constant", cval=0) == 1))

    def out_dir(r, c, steps=4):
        """从线头沿骨架向内走若干格，返回**朝外**的单位方向（(dy, dx)）。"""
        prev, cur, seen = None, (int(r), int(c)), {(int(r), int(c))}
        for _ in range(steps):
            nxt = None
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = cur[0] + dr, cur[1] + dc
                    if 0 <= nr < H and 0 <= nc < W and skel[nr, nc] and (nr, nc) not in seen:
                        nxt = (nr, nc)
                        break
                if nxt:
                    break
            if not nxt:
                break
            seen.add(nxt)
            prev, cur = cur, nxt
        if prev is None:
            return None
        dy, dx = cur[0] - r, cur[1] - c
        n = (dy * dy + dx * dx) ** 0.5
        return (-dy / n, -dx / n) if n else None

    pairs = []
    for i in range(len(ends)):
        ri, ci = ends[i]
        for j in range(i + 1, len(ends)):
            rj, cj = ends[j]
            if lab[ri, ci] == lab[rj, cj]:
                continue                                # 同一段，不用接
            d = float(((ri - rj) ** 2 + (ci - cj) ** 2) ** 0.5)
            if d > 3.5:
                continue
            vy, vx = (rj - ri) / d, (cj - ci) / d
            di, dj = out_dir(ri, ci), out_dir(rj, cj)
            ai = di[0] * vy + di[1] * vx if di else 0.0                # i 是否朝着 j
            aj = dj[0] * -vy + dj[1] * -vx if dj else 0.0              # j 是否朝着 i
            if d <= 2.05 or ai >= 0.5 or aj >= 0.5:
                pairs.append((d, (int(ri), int(ci)), (int(rj), int(cj))))
    # **端点 → 任意河格（T 型汇口）**：上一版只在"端点↔端点"之间接，管不了"支流端点指向
    # 干流腰部"这种最常见的汇口。实测漏出来的缝全属于这一类（如南京段长江 118.63E/32.11N，
    # 两条折线只差 1.41 格、还都是端点，但一条是另一条的"腰"）。做法：沿端点朝外的方向
    # 找一个锥形扇面（±50°）内最近的**别的段**的河格，≤3.5 格就接。
    import math
    erc2 = {}
    for i in range(len(ends)):
        ri, ci = int(ends[i][0]), int(ends[i][1])
        di = out_dir(ri, ci)
        if di is None:
            continue
        best = None
        R = 4
        for dy in range(-R, R + 1):
            for dx in range(-R, R + 1):
                if dy == 0 and dx == 0:
                    continue
                rj, cj = ri + dy, ci + dx
                if not (0 <= rj < H and 0 <= cj < W):
                    continue
                if not riv[rj, cj] or lab[rj, cj] == lab[ri, ci]:
                    continue
                d = math.hypot(dy, dx)
                if d > 3.6:
                    continue
                cos = (di[0] * dy + di[1] * dx) / d          # 是否朝着它
                if cos < 0.5:
                    continue
                if best is None or d < best[0]:
                    best = (d, (rj, cj))
        if best is not None:
            erc2[(ri, ci)] = best
    for a, (d, b) in erc2.items():
        pairs.append((d, a, b))
    pairs.sort(key=lambda t: t[0])

    used, sealed = set(), 0
    for _d, a, b in pairs:
        if a in used or b in used:
            continue
        used.add(a)
        used.add(b)
        cells = [(y, x) for y, x in supercover(a, b) if 0 <= y < H and 0 <= x < W]
        # 跨水面的桥：**只禁长的**。河中间夹 1 格小湖、河口那 1 格，本来就是河自己
        # （不接就是地图上一个亮点，实测需求方看到的就是这个）；而贝加尔那种长水面，
        # 河本来就该在湖岸断掉（进湖—出湖）。所以只允许桥经过 ≤2 格水面。
        if sum(1 for y, x in cells if terrain[y, x] in water) > 2:
            continue
        for y, x in cells:
            terrain[y, x] = value
        sealed += 1
    n1 = int(ndimage.label(terrain == value, structure=st4)[1])
    log(f"  河流封缝：{len(ends)} 个线头 → 封 {sealed} 处（4 邻接碎段 {n0} → {n1}）")
    return sealed


def cleanup_river_specks(terrain, before, value: int, min_cells: int, log=print) -> int:
    """丢掉短于 min_cells 的河段（还原成**烧伤之前**的地形类），返回丢了几格。

    为什么需要：线网是从**分区文件**拼起来的（HydroRIVERS 只下了 as/si/eu/au 四片），
    一条河的链条可能上游落在没下到的那片里，于是只剩孤零零一格插在海岛或海岸上。
    实测这一版有 7,340 个「孤立单格河」，海拔中位 **10 m**、48% 的邻格是海洋 ——
    全是北冰洋小岛与河口处的碎片。一格 6.9 km，画出来就是地图上的蓝色噪点。

    判据只看**连通段大小**（短于栅格分辨能力的不画），不看位置，不挑肥拣瘦。
    `before` 是河烧伤之前的 terrain 快照，丢掉的位置直接还原回去。
    """
    from scipy import ndimage
    st4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    riv = terrain == value
    lab, n = ndimage.label(riv, structure=st4)
    if not n:
        return 0
    sizes = np.bincount(lab.ravel())
    tiny = np.where((sizes > 0) & (sizes < min_cells))[0]
    drop = np.isin(lab, tiny)
    k = int(drop.sum())
    if k:
        terrain[drop] = before[drop]
    log(f"  河段去散点：{n:,} 段里丢掉 {int(tiny.size):,} 段"
        f"（< {min_cells} 格 = 低于栅格分辨能力）→ 还原 {k:,} 格")
    return k


def connect_diagonal_rivers(terrain, value: int, log=print) -> int:
    """把"两个**不同的**河段只靠一个角相连"补成正交相连，返回补了几格。

    为什么还要这一步：`supercover` 保证的是**同一条折线内部** 4 邻接连通；`seal_river_gaps`
    管的是"两个断头离得近"。两者都管不了**段与段之间恰好只用对角相接**——两格共享一个角，
    看着相连、缩小时会散架（地图的规矩是 4 邻接）。实测残留的 17 处全属这一类
    （南京段长江 118.63E/32.11N 就是一处）。

    ⚠️ 只补**跨段**的对角：同一段内部本来就是楼梯状 4 邻接，那些角接触无害；
    一律补会把河"加粗"（实测那样会多补 5.4 万格、河格从 1.45% 涨到 2.06%）。
    """
    from scipy import ndimage
    H, W = terrain.shape
    riv = terrain == value
    st4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    lab = ndimage.label(riv, structure=st4)[0]
    water = np.isin(terrain, (T_OCEAN, T_LAKE, T_RIVER))
    add = np.zeros((H, W), dtype=bool)
    for dy, dx in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        r0, r1 = max(0, -dy), min(H, H - dy)
        c0, c1 = max(0, -dx), min(W, W - dx)
        a = riv[r0:r1, c0:c1]
        b = riv[r0 + dy:r1 + dy, c0 + dx:c1 + dx]
        la = lab[r0:r1, c0:c1]
        lb = lab[r0 + dy:r1 + dy, c0 + dx:c1 + dx]
        cross = a & b & (la != lb) & (la > 0) & (lb > 0)
        if not cross.any():
            continue
        v1 = terrain[r0 + dy:r1 + dy, c0:c1]              # 纵向桥格
        v2 = terrain[r0:r1, c0 + dx:c1 + dx]              # 横向桥格
        use1 = cross & ~water[r0 + dy:r1 + dy, c0:c1]     # 纵向桥是陆地 → 点它
        add[r0 + dy:r1 + dy, c0:c1] |= use1
        use2 = cross & ~use1 & ~water[r0:r1, c0 + dx:c1 + dx]
        add[r0:r1, c0 + dx:c1 + dx] |= use2
    k = int(add.sum())
    if k:
        terrain[add] = value
    log(f"  对角补格：跨段「只靠角相连」的河补成正交 {k:,} 格")
    return k


def name_tag(seeds) -> str:
    """保留这个名字做兼容（旧调用点），实现已挪到 地图/栅格地形数据生成器/basetag.py 与 import_editor 共用。"""
    return _bt_name_tag([s["n"] for s in seeds])


def legend_tag() -> str:
    """保留这个名字做兼容（旧调用点）；真正的清单见下面的 LEGEND_FOR_TAG。"""
    return _bt_legend_tag(LEGEND_FOR_TAG)


def write_runtime(cover, form, plot_id, dist_local, heat, moist, W, H, cell, out_dir, log=print):
    """把四层打包成**一条 32 位记录**，zlib 落成一件给游戏加载的文件。

    契约（`docs/adr/0007`）：

        位 31..28  覆盖 4      位 27..26  形态 2
        位 25..24  热量带 2    位 23..21  干湿 3
        位 20..8   地块 13     位 7..0    块区局部 8
        = 32 位整 → 一个 `Uint32Array` 装完

    **没有第七个字段**：地理区层 2026-10-09 裁掉（`docs/adr/0006`），自然地表到这里为止
    ——覆盖 × 形态 × 气候三层就是全部。真要有第四层自然属性，它得**另开一个数组**，
    不许挤占"每格一条"的这条 32 位记录。

    为什么值得落这一件：真源那几张 PNG 是给人看、给人单层改的（合计约 0.12 B/格）；而游戏
    要的是"一次随机访问拿到全部字段"。实测原始数组 zlib 压一遍只有约 1 MiB——**比那几张
    PNG 加起来还小**，解出来直接就是数组，不用 canvas、不用调色板。
    """
    import zlib
    z = np.zeros_like(plot_id)
    heat = z if heat is None else heat
    moist = z if moist is None else moist
    # v9 布局：覆盖 5 位（原本 4 位，多的那一位从**地块**里借：13 → 12 位）。
    # 实测只用了 1,602 个地块，12 位装 4,095 个、余 2,493 —— 借得起。
    rec = ((cover.astype(np.uint32) << 27) | (form.astype(np.uint32) << 25)
           | (heat.astype(np.uint32) << 23) | (moist.astype(np.uint32) << 20)
           | (plot_id.astype(np.uint32) << 8) | dist_local.astype(np.uint32))
    hdr = json.dumps({"magic": "ZLRB1", "w": int(W), "h": int(H), "cell": float(cell),
                      "layout": "cover5|form2|heat2|moist3|plot12|block8"},
                     ensure_ascii=False).encode("utf-8")
    blob = len(hdr).to_bytes(4, "little") + hdr + zlib.compress(rec.tobytes(), 9)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "底图.bin")
    with open(path, "wb") as f:
        f.write(blob)
    log(f"  运行态 底图.bin：{len(blob) / 1048576:.2f} MiB"
        f"（解出来 {rec.nbytes / 1048576:.1f} MiB 的 Uint32Array / "
        f"每格 4 B；原始压到 {len(blob) / rec.nbytes * 100:.1f}%）")
    return path


def read_runtime(path):
    """读回运行态转储 → (cover, form, heat, moist, plot_id, block_local)。给测试与游戏用。"""
    import zlib
    with open(path, "rb") as f:
        n = int.from_bytes(f.read(4), "little")
        json.loads(f.read(n).decode("utf-8"))
        rec = np.frombuffer(zlib.decompress(f.read()), np.uint32)
    return ((rec >> 27) & 0x1F, (rec >> 25) & 0x03, (rec >> 23) & 0x03, (rec >> 20) & 0x07,
            (rec >> 8) & 0x0FFF, rec & 0xFF)



# ---------------------------------------------------------------- 唐 741 州面（参考层用）

TANG_MEMBER = "v5_Hartwell/v5_0741_chin_chn_0741_p.shp"


def tang_rings(cell: float):
    """唐 741 州面 → 像素坐标的 (外环, [洞环]) 列表。

    上游是 Hartwell 的投影米制面（Xian80 GK19），先反算到 WGS84，再折回本图经度窗口
    （复用 probe_hartwell 的读取与 make_valid）。参考层用它替换汉地的现代县界：
    对着唐州顶点图改地块，比对着 1648 个县级单元的黑网有用得多。
    """
    if not os.path.exists(HARTWELL_ZIP):
        print(f"  ! 缺 {os.path.basename(HARTWELL_ZIP)}，汉地参考层只能沿用现代单元边界",
              file=sys.stderr)
        return []
    from probe_hartwell import load
    with zipfile.ZipFile(HARTWELL_ZIP) as zf:
        if TANG_MEMBER not in zf.namelist():
            print(f"  ! Hartwell 里没有 {TANG_MEMBER}", file=sys.stderr)
            return []
        _proj, wgs, _recs, _bad = load(zf, TANG_MEMBER)

    def to_px(coords):
        return [((x - LON0) / cell, (LAT1 - y) / cell) for x, y in coords]

    out = []
    for g in wgs:
        for piece in wraps(g):
            for p in getattr(piece, "geoms", [piece]):
                if p.geom_type != "Polygon":
                    continue
                out.append((to_px(p.exterior.coords), [to_px(r.coords) for r in p.interiors]))
    return out


# ---------------------------------------------------------------- 主流程



# ---------------------------------------------------------------- 烧矢量

def 烧面(ctx, feats, value, label, buf=0.0, filt=None, only_from=None, only_veg=None):
    """only_from：只允许覆盖这些**既有地形类**；only_veg：只允许覆盖这些**土地覆盖候选**。
    后者才是"形状由 LC100 定"的正解 —— 按 LC100 判形状，不管当前是裸地还是高原
    （戈壁在海拔规则下先是「高原」，若按地形类过滤就轮不到它变沙漠）。"""
    hit = 0
    for g, rec in feats:
        if filt and not filt(rec):
            continue
        if buf:
            g = g.buffer(buf)
        g = g.buffer(0)
        if g.is_empty:
            continue
        for gg in wraps(g):
            c0, c1, r0, r1 = bbox_cells(gg, ctx.参数.cell, ctx.W, ctx.H)
            if c1 <= c0 or r1 <= r0:
                continue
            xs, ys = ctx.LON[r0:r1, c0:c1].ravel(), ctx.LAT[r0:r1, c0:c1].ravel()
            from shapely import contains_xy
            m = contains_xy(gg, xs, ys).reshape(r1 - r0, c1 - c0)
            m &= ctx.陆地[r0:r1, c0:c1].astype(bool)      # 掩膜只在陆地上生效
            if only_from is not None:
                m &= np.isin(ctx.地形[r0:r1, c0:c1], np.asarray(only_from, np.uint8))
            if only_veg is not None:
                m &= np.isin(ctx.植被[r0:r1, c0:c1], np.asarray(only_veg, np.uint8))
            if m.any():
                ctx.地形[r0:r1, c0:c1][m] = value
                hit += 1
    print(f"  {label}：命中 {hit} 个面")

def 烧线(ctx, feats, value, label):
    """把**折线**按格点燃（河这类线状要素用这个，不要用上面的 burn）。

    为什么不能用 burn：`contains_xy` 只测**格心**，而 `buf=cell*0.55` 只有约一格宽，
    于是河线在栅格里是一串"只靠对角相连"的单格。实测（修之前）：全图 64,900 个
    河流格，按 **4 邻接碎成 6,834 段**，允许对角才 260 段——差 26 倍。屏幕上就是断流：
    对角相邻的两格在缩小后会被点采样整个丢掉（`render.js` 的地形层是最近邻）。

    这里改成沿折线走 **supercover**：相邻顶点之间按 ≤1 格的步长采样，
    遇到"横纵同时跨一格"的对角步就补一格正交格。于是结果**保证 4 邻接连通**，
    而宽度仍是 1 格——只把断口接上，不改河的粗细。
    """
    mask = np.zeros((ctx.H, ctx.W), dtype=bool)

    def walk(x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        n = int(np.ceil(max(abs(dx), abs(dy)))) + 1
        px = py = None
        for i in range(n + 1):
            t = i / n
            cx, cy = int(np.floor(x0 + dx * t)), int(np.floor(y0 + dy * t))
            if 0 <= cx < ctx.W and 0 <= cy < ctx.H:
                mask[cy, cx] = True
                if px is not None and abs(cx - px) == 1 and abs(cy - py) == 1:
                    mask[py, cx] = True        # 对角步补一格 → 4 邻接
            px, py = cx, cy

    nline = 0
    for g, rec in feats:
        for gg in wraps(g):
            for part in getattr(gg, "geoms", [gg]):
                if part.geom_type != "LineString":
                    continue
                co = list(part.coords)
                nline += 1
                for (ax, ay), (bx, by) in zip(co, co[1:]):
                    walk((ax - LON0) / ctx.参数.cell, (LAT1 - ay) / ctx.参数.cell,
                         (bx - LON0) / ctx.参数.cell, (LAT1 - by) / ctx.参数.cell)
    # **不裁陆地掩膜**：河口（长江江阴以下）在 NE 陆地面与 LC100 里都被判成海，
    # 一裁就把入海段抹掉。河线的两端本来就在海岸/河口，不需要这层保护；
    # 真正该防的是"整段跑到外海"，那条由 T_RIVER 与海洋收口的配合兜（见下面 ocean 收口）。
    ctx.地形[mask] = value
    print(f"  {label}：{nline} 条折线 → {int(mask.sum())} 格")
