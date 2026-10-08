# -*- coding: utf-8 -*-
"""临时：把三层栅格解成 typed array，实测运行态字节账 + 试各种打包到底省不省。用完即删。"""
import gzip, json, os, time, zlib
import numpy as np
from PIL import Image

R = os.path.join("地图", "地图数据", "栅格")
t0 = time.time()
ter = np.asarray(Image.open(os.path.join(R, "地形编码.png")))          # uint8
plot = np.asarray(Image.open(os.path.join(R, "地块编码.png")))          # RGB
dist = np.asarray(Image.open(os.path.join(R, "分区编码.png")))
H, W = ter.shape
N = H * W
print(f"栅格 {W}×{H} = {N:,} 格；解三张 PNG 用了 {time.time()-t0:.1f} s（一次，加载时算一次）")

pid = plot[..., 0].astype(np.uint16) | (plot[..., 1].astype(np.uint16) << 8)
did = dist[..., 0].astype(np.uint16) | (dist[..., 1].astype(np.uint16) << 8)
print(f"地块编号 max {int(pid.max()):,}（需要 {int(pid.max()).bit_length()} 位）"
      f"；块区编号 max {int(did.max()):,}（需要 {int(did.max()).bit_length()} 位）"
      f"；地形类 max {int(ter.max())}（需要 {int(ter.max()).bit_length()} 位）")

print("\n=== A. 磁盘：现在这三张 PNG ===")
tot = 0
for f in ("地形编码.png", "地块编码.png", "分区编码.png"):
    s = os.path.getsize(os.path.join(R, f))
    tot += s
    print(f"  {f:<16}{s:>9,} B   {s/N:.4f} B/格")
print(f"  {'合计':<16}{tot:>9,} B   {tot/N:.4f} B/格")

print("\n=== B. 内存：typed array（每种字段一个原生数组）===")
mem = 0
for nm, a in (("地形 uint8", ter), ("地块 uint16", pid), ("块区 uint16", did)):
    mem += a.nbytes
    print(f"  {nm:<14}{a.nbytes:>12,} B   {a.nbytes/N:.0f} B/格")
print(f"  {'合计':<14}{mem:>12,} B = {mem/1048576:.1f} MB   {mem/N:.0f} B/格")
print(f"  对照：若三层都留在 canvas 的 RGBA 像素里 = {4*3*N/1048576:.0f} MB（4 B/格 × 3 层）")

print("\n=== C. 打包到底省不省？（关键：对齐）===")
for nm, bits in (("地形 4 位 + 地块 16 + 块区 16", 36), ("地形 5 + 地块 16 + 块区 16", 37),
                 ("地形 4 + 地块 15 + 块区 15", 34), ("地形 4 + 地块 14 + 块区 14", 32),
                 ("地形 5 + 地块 14 + 块区 13", 32), ("再加 地理区 8 位（5+16+16+8）", 45)):
    print(f"  {nm:<32}{bits:>3} 位 → { -(-bits//8)} B/格 = {-(-bits//8)*N/1048576:>6.1f} MB")

print("\n=== D. 压缩：把这 5 B/格的原始数组压一遍 ===")
raw = ter.tobytes() + pid.tobytes() + did.tobytes()
print(f"  原始 {len(raw):,} B = {len(raw)/1048576:.1f} MB")
for lvl in (6, 9):
    c = zlib.compress(raw, lvl)
    print(f"  zlib -{lvl}: {len(c):,} B = {len(c)/1048576:.1f} MB（{len(c)/N:.3f} B/格，"
          f"压剩 {len(c)/len(raw)*100:.1f}%）")
print(f"  ⚠ 对照：三张 PNG 合计 {tot:,} B —— 比压过的原始数组还小 {len(c)/tot:.1f} 倍，"
      f"因为 PNG 有行滤波 + 逐层调色板化")
print("\n=== E. 只解地形（游戏若按需加载）===")
print(f"  地形 1 B/格 = {N/1048576:.1f} MB；三张 PNG 里地形那张只有 "
      f"{os.path.getsize(os.path.join(R,'地形编码.png')):,} B")
print(f"\n总耗时 {time.time()-t0:.1f} s")
