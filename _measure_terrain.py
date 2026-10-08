# -*- coding: utf-8 -*-
"""临时测量：各候选地形类在当前数据下能落到多少格。用完即删。"""
import json, os
import numpy as np
from PIL import Image
from scipy import ndimage

R = os.path.join("地图", "地图数据", "栅格")
ter = np.asarray(Image.open(os.path.join(R, "地形编码.png")))
veg = np.load(os.path.join(R, "植被_降采样.npy"))
klim = np.load(os.path.join(R, "气候_降采样.npy"))
elev = np.load(os.path.join(R, "高程_降采样.npy")).astype(np.float32)
water = np.load(os.path.join(R, "水体_降采样.npy")).astype(np.int32)
G = json.load(open(os.path.join(R, "台账.json"), encoding="utf-8"))["grid"]
cell, lon0, lat1, H, W = G["cell"], G["lon0"], G["lat1"], G["h"], G["w"]
N = ter.size
TOC, TLA, TRI, TICE, TDES, TBARE, TPLA, TMTN, THIL, TPLN = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9
TSN, TSB, TSR, TGR, TMAR, TTUN = 10, 11, 12, 13, 14, 15
SYM = ["—","Af","Am","Aw","BWh","BWk","BSh","BSk","Csa","Csb","Csc","Cwa","Cwb","Cwc",
       "Cfa","Cfb","Cfc","Dsa","Dsb","Dsc","Dsd","Dwa","Dwb","Dwc","Dwd","Dfa","Dfb",
       "Dfc","Dfd","ET","EF"]
arid = np.isin(klim, (4, 5, 6, 7))
bw = np.isin(klim, (4, 5))
bs = np.isin(klim, (6, 7))
trop = np.isin(klim, (1, 2, 3))
st8 = np.ones((3, 3), bool)
st4 = np.array([[0,1,0],[1,1,1],[0,1,0]], bool)
oce8 = ndimage.binary_dilation(ter == TOC, st8)
riv8 = ndimage.binary_dilation(ter == TRI, st8)
ys, xs = np.mgrid[0:H, 0:W]
lat = lat1 - (ys + .5) * cell
lon = (lon0 + (xs + .5) * cell) % 360


def show(label, m, extra=""):
    n = int(m.sum())
    print(f"  {label:<46}{n:>8,} 格  {n/N*100:6.3f}%  {extra}")
    return n


def bins(label, m, k=6):
    yy, xx = np.where(m)
    if not len(yy):
        print(f"    {label}: 空")
        return
    la = (lat1 - (yy + .5) * cell)
    lo = (lon0 + (xx + .5) * cell) % 360
    key = np.floor(la / 5).astype(int) * 1000 + np.floor(lo / 5).astype(int)
    u, c = np.unique(key, return_counts=True)
    s = "，".join(f"{int(u[i]//1000)*5}N{int(u[i]%1000)*5}E {int(c[i]):,}"
                  for i in np.argsort(-c)[:k])
    print(f"    {label} 分布：{s}")


print("=== 0. 现在每一类的占比（<0.1% 的类是名存实亡） ===")
names = ["海洋","湖泊","河流","冰川","沙漠","裸地","高原","山地","丘陵","平原",
         "针叶林","阔叶林","雨林","草原","沼泽","苔原"]
c = np.bincount(ter.ravel(), minlength=16)
for i, nm in enumerate(names):
    flag = "  ← 名存实亡" if c[i]/N < 0.001 else ""
    print(f"  {i:>2} {nm:<4}{c[i]:>9,}  {c[i]/N*100:7.3f}%{flag}")

print("\n=== 1. 绿洲（干旱气候里的可耕地/植被，现在一律记平原/草原） ===")
show("干旱气候 ∧ LC100 农田 → 现为平原", arid & (veg == TPLN) & (ter == TPLN))
show("  其中紧邻河流（真绿洲/灌溉带）", arid & (veg == TPLN) & (ter == TPLN) & riv8)
show("干旱气候 ∧ LC100 草原灌丛 → 现为草原", arid & (veg == TGR) & (ter == TGR))
show("干旱气候 ∧ LC100 森林（山地绿洲）", arid & (veg >= 16) & (veg <= 19))
bins("绿洲农地", arid & (veg == TPLN) & (ter == TPLN))

print("\n=== 2. 滩涂/盐沼（LC100 90 湿地贴海）—— 能顺手解决河口绿边 ===")
show("LC100 湿地 ∧ 8邻接海洋 → 现为沼泽", (veg == TMAR) & oce8 & (ter == TMAR))
show("水体占比≥30 ∧ 贴海 ∧ 非水 → 现为陆地类（滩涂）",
     (water >= 30) & oce8 & ~np.isin(ter, (TOC, TLA, TRI)))

print("\n=== 3. 沙漠细分：柯本 BWh（热带沙漠/沙丘）vs BWk（冷沙漠/戈壁砾漠） ===")
for code in (4, 5, 6, 7):
    show(f"沙漠类里柯本={SYM[code]}", (ter == TDES) & (klim == code))
show("沙漠类里无气候数据", (ter == TDES) & (klim == 0))

print("\n=== 4. 稀树草原（热带草原，天竺/南洋/红洲） ===")
show("热带气候(Af/Am/Aw) ∧ 草原", trop & (ter == TGR))
show("  其中 Aw（干湿季分明）", (klim == 3) & (ter == TGR))
show("热带气候 ∧ LC100 农田", trop & (ter == TPLN) & (veg == TPLN))

print("\n=== 5. 裸地现状：还有多少、在哪、多高 ===")
bare = ter == TBARE
show("裸地", bare)
if bare.any():
    e = elev[bare]
    print(f"    海拔 p10/p50/p90 = {np.percentile(e,10):.0f}/{np.percentile(e,50):.0f}/"
          f"{np.percentile(e,90):.0f} m")
    bins("裸地", bare)

print("\n=== 6. 盐湖（干旱气候里的湖） ===")
show("湖泊 ∧ 干旱气候", (ter == TLA) & arid)

print("\n=== 7. 混交林（LC100 115/116/125/126，现在被权重判成针/阔/雨） ===")
show("候选层=混交系(19)", veg == 19)
show("  其中现在成了针叶林", (veg == 19) & (ter == TSN))
show("  其中现在成了阔叶林", (veg == 19) & (ter == TSB))

print("\n=== 8. 苔原：现在 NE 手绘面 vs 柯本 ET 全量 ===")
show("苔原（NE 面，现状）", ter == TTUN)
show("柯本 ET(29) 落在陆地上的格", (klim == 29) & (ter != TOC))

print("\n=== 9. 冰川 / 冰盖 ===")
show("冰川", ter == TICE)
bins("冰川", ter == TICE, 4)
