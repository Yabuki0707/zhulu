# -*- coding: utf-8 -*-
"""地形分类（**覆盖** × **形态**）：高程 + 起伏 + Copernicus LC100 土地覆盖 + Natural Earth 掩膜。

    from terrain import LEGEND, read_elevation, veg_from_landcover, landform, classify

真源口径（每一条都是踩过坑之后才这么定的）：

  陆地 = **Natural Earth 10m 陆地 ∪ 湖泊 ∪ 冰川区**（格心命中，`rasterize_union`）
         · 不用「ETOPO > 0」：吐鲁番（−154 m）、里海（−28 m）、死海（−430 m）会被判成海；
         · 不用「plot_id > 0」：欧/非/美洲整片（撒哈拉、刚果、东欧）会被判成海。
         海洋 = 这个掩膜的补集，**全管线只有这一处口径**（地块层也按它裁）。
  高程 = ETOPO 2022 60s（1 弧分）在窗口内按格做面积平均（BOX）。
  起伏 = 同一窗口按格取 max−min（0.0625° 的格 ≈ 6.9 × 5.3 km 的相对高差）——
         分丘陵 / 山地 / 高原全靠它，只看海拔分不出来（青藏 4500 m 是"面"，
         喜马拉雅 4500 m 是"脊"，四川盆地 400 m 且平坦是"平原"）。
  植被 = Copernicus LC100 离散分类（80 N–60 S，100 m），每格取 8 × 3 = 24 个样本。
         数据源是 `全球土地覆盖_100米.tif`（Deflate 分块，只解用得到的瓦片）。
         那份 48.8 GB 的裸数组（`原始数据/高程与地表/numpy`）已确认是**残件**并已删除：
         它在 lat −18° 以南整片是 0（澳洲、新西兰、南部非洲全废），而字节数恰好等于
         141120 × 362880。若将来放入一份新的裸数组，`validate_raw` 会先拿 6 个已知地点
         与 TIFF 逐点比对，对不上就不用，自动走 TIFF 流式解瓦片。

### 森林怎么定：**郁闭度存下来，叶型交给气候**

v1 用一套「纬度 + 海拔」连续权重把 LC100 的林型族判成雨林／阔叶林／针叶林，为的是避开
"23.5° 一刀切"那条横穿两广的直线；v2 把林型合并、改由气候层分。**v6 把这两件事分工钉死**：

  · **郁闭度（密林／疏林）＝ 地表事实**，由 LC100 的郁闭六型／疏林六型直接给（`LC100_DIRECT`）。
    它是**存储**的，气候猜不出来 —— v5 之前正是靠气候干旱猜"疏林"，13.7 万格真疏林只有 18% 显示对。
  · **叶型（雨林／常绿阔叶／落叶阔叶／针叶）＝ 气候的事**，由 `森林 × 热量带` 当场派生
    （`地图/栅格地形数据生成器/display_class.py` 的按轴词表）。针叶↔寒、阔叶↔暖湿，这本来就是气候带的差别。
  · **高原／山地森林**用「高原密林／高原疏林／山地密林／山地疏林」——海拔上不再分叶型。

代价是一条已知的小偏差：低纬的人工针叶林（马尾松、杉木、日本人工林——LC100 也标成
针叶林）在气候看来是亚热带，会显示成常绿阔叶。实测面积极小，且换气候数据不必重做地形
——这正是这一层分离要买的东西。

### 地形表（v9：**一个字节 5 ＋ 3 位**——高 5 位覆盖、低 3 位形态；见 `docs/地形覆盖判定规格.md`）

    覆盖（高 5 位，20 值）  0海洋 1淡湖 2河流 3冰川 ｜ 4密林 5疏林 6灌丛 7草原 8草甸
                           9沼泽 10苔原 ｜ 11盐沼 12滩涂 ｜ 13沙质裸地 14砾质裸地 ｜ 15绿洲
                           ｜ 16海冰 17咸湖 18盐漠 19火山（v9 追加；最大字节 31×8+3 = 251）
    形态（低 3 位， 4 值）  0平原 1丘陵 2高原 3山地（海洋格写 0 当 don't-care）

**v7 的一处变化**：原来的「裸地」按**材质**拆成 **沙质裸地 / 砾质裸地**（`docs/adr/0012`）。
「沙漠」与「戈壁」不是气候的差别而是地表材质的差别——塔克拉玛干（沙）与蒙古戈壁（砾）在柯本
分类里**同属 BWk**，拿气候永远分不开；材质由 GSDP30 的「有沙占比」定（`地图/栅格地形数据生成器/sanddunes.py`）。

**一条总则（`docs/地形覆盖判定规格.md` §0）：每根轴只判它自己管的事。**
覆盖管"地表长着什么"（含**郁闭度**），气候管冷暖干湿，起伏管平陡。不许交叉：
拿气候猜"有没有树/树密不密"、拿默认值顶替"地表长什么"，都是错的——v2/v5 两轮的错都出在
这一条上（「亚寒带 → 苔原」是拿气候猜地表；「疏林 = 干旱气候的森林」是拿气候猜郁闭度；
「非干旱裸地 → 草原」是拿默认值顶替事实）。

**v6 三处变化**（`docs/adr/0010`）：
1. **森林按郁闭度拆开**：LC100 郁闭六型（111–116）→ **密林**、疏林六型（121–126）→ **疏林**。
   v5 之前两组并成一个「森林」，郁闭度这个事实被删掉、再由气候干旱去猜"疏林"——实测 13.7 万格
   真疏林里只有 18% 显示对，而图上写着"疏林"的判据是气候、不是郁闭度。
2. **灌丛（LC100 20）独立成覆盖类**，不再"存储上归草原"（那让 15 万格灌木在图上显示成草原）。
3. **「荒漠」改名「裸地」并去掉"必须是干旱气候"的前提**。荒漠是个气候词，不该当地表类名；
   去掉前提同时修掉 4.5 万格"源数据明说是裸露地面、图上却写着草原"的错，**3500 m 海拔上限随之取消**
   （那是给"荒漠必须是干旱"打的补丁）。
   沙漠/戈壁/寒漠/裸地 四个名字改由**显示层**按气候判（`display_class` 的裸地族）。
4. 顺带：**一个 LC100 码对一个覆盖类，植被层不再有中间哨兵**，`classify()` 退化成纯直通，
   v5 那三个候选哨兵与「草原族两级表决」一并删除。

**为什么必须拆**（`docs/adr/0007`，需求方看图报的）：

v2 让形态与覆盖**抢同一个值**，规则是"形态赢"。实测后果：全图形态类 520,660 格里有
**514,976 格（98.9%）底下藏着一个 LC100 覆盖**；西北窗口（96–108°E/32–40.5°N）更是
**100%**——那一片 LC100 说草原 19,471 格、裸地 9,845、森林 4,230、农田 3,050，
图上却只显示"高原 20,705"。于是：

  · **河湟谷地不见了**：西宁那格 2321 m、起伏 140 m → 判「高原」，而 LC100 说它是农田；
  · **陇右整片是高原**：天水、定西同样被形态吃掉覆盖；
  · **沙漠/苔原分不出来**：`沙漠 = 荒漠 ∧ 干旱`、`苔原 = 草原 ∧ 寒带`，可高原上的格
    根本没有覆盖可以相乘。

拆开之后一格可以同时是「高原 ∧ 草原」「山地 ∧ 森林」「高原 ∧ 草甸（河谷）」，上面
三件事一起解掉。两个半字节**共用原来那一个字节**，不加新图。

拆开后顺带作废两条 v2 的规则（现在都成了可表达的组合）：

  · `YIELD_TO_HILL`（丘陵接住草原）——"丘陵 ∧ 草原"现在能直接存，不必让位；
  · `open_ground`（山地/高原不吃覆盖）——现在"山地 ∧ 森林"能直接存。

**LC100 的农田与聚落 → 覆盖「草甸」**（v2 是"农田 → 平原"）：v2 让农田与形态抢位，只好
强行归平原；两轴分开之后它不再与平原竞争，于是回到覆盖轴上——这也正是"河湟谷地要有"
那一条的正解。

**名字是「草甸」**，这是需求方在同一天里改了三次之后定下的词（农田 → 田野 → **草甸**）。
第一次改（农田 → 田野）买到的东西是不再像在给土地贴**土地利用**标签——需求方原话是
"平原又不是全部都要利用"，这一层说的是**地表本身**，不是"人在种它"。第二次改（田野 →
草甸）是把它再往"地表本身"推一步：草甸是**地表的说法**，一个覆盖类不该替玩家回答
"这块地有没有开垦过"（那是地块层的属性，不是像元层的）。
⚠️ 它与覆盖 5「草原」只差一层植被密度，图上靠**配色**分开（草甸 `#e8e4a8` 偏黄、草原
`#b9c68a` 偏绿），显示类里也各自有名字——别把两者并成一个类。

绿洲仍是独立覆盖类（= LC100 农田 ∧ 真沙漠气候），保留在图例里。

**改这张表 = 改数据契约**：编码直接写进 `栅格/地形编码.png`，编辑器 `js/config.js`
的 `TER_COLORS` 与 `js/data.js` 的 `cover_legend`/`form_legend` 必须同步；`base_tag`
含图例摘要，改表会让编辑器里的本地草稿全部失效。
"""
from __future__ import annotations

