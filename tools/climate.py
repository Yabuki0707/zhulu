# -*- coding: utf-8 -*-
"""柯本气候分类（Beck et al. 2023，1 km）→ 栅格格心的**主导气候类**。

为什么要有这一层：地形表里「沙漠」与「裸地」在 Copernicus LC100 里是**同一个事实**
（都是「无植被～稀疏植被」= 60）。谁来定"哪一片算沙漠"？以前是 Natural Earth 那几个
**手绘沙漠面**（平均 76 个顶点、戈壁整个只有 100 个顶点），于是沙漠的每条外轮廓都是 NE
的边——实测「沙漠边界外侧 25.5% 仍是 LC100 裸地」，最长一段 207 km 笔直
（见 `设计笔记03` §14.11）。NE 那层面必须彻底不要，换成**气候**这一事实来源。

数据：Beck, H. E. et al. (2023) High-resolution (1 km) Köppen-Geiger maps for 1901–2099
based on constrained CMIP6 projections, *Scientific Data* 10, 724. 许可 **CC BY 4.0**。
本模块只读**现值期**（1991–2020）那幅。

编码（原文 `legend.txt`，本模块原样照抄，不做增删）：

    1 Af  2 Am  3 Aw                                    热带
    4 BWh 5 BWk  沙漠   6 BSh 7 BSk  草原                干旱（B）
    8-16 C*                                             温带
    17-28 D*                                            冷
    29 ET  苔原   30 EF  冰原                             极地

「干旱」= **BWh/BWk/BSh/BSk**（`ARID`）—— 与 `设计笔记03` §14.11 写定的判据一致：
沙漠 = `LC100 裸地 ∧ 干旱气候`。

用法：
    from climate import koppen_from_zip, ARID
    k = koppen_from_zip(W, H, cell, LON0, LAT1, KOPPEN_ZIP, KOPPEN_MEMBER, cache_path)
    arid = np.isin(k, ARID)

缓存：算出的是 (H, W) uint8 的**气候类栅格**（不是布尔掩膜），所以将来要按气候带再细分
草原/苔原时，改规则不必重读 TIFF（与 `植被_降采样.npy` 同一思路）。
"""
from __future__ import annotations

import io
import json
import os
import zipfile

import numpy as np

# ---------------------------------------------------------------- 数据位置与编码
KOPPEN_ZIP_NAME = "koppen_geiger_tif.zip"
# 现值期（1991–2020）1 km。同包里还有：0p1（0.1°）、另外三个历史期与六个 SSP 的未来期
KOPPEN_MEMBER = "1991_2020/koppen_geiger_0p00833333.tif"
KOPPEN_ENCODING = "beck2023-v3"          # 换编码就往缓存旁写这个标记，对不上就不复用

KOPPEN_SCALE = 1.0 / 120.0               # 0.00833333° ≈ 1 km
KOPPEN_TOP_LAT = 90.0                    # 首行格心纬度（自北向南）
KOPPEN_LEFT_LON = -180.0                 # 首列格心经度（自西向东）
KOPPEN_NODATA = 0                        # GDAL_NODATA；0 = 无数据（海洋）
N_CODE = 31                              # 1…30 有效，0 = 无数据

SYMBOLS = ["—", "Af", "Am", "Aw", "BWh", "BWk", "BSh", "BSk",
           "Csa", "Csb", "Csc", "Cwa", "Cwb", "Cwc", "Cfa", "Cfb", "Cfc",
           "Dsa", "Dsb", "Dsc", "Dsd", "Dwa", "Dwb", "Dwc", "Dwd",
           "Dfa", "Dfb", "Dfc", "Dfd", "ET", "EF"]

ARID = (4, 5, 6, 7)                      # BWh BWk BSh BSk —— 「干旱气候」
DESERT = (4, 5)                          # BWh BWk       —— 沙漠气候（BS 是草原）
STEPPE = (6, 7)                          # BSh BSk
TUNDRA = (29,)                           # ET


