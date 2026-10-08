# -*- coding: utf-8 -*-
"""临时预览：沿海/岛屿在三种改法下会变成什么样。产出 PNG 到 地图/_预览_沿海改法/。

不改 tools/ 里任何东西：这里把"烧河之前"的地形从缓存的 npy 层重建出来（并自检
与 地形编码.png 在非河格上一致），再把三种河规则分别叠上去渲染。
"""
import json, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))
os.chdir(HERE)

import terrain as TR
import climate as CL
import build_raster as BR
from mapdata import RASTER

R = RASTER
ter = np.asarray(Image.open(os.path.join(R, "地形编码.png")))
water = np.load(os.path.join(R, "水体_降采样.npy")).astype(np.int32)
veg = np.load(os.path.join(R, "植被_降采样.npy"))
elev = np.load(os.path.join(R, "高程_降采样.npy")).astype(np.float32)
relief = np.load(os.path.join(R, "起伏_降采样.npy")).astype(np.float32)
klim = np.load(os.path.join(R, "气候_降采样.npy"))
G = json.load(open(os.path.join(R, "台账.json"), encoding="utf-8"))["grid"]
cell, lon0, lat1, H, W = G["cell"], G["lon0"], G["lat1"], G["h"], G["w"]
TOC, TLA, TRI = 0, 1, 2
lon_c = lon0 + (np.arange(W) + .5) * cell
lat_c = lat1 - (np.arange(H) + .5) * cell
LON, LAT = np.meshgrid(lon_c, lat_c)
above80 = (lat_c > 80.0)[:, None]

print("① 重建陆地掩膜（NE 陆地 ∪ 湖泊 ∪ 冰川区）…")
geoms = []
for path, lab in ((BR.NE_LAND, "陆地"), (BR.NE_LAKES, "湖泊"), (BR.NE_GLACIATED, "冰川区")):
    feats = BR.ne_features(path)
    for g, _ in feats:
        g = g.buffer(0)
        if g.is_empty:
            continue
        geoms.extend(BR.wraps(g))
land = TR.rasterize_union(LON, LAT, lon0, lat1, cell, geoms)
print(f"   陆地掩膜 {int(land.sum()):,} 格")

print("② 重建'烧河之前'的地形 …")
pre = TR.classify(elev, relief, veg, land, LAT)
dry = (np.isin(klim, CL.ARID) & (veg == TR.T_BARE) & land.astype(bool)
       & (elev < BR.DESERT_MAX_ELEV))
pre[dry] = TR.T_DESERT
REG = BR.ne_features(BR.NE_REGIONS)


def burn(feats, value, filt=None, only_veg=None):
    for g, rec in feats:
        if filt and not filt(rec):
            continue
        g = g.buffer(0)
        if g.is_empty:
            continue
        for gg in BR.wraps(g):
            c0, c1, r0, r1 = BR.bbox_cells(gg, cell, W, H)
            if c1 <= c0 or r1 <= r0:
                continue
            from shapely import contains_xy
            xs, ys = LON[r0:r1, c0:c1].ravel(), LAT[r0:r1, c0:c1].ravel()
            m = contains_xy(gg, xs, ys).reshape(r1 - r0, c1 - c0)
            m &= land[r0:r1, c0:c1].astype(bool)
            if only_veg is not None:
                m &= np.isin(veg[r0:r1, c0:c1], np.asarray(only_veg, np.uint8))
            if m.any():
                pre[r0:r1, c0:c1][m] = value


burn(REG, TR.T_TUNDRA, filt=lambda r: r.get("FEATURECLA") == "Tundra",
     only_veg=(TR.T_BARE, TR.T_GRASS, TR.T_TUNDRA))
burn(BR.ne_features(BR.NE_GLACIATED), TR.T_ICE)
burn(BR.ne_features(BR.NE_LAKES), TR.T_LAKE)
was_lake = pre == TR.T_LAKE
# 收口（与管线同序）
pre[(land == 0) & (pre != TR.T_RIVER)] = TOC
inland = (pre == TOC) & (veg == TR.T_LAKE)
pre[inland] = TLA

riv_cur = ter == TRI
fill = (water >= 30) & riv_cur
line = riv_cur & ~fill
agree = np.mean(pre[~riv_cur] == ter[~riv_cur])
print(f"   自检：非河格上重建 vs 实际 一致率 {agree*100:.3f}%（应≈100%）")

st4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)
st8 = np.ones((3, 3), bool)
base = np.where(riv_cur, pre, ter)
V0 = ter.copy()
# V2 = 只修河（A+B）：砍掉 LC100 判开阔海的补面格 + 80N 以北的补面格
keep_fill = fill & (veg != TOC) & ~above80
V2 = base.copy()
V2[line | keep_fill] = TRI
# V1 = 推荐（A+B+正解）：先把"掩膜说陆、LC100 说过半是海"的格判成水，再烧河
sea_maj = land.astype(bool) & (veg == TOC) & ~above80      # 80N 以北 LC100 无数据，不许用
oce4 = ndimage.binary_dilation(ter == TOC, st4)
V1 = base.copy()
V1[sea_maj & oce4] = TOC
V1[sea_maj & ~oce4] = TLA
V1[line | keep_fill] = TRI