import json
import os
import zlib

import numpy as np

# ---- 覆盖：地形字节的**高 5 位**（20 值／32 个位置；逐条口径见 docs/地形覆盖判定规格.md） ----
# ⚠️ **顺序即契约**：覆盖码写进 PNG 的高 5 位、也进 base_tag 的图例摘要，改序会让之后每个
#    码位整体错位（缓存作废、运行态语义全变）。
# ⚠️ **0–3（水与冰）钉死不动**：编辑器靠「字节 0 = 海洋」判海陆、靠覆盖码 1/2/3 做细线保护
#    （`地图/地图编辑器/js/config.js` 的 `TER_THIN`）。
#
# **v9 起覆盖占 5 位**（`docs/adr/0014`）：4 位只有 16 个位置、v7 已用满，而需求方要加
# 海冰／咸水湖／盐漠／火山 四类。**新类一律追加在末尾（16 起）**，前面 0–15 的**码值一个不动**
# —— 这样植被层的缓存仍然有效（里面存的就是覆盖码），省掉一次 1–2 分钟的重读。
# 排列：水冰 → 植被 → 湿生 → 海岸 → 无植被 → 派生 → **v9 追加（海冰／咸湖／盐漠／火山）**。
# ⚠️ v9 又把「湖泊」「咸水湖」改名成「**淡湖**」「**咸湖**」（需求方定）：有了咸湖就得有它的对应词。
#    **码值一个没动**（1 与 17），只改名字。
COVER_LEGEND = ["海洋", "淡湖", "河流", "冰川",
                "密林", "疏林", "灌丛", "草原", "草甸", "沼泽", "苔原",
                "盐沼", "滩涂", "沙质裸地", "砾质裸地", "绿洲",
                "海冰", "咸湖", "盐漠", "火山"]