# ---------------------------------------------------------------- TIFF 瓦片流式读
class _KoppenStrip:
    """柯本 TIFF（LZW、256×256 分块）按**瓦片行**流式解码，只解本图经度窗口内的列。

    与 `terrain._TifStrip` 同思路（那里解 Deflate），只是解码器换成 imagecodecs 的 LZW。
    窗口跨日界线，所以是"两段列"：A = lon0…180°，B = -180°…lon1-360°。
    """

    def __init__(self, buf: io.BytesIO, lon0: float, lon1: float, log=print):
        import tifffile
        self.tf = tifffile.TiffFile(buf)
        pg = self.pg = self.tf.pages[0]
        assert pg.shape == (21600, 43200) and pg.dtype == np.uint8, "柯本栅格形状不符"
        assert pg.is_tiled, "柯本栅格期望分块存储"
        self.tw, self.th = pg.tilewidth, pg.tilelength
        self.ntc = (pg.imagewidth + self.tw - 1) // self.tw
        self.width_px = pg.imagewidth
        # 列窗口（像素）
        cA0 = int(round((lon0 - KOPPEN_LEFT_LON) / KOPPEN_SCALE))
        cA1 = self.width_px
        cB1 = int(round((lon1 - 360.0 - KOPPEN_LEFT_LON) / KOPPEN_SCALE))
        self.colA = (cA0, cA1)
        self.cB1 = cB1
        self.width = (cA1 - cA0) + cB1
        self._fh = buf
        self._row = None
        self._cache = None
        log(f"  读柯本气候（LZW 分块流式，窗口 {self.width} 列）")

    def _tile(self, iy: int, ix: int) -> np.ndarray:
        import imagecodecs
        i = iy * self.ntc + ix
        self._fh.seek(self.pg.dataoffsets[i])
        raw = self._fh.read(self.pg.databytecounts[i])
        a = np.frombuffer(imagecodecs.lzw_decode(raw), np.uint8)
        # 非整块（右/下边缘）解出来会短，按实际长度推列数
        return a.reshape(-1, self.tw)

    def strip(self, tile_row: int) -> np.ndarray:
        """整条瓦片行（只含本图需要的列），形状 (th, width)。按 tile_row 缓存。"""
        if tile_row != self._row:
            cA0, cA1 = self.colA
            x0 = cA0 // self.tw
            x1 = (cA1 + self.tw - 1) // self.tw
            x2 = (self.cB1 + self.tw - 1) // self.tw
            skip = cA0 - x0 * self.tw                    # 首块切掉不足一块的前缀
            head = np.concatenate([self._tile(tile_row, ix) for ix in range(x0, x1)], axis=1)
            head = head[:, skip:skip + (cA1 - cA0)]
            head = head[:, :self.width_px - cA0]          # 末块的多余列
            if x2:
                tail = np.concatenate([self._tile(tile_row, ix) for ix in range(0, x2)], axis=1)
                tail = tail[:, :self.cB1]
                self._cache = np.concatenate([head, tail], axis=1)
            else:
                self._cache = head
            self._row = tile_row
        return self._cache


def _col_index(lon_s: np.ndarray, strip: _KoppenStrip) -> np.ndarray:
    """格心经度 → strip 内的列下标（跨日界线时第二段要平移。经度已折回连续 >180）。"""
    cols = np.round((lon_s - KOPPEN_LEFT_LON) / KOPPEN_SCALE).astype(np.int64)
    cA0, cA1 = strip.colA
    idx = np.where(lon_s <= 180.0, cols - cA0, (cA1 - cA0) + cols)
    return np.clip(idx, 0, strip.width - 1)