print(f"\n   「掩膜说陆、LC100 说过半是海」的格（80N 以北不计）：{int(sea_maj.sum()):,}")

for nm, V in (("现状", V0), ("V2 只修河", V2), ("V1 推荐", V1)):
    c = np.bincount(V.ravel(), minlength=16)
    print(f"   {nm:<10} 河 {c[2]:>7,}  湖 {c[1]:>7,}  海 {c[0]:>9,}  "
          f"陆地类 {int(c[3:].sum()):>9,}")

# 岛屿是否整块消失
lab, n = ndimage.label(land.astype(bool), st8)
sz = np.bincount(lab.ravel(), minlength=n + 1)
print(f"\n   陆地连通块 {n:,}（含大陆）")


def vanished(V):
    alive = np.bincount(lab.ravel(), weights=(V != TOC).astype(np.float32).ravel(),
                        minlength=n + 1)
    return np.where((sz > 0) & (alive < 0.5))[0]


for nm, V in (("现状", V0), ("V2", V2), ("V1", V1)):
    idx = vanished(V)
    idx = idx[idx > 0]
    if not len(idx):
        print(f"   整块变水的岛：{nm} 0 块")
        continue
    s = sz[idx]
    ys, xs = np.where(np.isin(lab, idx))
    print(f"   整块变水的岛：{nm} {len(idx):,} 块 / 共 {int(s.sum()):,} 格"
          f"（1 格 {int((s == 1).sum()):,} 块，2–4 格 {int(((s >= 2) & (s <= 4)).sum()):,}，"
          f"≥5 格 {int((s >= 5).sum()):,}）；分布 {lat_c[ys.min()]:.0f}–{lat_c[ys.max()]:.0f}N")
    for i in idx[np.argsort(-sz[idx])][:6]:
        yy, xx = np.where(lab == i)
        print(f"      {int(sz[i]):>4} 格 @ {lat_c[int(yy.mean())]:6.2f}N "
              f"{lon_c[int(xx.mean())] % 360:7.2f}E")

PAL = [(0x7f,0xa6,0xc4),(0x6e,0xa8,0xd8),(0x5b,0x8f,0xc7),(0xee,0xf4,0xf8),
       (0xe3,0xcf,0x9a),(0xcd,0xbb,0x96),(0xc2,0xab,0x7e),(0xa9,0x8a,0x62),
       (0xc8,0xb9,0x8f),(0xcf,0xe0,0xa8),(0x4f,0x7a,0x4a),(0x6f,0x9c,0x4a),
       (0x2f,0x6b,0x3a),(0xb9,0xc6,0x8a),(0x8f,0xa9,0x8a),(0xb8,0xc4,0xb0)]
lut = np.zeros((16, 3), np.uint8)
for i, c in enumerate(PAL):
    lut[i] = c

OUT = os.path.join(HERE, "地图", "_预览_沿海改法")
os.makedirs(OUT, exist_ok=True)
WIN = [
    ("长江口—杭州湾—舟山", 119.2, 123.4, 29.2, 33.0),
    ("菲律宾中部群岛",      121.4, 126.4,  9.0, 13.0),
    ("日本濑户内—九州",     129.0, 135.0, 31.0, 35.0),
    ("北地群岛 80N",        88.0, 106.0, 78.0, 81.5),
    ("勒拿三角洲（真三角洲）", 122.0, 130.0, 71.0, 74.0),
    ("西西伯利亚沼泽—鄂毕", 66.0, 76.0, 58.0, 62.0),
]
for name, lo0, lo1, la0, la1 in WIN:
    c0, c1 = int((lo0 - lon0) / cell), int((lo1 - lon0) / cell)
    r0, r1 = int((lat1 - la1) / cell), int((lat1 - la0) / cell)
    c0, c1 = max(0, c0), min(W, c1)
    r0, r1 = max(0, r0), min(H, r1)
    w, h = c1 - c0, r1 - r0
    k = max(1, min(6, 520 // max(w, 1)))
    panels = []
    for V in (V0, V2, V1):
        sub = V[r0:r1, c0:c1]
        img = Image.fromarray(lut[sub], "RGB").resize((w * k, h * k), Image.NEAREST)
        panels.append(np.asarray(img))
    gap = np.full((h * k, 3, 3), 255, np.uint8)
    strip = np.concatenate([panels[0], gap, panels[1], gap, panels[2]], axis=1)
    p = os.path.join(OUT, f"{name}（左现状 中只修河 右推荐）.png")
    Image.fromarray(strip).save(p)
    n0 = int((V0[r0:r1, c0:c1] == TRI).sum())
    n1 = int((V1[r0:r1, c0:c1] == TRI).sum())
    o0 = int((V0[r0:r1, c0:c1] == TOC).sum())
    o1 = int((V1[r0:r1, c0:c1] == TOC).sum())
    print(f"   {name:<22} {w}×{h} 格  河 {n0:,}→{n1:,}  海 {o0:,}→{o1:,}  →{p}")
print("完成")