(C_OCEAN, C_LAKE, C_RIVER, C_ICE,
 C_DENSE, C_OPEN, C_SHRUB, C_GRASS, C_FARM, C_MARSH, C_TUNDRA,
 C_SALTM, C_TIDAL, C_SAND, C_GRAVEL, C_OASIS,
 C_SEAICE, C_SALTLAKE, C_SALTPAN, C_VOLCANO) = range(20)
N_COVER = len(COVER_LEGEND)

# ---- 形态：地形字节的**低 4 位**（4 值，实际只用 2 位） ----
# ⚠️ 只有 4 个值，是因为运行态那条 32 位记录里形态只分到 **2 位**（见 docs/adr/0007）。
# 原来那个"无（水冰格）"被删掉了：海洋格的形态位一律写 平原（0）当 don't-care——
# 覆盖=海洋 已经足够识别海洋，再给形态留一个"无"就会把形态撑到 5 个值、2 位装不下
# （这正是子代理验收时抓到的那个 bug：山地的 4 溢出进了热量带，10.9 万格错位）。
# 湖泊与冰川**保留**它们的 landform（于是"高原湖泊"这类说法仍然成立）。
FORM_LEGEND = ["平原", "丘陵", "高原", "山地"]
(F_PLAIN, F_HILL, F_PLATEAU, F_MOUNTAIN) = range(4)
N_FORM = len(FORM_LEGEND)

VEG_UNKNOWN = 255                 # 植被层里"没有样本/无法归类"的哨兵（uint8）

# ---- 植被层：**与覆盖同码，一个哨兵都不需要**（v6） ----
# v6 起 LC100 的每一个码都有**自己的**覆盖类（灌丛 / 密林 / 疏林 / 裸地 全独立了），所以植被层
# 直接存覆盖码，`classify()` 退化成纯直通。v5 那三个候选哨兵（CAND_BARE / CAND_FOREST /
# CAND_SHRUB）与 `GRASS_FAMILY` 两级表决**一并删掉** —— 它们存在的前提（"几个 LC100 码共用一个
# 覆盖类，要靠另一根轴往回猜"）已经没有了。这正是那一类错（拿气候猜地表）的根，除掉它。
N_CAND = N_COVER                  # 候选码空间 = 覆盖码空间（15）；255 是"无样本"
CACHE_TAG = "cover-v6"            # 缓存标记：换了码的**含义**就 +1，否则旧缓存会被静默复用一个错映射。
                                  # v7（`adr/0012`）把 13 的**名字**改了（裸地→沙质裸地）但 LC100 60 → 13
                                  # 的**映射数值没变**，植被层逐字节相同，所以**特意不 bump**（省一次 1–2 分钟的重读）。

# ---------------------------------------------------------------- 地形字节的打包
# 一个字节：`码 = 覆盖 × 8 + 形态`（覆盖高 5 位、形态低 3 位；v9 起，ADR 0014）。这样**不加新图**
# ——编辑器少一套画布，而两者本来就永远一起读。海洋格的形态位恒写 0（平原）当 don't-care——
# **不给它留一个"无"**：那样形态会变成 5 个值，而运行态那条 32 位记录里形态只分到 2 位（ADR 0007）。


# 覆盖占**高 5 位**、形态占**低 3 位**（`docs/adr/0014`）：4 位只有 16 个位置、v7 用满了，
# 而 v9 要加海冰／咸水湖／盐漠／火山。5 位给 32 个位置（现用 20，余 12）。
# 形态只用 0–3（2 位），低 3 位里那 1 位空着——**故意留白**，将来要加第 5 种形态时不必再动布局。
# 最大字节 = 31×8 + 3 = **251 < 256** ✓；海洋仍是覆盖 0 ∧ 形态 0 = **字节 0** ✓（编辑器判海陆靠它）。
FORM_BITS = 3


def pack(cover: np.ndarray, form: np.ndarray) -> np.ndarray:
    """(覆盖, 形态) → 一个字节（覆盖在高 5 位、形态在低 3 位）。"""
    return ((cover.astype(np.uint16) << FORM_BITS)
            | (form.astype(np.uint16) & ((1 << FORM_BITS) - 1))).astype(np.uint8)


def unpack(ter: np.ndarray):
    """一个字节 → (覆盖, 形态)。"""
    t = ter.astype(np.uint8)
    return (t >> FORM_BITS).astype(np.uint8), (t & ((1 << FORM_BITS) - 1)).astype(np.uint8)
WATER_ENCODING = "waterfrac-v1"   # 水体占比层的缓存标记（LC100 80∪200 占有效样本的百分比）

# 水体占比的用法：**逐格取众数会把"碎成几块的水"藏起来**。实测长江口有一格
# 45% 是水像素（80/200 各占一部分），可单一类最多的是农田（LC100 40），取众数就记成
# 「平原」——于是长江口整片成了陆地色，河到 119.6°E 就"断"了（见 `设计笔记03` §14.13）。
# 修法：一格的水体占比 ≥ WATER_PCT 且**与既有水面 4 邻接**时，补成水面。
# 加"邻接"是为了不动海岸线：孤立的 30% 水格（滩涂、灌溉水田）不该变成河。
WATER_PCT = 30                    # 判"这格是水"的占比门槛（百分数）


def water_frac_note() -> str:
    """给调用方（台账 / 日志）用的一句话说明，避免口径再被抄错。"""
    return (f"水体占比 = LC100 的 80（内陆水）∪ 200（开阔海）占格内有效样本的百分比；"
            f"≥ {WATER_PCT}% 且与既有水面 4 邻接者补成水面（逐格众数会把碎水藏起来）")


