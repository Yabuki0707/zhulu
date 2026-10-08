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


# ================================================================ 两轴：热量带 × 干湿
# v1 这一层只是**构建期中间层**（判沙漠用的 .npy）；v2 升格为**产品层**
# （`栅格/气候编码.png`），因为地形表把气候那一半交还给了它：沙漠、苔原、雨林/针叶/阔叶
# 全不再存储，改由「覆盖 × 气候」派生（见 docs/adr/0006）。
#
# 为什么不直接存柯本 30 类：柯本是为**植被分类**设计的，符号玩家读不懂；游戏要吃的是
# 两个量——**热量**（几熟、物产、疫病）与**干湿**（农耕/游牧、商路）。柯本可以拆成这两轴，
# 但 **B 组必须按纬度补一刀**：B 组是按*水分*定义的，实测 BWh 有 **59.1% 在回归线以外**
# （撒哈拉北缘、塔尔沙漠、阿拉伯北缘），一律算「热带干旱」就错了一半。
# （BWk/BSk 冷沙漠 99.9% 在回归线外，本来就干净，照柯本的 k 归温带即可。）
#
# 两轴只要 5 位：热量带 2 位 + 干湿 3 位。**寒带不占热量带的取值**——它由干湿的 0 码表示。
# 柯本 ET/EF 共 195,787 格（这些是真的极地）。
# 读取规则：**先读干湿；=0 则整条气候码读作「寒带」，热量带那 2 位是 don't-care。**
#
# ⚠️ 0 这个码因此有两个来源：柯本的 ET/EF，以及"整格无气候数据"。后者**必须在管线里补掉**
# （`fill_land_nodata`）——实测 11,352 格里阿拉斯加、波罗的海、堪察加都有，纬度最低到
# 9.4°N；不补就会把阿拉斯加 58°N 读成极地。`build_raster` 的断言第 4 条守着这件事。
HEAT_TROP, HEAT_SUBTROP, HEAT_TEMP, HEAT_SUBARC = range(4)
HEAT_NAMES = ["热带", "亚热带", "温带", "亚寒带"]      # 寒带不在这里，见 MOIST_NAMES[0]
MOIST_NAMES = ["寒带", "干旱", "半干旱", "冬干", "冬雨", "夏雨", "季风", "常湿"]
N_HEAT, N_MOIST = len(HEAT_NAMES), len(MOIST_NAMES)
SUBARCTIC_LAT = 23.5                     # B 组按此纬度切成「热」与「冷」两半

_HEAT = {}
for _c in (1, 2, 3, 4, 6):               # Af/Am/Aw ＋ BWh/BSh（热的 B 组）
    _HEAT[_c] = HEAT_TROP
for _c in range(8, 17):                  # Csa … Cfc
    _HEAT[_c] = HEAT_SUBTROP
for _c in (17, 18, 21, 22, 25, 26):      # Dsa/Dsb/Dwa/Dwb/Dfa/Dfb（温和的 D 组）
    _HEAT[_c] = HEAT_TEMP
for _c in (5, 7):                        # BWk/BSk（冷的 B 组）
    _HEAT[_c] = HEAT_TEMP
for _c in (19, 20, 23, 24, 27, 28):      # Dsc/Dsd/Dwc/Dwd/Dfc/Dfd（亚寒带）
    _HEAT[_c] = HEAT_SUBARC

_MOIST = {4: 1, 5: 1,                    # 干旱
          6: 2, 7: 2,                    # 半干旱
          1: 7, 2: 6, 3: 3}              # Af 常湿 / Am 季风 / Aw 冬干（稀树草原）
for _c in (8, 9, 10, 17, 18, 19, 20):    # 带 s = 冬雨（地中海型）
    _MOIST[_c] = 4
for _c in (11, 12, 13, 21, 22, 23, 24):  # 带 w = 夏雨（季风型）
    _MOIST[_c] = 5
for _c in (14, 15, 16, 25, 26, 27, 28):  # 带 f = 常湿
    _MOIST[_c] = 7
for _c in (29, 30):                      # ET/EF → 干湿码 0，即「寒带」
    _MOIST[_c] = 0

HEAT_BY_CODE = np.zeros(N_CODE, np.uint8)
MOIST_BY_CODE = np.zeros(N_CODE, np.uint8)
for _c, _h in _HEAT.items():
    HEAT_BY_CODE[_c] = _h
for _c, _m in _MOIST.items():
    MOIST_BY_CODE[_c] = _m