def koppen_from_zip(W, H, cell, lon0, lat1, zip_path, member=KOPPEN_MEMBER,
                    cache_path=None, rs=8, cs=8, log=print, reuse_cache=False) -> np.ndarray:
    """→ (H, W) uint8：每格**主导**柯本类（0 = 窗口内无有效像元）。

    主导 = 格内 rs × cs 个样本里出现最多的那一类（同 `terrain._dominant_from_parts` 的口径）。
    1 km 数据在 0.0625° 格里有约 7.5 × 7.5 = 56 个像元，rs = cs = 8 已略过采样，够用。
    """
    if reuse_cache and cache_path and cache_ok(cache_path):
        try:
            a = np.load(cache_path)
            if a.shape == (H, W):
                log(f"  气候层读缓存 {os.path.basename(cache_path)}")
                return a.astype(np.uint8)
        except Exception:                                                     # noqa: BLE001
            pass
    if not os.path.exists(zip_path):
        log(f"  ! 缺 {os.path.basename(zip_path)}，气候层跳过")
        return np.zeros((H, W), np.uint8)

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if member not in names:
            log(f"  ! {os.path.basename(zip_path)} 里没有 {member}，气候层跳过")
            return np.zeros((H, W), np.uint8)
        buf = io.BytesIO(z.read(member))

    lon1 = lon0 + W * cell
    strip = _KoppenStrip(buf, lon0, lon1, log=log)

    x = np.arange(W)
    lon_s = lon0 + (x[:, None] + (np.arange(cs)[None, :] + 0.5) / cs) * cell     # (W, cs)
    colidx = _col_index(lon_s, strip)                                            # (W, cs)
    cells_idx = np.repeat(x, cs).astype(np.int64)                                # (W*cs,)

    out = np.zeros((H, W), np.uint8)
    for y in range(H):
        lat_s = lat1 - (y + (np.arange(rs) + 0.5) / rs) * cell
        rr = np.clip(np.round((KOPPEN_TOP_LAT - lat_s) / KOPPEN_SCALE).astype(np.int64),
                     0, 21600 - 1)
        cnt = np.zeros(W * N_CODE, np.int32)
        for r in np.unique(rr):
            row = strip.strip(int(r) // strip.th)[int(r) % strip.th]
            vals = row[colidx]                                                   # (W, cs)
            cnt += np.bincount(cells_idx * N_CODE + vals.ravel().astype(np.int64),
                               minlength=W * N_CODE)
        # 主导类**只在有效类之间**取（0 = 无数据不参与）。否则半海半陆的沿岸格会
        # 平票给 0，把陆地气候整个丢掉——实测新加坡那格 33 陆 : 23 海，
        # 8×8 采样打成 32:32，argmax 取到 0。0 的语义要留给"整格无气候数据"。
        grid = cnt.reshape(W, N_CODE)
        tot = grid[:, 1:].sum(axis=1)
        grid[:, 0] = 0
        best = grid.argmax(axis=1).astype(np.uint8)
        out[y] = np.where(tot > 0, best, 0)
        if log and (y % 200 == 0 or y == H - 1):
            log(f"    气候 {y + 1}/{H} 行")

    if cache_path:
        try:
            np.save(cache_path, out)
            with open(cache_path + ".tag", "w", encoding="utf-8") as f:
                json.dump({"encoding": KOPPEN_ENCODING, "member": member,
                           "source": "Beck et al. 2023, CC BY 4.0"}, f)
            log(f"  气候层已缓存 {os.path.basename(cache_path)}"
                f"（{out.nbytes / 1048576:.1f} MB）")
        except Exception as e:                                            # noqa: BLE001
            log(f"  ! 气候层缓存失败：{e}")
    return out


def cache_ok(cache_path) -> bool:
    """缓存是不是本模块这一版编码产出的（对不上就重算，别静默复用）。"""
    if not os.path.exists(cache_path):
        return False
    tag = cache_path + ".tag"
    if not os.path.exists(tag):
        return False
    try:
        with open(tag, encoding="utf-8") as f:
            return json.load(f).get("encoding") == KOPPEN_ENCODING
    except Exception:                                                     # noqa: BLE001
        return False


def summarise(k: np.ndarray, share: int = 12) -> str:
    """一句话摘要：占比最高的若干气候类（码 + 符号 + 占比）。分母不含"无气候数据"。"""
    cnt = np.bincount(k.ravel(), minlength=N_CODE)
    cnt[0] = 0
    tot = int(cnt.sum())
    if not tot:
        return "（空）"
    order = np.argsort(cnt)[::-1]
    parts = []
    for c in order:
        if not cnt[c]:
            break
        parts.append(f"{SYMBOLS[c]} {cnt[c] / tot * 100:.1f}%")
        if len(parts) >= share:
            break
    return "，".join(parts)