# ---------------------------------------------------------------- 沙／砾 的分界（v7）
# LC100 60（裸地／稀疏植被）只说"地面是裸的"，说不出铺的是**沙**还是**砾**。材质由 GSDP30
# 的「有沙占比」（`地图/栅格地形数据生成器/sanddunes.py`）定：占比 ≥ SAND_PCT 读作**沙质裸地**（沙漠/沙地），
# 否则读作**砾质裸地**（戈壁/寒漠）。**为什么是 50**：GSDP30 的图例自己就是二元的
# （0–8/10 = 沙丘与沙席，"9 = 没有被沙覆盖的地面：砾石、裸岩、农田"），而一格取多数决
# 正是本管线对所有"格内成分不一"的通用口径（§8 第 3 条）。所以这不是我们划的线，
# 是数据自带的分界 + 既有的多数决口径。
#
# ⚠️ 实测这是**必需的**：气候数据分不开沙与砾——塔克拉玛干（沙海）与蒙古戈壁（砾漠）
# 在柯本分类里同属 BWk；土壤数据也分不开（试过 ISRIC SoilGrids 的粗碎屑与沙粒占比，
# 塔克拉玛干读 177‰ 而戈壁读 171‰）。见 地图/栅格地形数据生成器/sanddunes.py 抬头。
SAND_PCT = 50                     # 判"这格的材质是沙"的有沙占比门槛（百分数）


# v9：盐漠的门槛。GLWD-3 的「盐盘/咸水湿地」是**类值**（第 7 类），一格取"该类像素占多数"
# 就是本管线对所有"格内成分不一"的通用口径（§8 第 3 条）。同 SAND_PCT，阈值不是我们划的线。
SALT_PCT = 50                     # 判"这格是盐漠"的盐盘占比门槛（百分数）


def sand_note() -> str:
    """给调用方（台账 / 日志）用的一句话说明。"""
    return (f"材质 = GSDP30 的「有沙占比」：≥ {SAND_PCT}% 读作沙质裸地（沙漠／沙地），"
            f"否则砾质裸地（戈壁／寒漠）；占比 = 沙类像素占格内有效像素的百分比")

# ---------------------------------------------------------------- LC100 常量
LC100_SHAPE = (141120, 362880)    # 80 N → 60 S / 180 W → 180 E
LC100_PX_DEG = 1.0 / 1008.0       # 实测 0.0009920634920634888 = 1/1008（≈ 100 m）
LC100_TOP_LAT = 80.0
LC100_SEA = 200                   # 开阔海
LC100_NODATA = (0, 255)           # 0 = 无输入数据；255 = 产品 nodata

# ================================================================ 土地覆盖码表（LC100 → 覆盖）
# **这是全项目唯一一份 LC100 码表**（Copernicus CGLS-LC100 离散分类），逐条含中文名见
# `docs/地形覆盖判定规格.md` §2。一个码对一个覆盖类、**没有中间层** —— v6 之前那套
# "几个 LC100 码共用一个覆盖类、再靠气候往回猜"的中间层已删除（那正是"拿气候猜地表"这类错的根）。
LC100_DIRECT = {
    20: C_SHRUB,                       # 灌木（Shrubs）→ 灌丛
    30: C_GRASS,                       # 草本植被（Herbaceous vegetation）→ 草原
    40: C_FARM,                        # 耕地（Cultivated and managed vegetation）→ 草甸
    50: C_FARM,                        # 建成区（Urban / built-up）→ 草甸。**声明合并**：这一层只
                                       #   说地表本身、不说开垦（ADR 0009 决定 11）。
    60: C_SAND,                        # 裸地／稀疏植被（Bare / sparse vegetation）→ **沙质裸地**
                                       #   ⚠️ 这只是**占位**：LC100 60 只说"地面是裸的"，说不出
                                       #   地上铺的是沙还是砾。材质由 `生成.py` 用 GSDP30
                                       #   的「有沙占比」再定（低于门槛的改判 **砾质裸地**）。
                                       #   LC100 分不开沙与砾 —— 它只有一个笼统的"裸地"类。
    70: C_ICE,                         # 常年冰雪（Snow and ice）→ 冰川
    80: C_LAKE,                        # 内陆水体（Permanent water bodies）→ 湖泊
    90: C_MARSH,                       # 草本湿地（Herbaceous wetland）→ 沼泽（贴海则盐沼）
    100: C_TUNDRA,                     # 苔藓地衣（Moss and lichen）→ 苔原
    # 郁闭林六型（111–116）→ **密林**；疏林六型（121–126）→ **疏林**。
    # **郁闭度是地表事实**，由土地覆盖说了算；针叶／阔叶／落叶不在这里分 —— 那是**气候**的事
    # （林型表在 `display_class`）。v5 之前两组并成一个「森林」，郁闭度被删掉、再拿气候干旱去猜
    # "疏林"，是个真错（13.7 万格真疏林只有 18% 显示对），v6 修掉。
    111: C_DENSE, 112: C_DENSE, 113: C_DENSE, 114: C_DENSE, 115: C_DENSE, 116: C_DENSE,
    121: C_OPEN, 122: C_OPEN, 123: C_OPEN, 124: C_OPEN, 125: C_OPEN, 126: C_OPEN,
}