def axes(klim: np.ndarray, lat: np.ndarray):
    """柯本类栅格 → (heat, moist) 两张 uint8：每格 0..3 与 0..7。

    · **B 组按纬度补一刀**：BWh/BSh 在回归线内算热带，线外算亚热带；BWk/BSk 照柯本的 k
      归温带（99.9% 在回归线外）。
    · **调用方必须先跑 `fill_land_nodata`**——否则"整格无气候数据"（0）会混进 `moist = 0`，
      和柯本的 ET/EF 一起被读成「寒带」，把阿拉斯加 58°N 显示成极地。
    """
    heat = HEAT_BY_CODE[klim].copy()
    moist = MOIST_BY_CODE[klim].copy()
    hot = np.abs(lat) <= SUBARCTIC_LAT
    bw_bs = np.isin(klim, (4, 6))                    # 只有"热的 B 组"要按纬度再分
    heat = np.where(bw_bs & ~hot, np.uint8(HEAT_SUBTROP), heat)
    return heat.astype(np.uint8), moist.astype(np.uint8)


def pack(heat: np.ndarray, moist: np.ndarray) -> np.ndarray:
    """两轴 → 一个字节：`码 = 热量带 × 8 + 干湿`（0..31）。写 8 位灰度 PNG 用这个。"""
    return (heat.astype(np.uint16) * N_MOIST + moist.astype(np.uint16)).astype(np.uint8)


def unpack(code: np.ndarray):
    """一个字节 → (heat, moist)。读取方（编辑器 / 游戏）用这个。"""
    code = code.astype(np.uint8)
    return (code // N_MOIST).astype(np.uint8), (code % N_MOIST).astype(np.uint8)


def fill_land_nodata(klim: np.ndarray, land: np.ndarray, log=print):
    """把**陆地上**"整格无气候数据"的洞补上（取最近的有效气候类），返回 (新层, 补了几格)。

    为什么必须补：柯本把**水体与冰盖** mask 成 nodata，于是"整格都在湖里/冰上"的格子判不出
    气候类；而 NE 陆地掩膜说那是陆（小岛、湖岸、冰川前缘、三角洲）。实测 11,352 格——
    它们**不在极地**：阿拉斯加一带 3,456 格（200°E 那个 5° 箱）、波罗的海 2,700 余格、
    堪察加与白令海沿岸，纬度中位 69.9°、最低 9.4°N。

    ⚠️ 这批格若不补，就会落进干湿码 0 —— 而 0 是「寒带」。**阿拉斯加 58°N 会被显示成极地**。
    这正是 `build_raster.assert_contract` 第 4 条要拦的东西：它第一次跑就把这条**拦下来了**
    （原先 `polar_nodata` 的注释里写着"实测全在 81.7–81.8°N"，那是只看纬度最高的 3 格
    得出的错话——断言把这条错话证伪了）。

    补法用最近邻而非邻域多数：洞都很小（湖心、岸边），最近的有效格就是它本该有的气候带。
    """
    from scipy import ndimage
    k = klim.copy()
    hole = np.asarray(land).astype(bool) & (k == 0)
    n = int(hole.sum())
    if not n:
        return k, 0
    # ⚠️ 源掩膜必须是 `k == 0`（无气候类的格：陆地洞 **加上海洋**），不能是 `~hole`。
    # 用 `~hole` 会把"洞旁边那格海"当成有效源——海也是 klim==0，于是沿海的洞被填回 0，
    # 补完还剩 6,814 格（第一次就是这么错的）。
    src = (k == 0)
    _d, idx = ndimage.distance_transform_edt(src, return_indices=True)
    k[hole] = k[idx[0][hole], idx[1][hole]]
    log(f"  气候补洞：陆地上 {n:,} 格无气候类（柯本把水体/冰盖 mask 成 nodata，"
        f"而 NE 说那是陆）→ 取最近**有气候类**的格补上")
    return k, n


def polar_nodata(klim: np.ndarray, lat: np.ndarray, land: np.ndarray):
    """→ (格数, 最小 |纬度|)：陆地 ∧ klim==0 的统计，给管线断言用。

    补洞（`fill_land_nodata`）之后这个数应当是 0；**不是 0 就说明还有洞没补**，
    而洞会被静默读成「寒带」。它是断言第 4 条的判据。
    """
    z = np.asarray(land).astype(bool) & (klim == 0)
    n = int(z.sum())
    if not n:
        return 0, None
    return n, float(np.abs(lat)[z].min())


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