# ---------------------------------------------------------------- 形态阈值（起伏 = 格内 max−min）
# **三个数就够**（`adr/0012` 的兄弟条目 `adr/0013`）：
#   起伏 > 350 m → 山地      起伏 > 120 m → 丘陵      海拔 > 1200 m 且起伏 ≤ 350 m → 高原
#
# 起伏的物理含义：格 ≈ 5.86 km，所以 起伏 ÷ 5860 ≈ 整格平均坡度。
#   120 m ↔ 2.0%   350 m ↔ **6.0%**   600 m ↔ 10.2%
#
# **v8 把山地门槛从 600 降到 350**（2026-10-10，一次准确性检测查出来的）。600 m 那道线只有
# 极陡的地方够得着，实测：大别山主峰一带高格的起伏中位数 **432 m**（400 格里只有 5 格过 600）、
# 太行山主脊 **225 m**（平顶断块山）、华山 443、黄山 582 —— 于是**大别山 80% 读成丘陵、太行山
# 只有 1.9% 是山地**。而该是高原的羌塘，高格起伏中位数只有 211 m —— **山与高原之间有空隙，
# 切在 200–400 都分得开**，取 350（6% 坡）。
#
# 代价（实测，按陆面格数）：山地 3.6% → **10.3%**，丘陵 20.0% → 14.9%，高原 10.7% → 9.1%。
# 已知仍不完美：**窄而平顶的断块山**（太行山主脊那类）因为格内起伏本来就不大，仍会读丘陵——
# 那要的是"相对周边的高差"（prominence），得另加一层派生量，不是改这几个门槛能解决的。
#
# 原「2600 m 以上且起伏 ≤ 600 m」那一档**删掉了**：山地门槛一降到 350，它的 600 m 上限就永远
# 够不着（高原那支先判、随后被 `relief > 350` 覆盖），留着是个死条款。
MOUNTAIN_RELIEF = 350.0           # 起伏 > 350 m（≈ 6% 平均坡度）→ 山地
HILL_RELIEF = 120.0               # 起伏 > 120 m（≈ 2%）→ 丘陵
PLATEAU_ELEV = 1200.0             # 海拔 > 1200 m 且起伏小 → 高原（青藏/蒙古/黄土/云贵/伊朗）
PLATEAU_RELIEF_FLAT = 350.0       #   与山地门槛同一个数：高而平是高原，高而起伏是山地


# ================================================================ 陆地掩膜
def rasterize_union(LON, LAT, lon0, lat1, cell, geoms, out=None) -> np.ndarray:
    """把若干（已折回本图经度窗口的）几何按**格心命中**烧进一张掩膜。

    LON / LAT 是 (H, W) 的格心经纬度网格（build_raster 里已算好）。
    geoms 需先 make_valid / buffer(0)；这里只做 bbox 剪裁 + contains_xy。
    """
    from shapely import contains_xy
    H, W = LON.shape
    m = np.zeros((H, W), np.uint8) if out is None else out
    for g in geoms:
        if g is None or g.is_empty:
            continue
        x0, y0, x1, y1 = g.bounds
        c0 = max(0, int(np.floor((x0 - lon0) / cell)) - 1)
        c1 = min(W, int(np.ceil((x1 - lon0) / cell)) + 2)
        r0 = max(0, int(np.floor((lat1 - y1) / cell)) - 1)
        r1 = min(H, int(np.ceil((lat1 - y0) / cell)) + 2)
        if c1 <= c0 or r1 <= r0:
            continue
        xs, ys = LON[r0:r1, c0:c1].ravel(), LAT[r0:r1, c0:c1].ravel()
        hit = contains_xy(g, xs, ys).reshape(r1 - r0, c1 - c0)
        m[r0:r1, c0:c1][hit] = 1
    return m


# ================================================================ 高程与起伏
def read_elevation(etopo_path, lon0, lon1, lat0, lat1, W, H):
    """→ (elev 格均值, relief 格内极差) 两张 (H, W) float32。

    原实现有个隐性浪费：`np.concatenate([page.asarray()[...], page.asarray()[...]])`
    把整页 10800 × 21600 解了两遍（≈ 2 × 933 MB）。这里只解一遍。
    """
    import tifffile
    with tifffile.TiffFile(etopo_path) as tf:
        page = tf.pages[0]
        fh, fw = page.shape[0], page.shape[1]
        r0 = int((90.0 - lat1) / 180.0 * fh)
        r1 = int((90.0 - lat0) / 180.0 * fh)
        cA0, cA1 = int((lon0 + 180.0) / 360.0 * fw), int((180.0 + 180.0) / 360.0 * fw)
        cB0, cB1 = 0, int((lon1 - 360.0 + 180.0) / 360.0 * fw)
        whole = page.asarray()
        full = np.concatenate([whole[r0:r1, cA0:cA1], whole[r0:r1, cB0:cB1]], axis=1).astype(np.float32)
        del whole
    full[full <= -9999.0] = 0.0                      # GDAL_NODATA = -99999
    from PIL import Image
    # 0.0625° ÷ (1/60)° = 3.75 像元/格，除不尽；必须按面积平均（BOX），不能截断
    elev = np.asarray(Image.fromarray(full).resize((W, H), Image.BOX), dtype=np.float32)
    return elev, relief_of(full, H, W)


def relief_of(full: np.ndarray, H: int, W: int) -> np.ndarray:
    """格内 max−min（相对高差）。用 reduceat 按格边界分段，任意 cell 都对齐格心。"""
    rows, cols = full.shape
    rs = np.round(np.arange(H + 1) * rows / H).astype(np.int64)
    cs = np.round(np.arange(W + 1) * cols / W).astype(np.int64)
    np.clip(rs, 0, rows - 1, out=rs); rs[H] = rows
    np.clip(cs, 0, cols - 1, out=cs); cs[W] = cols
    np.maximum.accumulate(rs, out=rs)
    np.maximum.accumulate(cs, out=cs)
    hi_r = np.maximum.reduceat(full, rs[:-1], axis=0)
    lo_r = np.minimum.reduceat(full, rs[:-1], axis=0)
    hi = np.maximum.reduceat(hi_r, cs[:-1], axis=1)
    lo = np.minimum.reduceat(lo_r, cs[:-1], axis=1)
    return (hi - lo).astype(np.float32)


# ================================================================ 土地覆盖（LC100）
def _lc_cols(lon_s: np.ndarray) -> np.ndarray:
    """经度 → LC100 列号（-180…180 展开）"""
    return ((lon_s + 180.0) % 360.0) * 1008.0


def _lc_rows(lat_s: np.ndarray) -> np.ndarray:
    return np.round((LC100_TOP_LAT - lat_s) / LC100_PX_DEG).astype(np.int64)


def _lut() -> np.ndarray:
    """LC100 码 → 覆盖码（`LC100_DIRECT`），无对应给 VEG_UNKNOWN。

    v6 起植被层就是覆盖层：**一个码对一个覆盖类**，没有中间哨兵、也不再有"按纬度+海拔算权重
    定林型"那一层（林型是显示层的事，见 `display_class`）。
    """
    lut = np.full(256, VEG_UNKNOWN, np.uint8)
    for c, t in LC100_DIRECT.items():
        lut[c] = t
    lut[LC100_SEA] = C_OCEAN
    for c in LC100_NODATA:
        lut[c] = VEG_UNKNOWN
    return lut


def _dominant_from_parts(W, H, cell, lon0, lat1, read_strip, cache_path, rs=8, cs=3, log=print,
                         water_path=None):
    """逐格取 rs × cs 个样本的**主导候选**（12 个覆盖标号 + 2 个内部哨兵）。read_strip(row) → 该行列。

    同时算出**水体占比**层（LC100 的 80 内陆水 ∪ 200 开阔海 占有效样本的百分比）。
    为什么不另读一遍：LUT 已经把这两个码映射成 C_LAKE/C_OCEAN，所以水体计数就是
    `cnt` 的两列之和——白拿。为什么需要它：见 `water_frac_note()`。
    """
    x = np.arange(W)
    lon_s = lon0 + (x[:, None] + (np.arange(cs)[None, :] + 0.5) / cs) * cell      # (W, cs)
    cols = np.round(_lc_cols(lon_s)).astype(np.int64)
    colA0, colA1 = read_strip.colA
    idx = np.where(lon_s <= 180.0, cols - colA0, (colA1 - colA0) + cols)
    idx = np.clip(idx, 0, read_strip.width - 1)
    lut = _lut()

    veg = np.full((H, W), VEG_UNKNOWN, np.uint8)
    water = np.zeros((H, W), np.uint8)                     # 水体占比（百分数，0–100）
    cells_idx = np.repeat(x, cs).astype(np.int64)                              # (W*cs,)
    for y in range(H):
        lat_s = lat1 - (y + (np.arange(rs) + 0.5) / rs) * cell
        rr = np.clip(_lc_rows(lat_s), 0, LC100_SHAPE[0] - 1)
        cnt = np.zeros(W * N_CAND, np.int32)
        for r in rr:
            codes = read_strip(int(r))[idx]                                   # (W, cs)
            cls = lut[codes]
            keep = (cls != VEG_UNKNOWN).ravel()
            if not keep.any():
                continue
            flat = cells_idx[keep] * N_CAND + cls.ravel()[keep]
            cnt += np.bincount(flat, minlength=W * N_CAND)
        g = cnt.reshape(W, N_CAND)
        tot = g.sum(axis=1)
        # **一类一票，取单一类的多数**（v6）。不再有"族"：那套两级表决是把 灌丛/草本/苔原
        # 并成一票用的，而它们现在各有自己的覆盖类，前提没了。平局取码最小者。
        # 注：这让森林边界与 v5（把三者并成一票的那版）不同 —— 那是**重新定义**，不是漂移。
        best = g.argmax(axis=1).astype(np.uint8)
        veg[y] = np.where(tot > 0, best, VEG_UNKNOWN)
        w = g[:, C_OCEAN] + g[:, C_LAKE]                    # 水体 = 开阔海 + 内陆水
        water[y] = np.where(tot > 0, np.round(w * 100.0 / np.maximum(tot, 1)), 0).astype(np.uint8)
        if log and (y % 200 == 0 or y == H - 1):
            log(f"    植被/水体 {y + 1}/{H} 行")
    if water_path:
        try:
            np.save(water_path, water)
            with open(water_path + ".tag", "w", encoding="utf-8") as f:
                json.dump({"encoding": WATER_ENCODING}, f)
            log(f"  水体占比层已缓存 {os.path.basename(water_path)}"
                f"（{water.nbytes / 1048576:.1f} MB）")
        except Exception as e:                                                # noqa: BLE001
            log(f"  ! 水体占比层缓存失败：{e}")
    if cache_path:
        try:
            np.save(cache_path, veg)
            with open(cache_path + ".tag", "w", encoding="utf-8") as f:
                json.dump({"encoding": CACHE_TAG}, f)
            log(f"  植被层已缓存 {os.path.basename(cache_path)}（{veg.nbytes / 1048576:.1f} MB）")
        except Exception as e:                                                # noqa: BLE001
            log(f"  ! 植被层缓存失败：{e}")
    return veg, water


class _RawStrip:
    """LC100 裸数组（满分辨率原始字节）按行读窗口内的两段列。给可信的裸数组用。"""

    def __init__(self, path, lon0, lon1):
        self.mm = np.memmap(path, np.uint8, "r", shape=LC100_SHAPE)
        cA0 = int((lon0 + 180.0) * 1008.0)
        cA1 = LC100_SHAPE[1]
        self.cB1 = int((lon1 - 360.0 + 180.0) * 1008.0)
        self.colA = (cA0, cA1)
        self._b0, self._b1 = cA0, cA1
        self.width = (cA1 - cA0) + self.cB1

    def __call__(self, r: int) -> np.ndarray:
        a = self.mm[r, self._b0:self._b1]
        b = self.mm[r, 0:self.cB1] if self.cB1 else a[:0]
        return np.concatenate([a, b])


class _TifStrip:
    """LC100 压缩 TIFF 的瓦片流式解码（只解用得到的瓦片行 / 列，内存有界）。

    实测全窗约 1–2 分钟。
    """

    def __init__(self, path, lon0, lon1, log=print):
        import tifffile
        self.tf = tifffile.TiffFile(path)
        pg = self.tf.pages[0]
        assert pg.compression == 8 and pg.predictor == 1, "LC100 期望 Deflate/无预测器"
        self.pg = pg
        self.tw = pg.tilewidth
        self.th = pg.tilelength
        self.ntc = (pg.imagewidth + self.tw - 1) // self.tw
        cA0 = int((lon0 + 180.0) * 1008.0)
        cA1 = pg.imagewidth
        self.cB1 = int((lon1 - 360.0 + 180.0) * 1008.0)
        self.colA = (cA0, cA1)
        self.width = (cA1 - cA0) + self.cB1
        self._fh = open(path, "rb")
        self._cache_row = None
        self._cache = None
        log("  用瓦片流式解 LC100（Deflate 分块，只解用得到的瓦片；实测全窗约 1–2 分钟）")

    def _tile(self, iy: int, ix: int) -> np.ndarray:
        i = iy * self.ntc + ix
        self._fh.seek(self.pg.dataoffsets[i])
        raw = self._fh.read(self.pg.databytecounts[i])
        # 最后一行瓦片不满 256 行，故按 -1 推行数，不写死 (th, tw)
        return np.frombuffer(zlib.decompress(raw), np.uint8).reshape(-1, self.tw)

    def __call__(self, r: int) -> np.ndarray:
        ty = r // self.th
        if ty != self._cache_row:
            x0 = self.colA[0] // self.tw
            x1 = (self.colA[1] + self.tw - 1) // self.tw
            x2 = (self.cB1 + self.tw - 1) // self.tw
            skip = self.colA[0] - x0 * self.tw          # 首块要切掉不足一块的前缀
            head = np.concatenate([self._tile(ty, ix) for ix in range(x0, x1)], axis=1)
            head = head[:, skip:skip + (self.colA[1] - self.colA[0])]   # 末块也要切掉多余列
            if x2:
                tail = np.concatenate([self._tile(ty, ix) for ix in range(0, x2)], axis=1)[:, :self.cB1]
                self._cache = np.concatenate([head, tail], axis=1)
            else:
                self._cache = head
            self._cache_row = ty
        off = r - ty * self.th
        return self._cache[off] if off < self._cache.shape[0] else self._cache[-1]


def validate_raw(raw_path, tif_path, log=print) -> bool:
    """裸数组与 TIFF 逐点比对；对不上就说明它是残件，不能用。

    本机曾有的那份在 lat −18° 以南整片是 0（澳洲 / 新西兰 / 南部非洲全废），
    而字节数又恰好对上 —— 光看大小和北半球几个点都看不出来。故必须比"南边的点"。
    """
    pts = [(-26.0, 128.0), (-44.0, 170.0), (-20.0, 30.0), (-3.0, 115.0), (25.0, 15.0), (38.0, 116.0)]
    try:
        import tifffile
        mm = np.memmap(raw_path, np.uint8, "r", shape=LC100_SHAPE)
        with tifffile.TiffFile(tif_path) as tf:
            pg = tf.pages[0]
            ntc = (pg.imagewidth + pg.tilewidth - 1) // pg.tilewidth
            fh = open(tif_path, "rb")
            bad = []
            for lat, lon in pts:
                r = int((LC100_TOP_LAT - lat) / LC100_PX_DEG)
                c = int(((lon + 180.0) % 360.0) * 1008.0)
                iy, ix = r // pg.tilelength, c // pg.tilewidth
                i = iy * ntc + ix
                fh.seek(pg.dataoffsets[i])
                t = np.frombuffer(zlib.decompress(fh.read(pg.databytecounts[i])), np.uint8)
                t = t.reshape(-1, pg.tilewidth)
                want = int(t[r - iy * pg.tilelength, c - ix * pg.tilewidth])
                got = int(mm[r, c])
                if want != got:
                    bad.append(f"({lat:g},{lon:g}) TIFF={want} 裸数组={got}")
            fh.close()
    except Exception as e:                                                    # noqa: BLE001
        log(f"  ! 裸数组自检失败（{e}），改走 TIFF")
        return False
    if bad:
        log("  ! 裸数组与 TIFF 不符（是残件，已忽略）：" + "；".join(bad))
        return False
    log("  裸数组自检通过（6 个已知地点与 TIFF 一致）")
    return True


def _cache_ok(cache_path, encoding=CACHE_TAG):
    """缓存旁边有标记、且与当前标记一致才复用（换过编码**或表决版本**的旧缓存必须重算）。"""
    try:
        with open(cache_path + ".tag", encoding="utf-8") as f:
            return json.load(f).get("encoding") == encoding
    except Exception:                                                         # noqa: BLE001
        return False


def veg_from_landcover(W, H, cell, lon0, lon1, lat0, lat1, raw_path, tif_path, cache_path,
                       use_raw=False, log=print, water_path=None):
    """→ (veg, water)：候选标号 (H,W) uint8（VEG_UNKNOWN = 无数据）+ 水体占比 (H,W) uint8 百分数。

    两个源都没有则返回 (None, None)。水体占比的用途见 WATER_PCT 上面的说明。
    """
    say = log or (lambda *a, **k: None)
    if (cache_path and os.path.exists(cache_path) and _cache_ok(cache_path)
            and (not water_path or (os.path.exists(water_path)
                                    and _cache_ok(water_path, WATER_ENCODING)))):
        try:
            a = np.load(cache_path)
            w = np.load(water_path) if water_path else np.zeros((H, W), np.uint8)
            if a.shape == (H, W) and w.shape == (H, W):
                say(f"  植被层读缓存 {os.path.basename(cache_path)}"
                    + (f" + {os.path.basename(water_path)}" if water_path else ""))
                return a.astype(np.uint8), w.astype(np.uint8)
        except Exception:                                                     # noqa: BLE001
            pass
    src = None
    if use_raw and raw_path and os.path.exists(raw_path) and tif_path and os.path.exists(tif_path):
        if validate_raw(raw_path, tif_path, log=say):
            say("  植被层：读 LC100 裸数组")
            src = _RawStrip(raw_path, lon0, lon1)
    if src is None and tif_path and os.path.exists(tif_path):
        src = _TifStrip(tif_path, lon0, lon1, log=say)
    if src is None:
        say("  ! 没有 LC100（裸数组与 TIFF 都缺），植被类只能靠高程与掩膜推断")
        return None, None
    return _dominant_from_parts(W, H, cell, lon0, lat1, src, cache_path, log=say,
                                water_path=water_path)


# ================================================================ 分类
def landform(elev: np.ndarray, relief: np.ndarray) -> np.ndarray:
    """只按**起伏**（格内极差）与**海拔**给形态码（= FORM_LEGEND 的下标，0..3）：
    平原 0 / 丘陵 1 / 高原 2 / 山地 3。

    海拔只用来分「高原」——"高而平"的面；判丘陵/山地一律看起伏：
    海拔 4500 m 的青藏内部很平（高原），海拔 2000 m 的华山很陡（山地），
    四川盆地底部 400 m 且平坦（平原）——用海拔判会把盆地判成丘陵（踩过）。

    起伏的物理含义：格 ≈ 5.86 km，`起伏 ÷ 5860 ≈ 整格平均坡度`。

      山地：起伏 > **350 m**（≈ 6% 坡）
      丘陵：起伏 > 120 m（≈ 2%）
      高原：海拔 > 1200 m **且** 起伏 ≤ 350 m
            （青藏、蒙古高原、黄土高原、云贵高原、伊朗高原 —— 都是"面"不是"脊"）
      平原：其余

    ⚠️ **山地门槛 2026-10-10 由 600 降到 350**（`docs/adr/0013`）：600 m 只有极陡处够得着，
    实测大别山主峰的起伏中位数才 432 m、太行山主脊 225 m，于是**大别山 80% 被判成丘陵**。
    代价是山地由陆面的 3.6% 升到 **10.3%**（丘陵 20.0% → 14.9%）。详见常量处的注释。

    ⚠️ v3 起它**只出形态**，不再与覆盖抢同一个值：陇右（1500–2500 m、起伏 200–400 m）
    照样判「高原」，但那里的覆盖（LC100 的草原/农田）现在**看得见了**——
    这正是 `docs/adr/0007` 要修的东西。**不要把这里的阈值当成"西北画错了"的解**。
    """
    out = np.full(elev.shape, F_PLAIN, np.uint8)
    out[relief > HILL_RELIEF] = F_HILL
    out[(elev > PLATEAU_ELEV) & (relief <= PLATEAU_RELIEF_FLAT)] = F_PLATEAU
    out[relief > MOUNTAIN_RELIEF] = F_MOUNTAIN
    return out


def classify(elev, relief, veg, land):
    """→ **(cover, form) 两张 uint8**。两轴谁也不吃谁。

    · **形态**全交给高程 + 起伏（`landform`），陆地格一律有值，海洋格为 0（无意义）。
    · **覆盖**来自 LC100，**一个码对一个覆盖类、纯直通**（`LC100_DIRECT`，v6 起无中间层）。
      绿洲 / 盐沼 / 滩涂 三类要气候或海岸才判得出来，由 `生成.py` 后置覆盖——
      **那是"派生类"，在覆盖表里已声明**（见 `docs/地形覆盖判定规格.md` §3）。

    三条必须防的坑：
      · **LC100 200（开阔海）的格子不许盖到陆地上** —— 里海、咸海这类内海在 LC100 里
        记 200，而我们靠 NE 湖泊把它算作陆地；若让 200 生效就会写回「海洋」（里海曾经
        就这么变成海的）。排除掉，交给后面的 NE 湖泊面判成湖泊。
      · `land` 是 uint8 掩膜，**不能写 `~mask`** —— numpy 在 uint8 上按位取反，`~1 = 254`
        （真值），于是"~hard"恒真，覆盖会被整层抹掉（v1 就这么把森林全弄没过）。先转 bool。
      · 陆地默认覆盖给**草原**（LC100 无数据/无样本时最不坏的猜测：既不是水面也不是森林）。
    """
    land = np.asarray(land).astype(bool)
    form = np.zeros(elev.shape, np.uint8)
    form[land] = landform(elev, relief)[land]
    cover = np.full(elev.shape, C_OCEAN, np.uint8)
    cover[land] = C_GRASS
    if veg is None:
        return cover, form
    known = land & (veg != VEG_UNKNOWN) & (veg != C_OCEAN)
    cover[known] = veg[known]              # 覆盖码**直通**（与 LC100 码一一对应，v6 起无中间层）
    return cover, form
