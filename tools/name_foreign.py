#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给「外国县一级」（GADM 4.1 level 2，53 国 / 18,232 个单元）定中文名。

为什么需要这一步：GADM **没有中文名**（实测只有日本、中华民国的 NL_NAME_2 是汉字；
俄罗斯的 NAME_2 / NL_NAME_2 是 `Giaginskiyrayon` / `Гиагинскийрайон`，连空格都被抹掉）。
而本项目「每个单元都要有可读中文名」是写死的约定（NE admin-1 靠自带的 name_zh 满足）。

命名来源，按优先级：

  1. **自带**     GADM 的 NL_NAME_2 里含汉字（日本 1809/1811、中华民国 22/22）→ 直接用
  2. **维基数据** 从 QLever（Wikidata 的只读镜像，`query.wikidata.org` 常年限流）取
                 「位于本国 + 是行政区域（Q56061 子类）+ 有中文标签」的条目，
                 再用**归一化名称 + 坐标邻近**回连到 GADM 单元；中文标签一律 OpenCC 转简体
  3. **音译**     都没命中时按语言音译（TODO：目前只做了俄语，见 translit_ru）
  4. **待人工**   仍未命中的，保留原名并标出来，供人工在 TSV 里补

产物：`地图/地图数据/外国县名.tsv` —— 制表符分隔，**可以直接用文本编辑器改**。
重跑时若某单元的「中文名」被人工改过（来源列不是机器写的四种），不会被覆盖。

用法：
    python tools/name_foreign.py --all                      # 全部 53 国
    python tools/name_foreign.py --all --skip USA           # 美国这一国要单独处理，见下
    python tools/name_foreign.py --countries RUS TUR        # 只做指定国家（调试用）
    python tools/name_foreign.py --report                   # 只看现有 TSV 的覆盖率

美国为什么要单独处理：它的「行政区域 + 有中文标签」候选池比别的国家大两个数量级，
一条查询在 QLever 上必然超时（反复重试会卡很久）。而游戏只用到**夏威夷**（沧溟·夏威域，
5 个县），所以美国等国单独用 `--countries USA` 跑，或干脆手填那 5 个名字。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# ⚠️ 路径表（mapdata）与底图指纹（basetag）在 **地图/栅格地形数据生成器/** 里 ——
#    2026-10-10 地形流程那一整包搬去了那里，本文件留在 tools/（它做的是行政图那半）。
#    所以先把那一包挂上 sys.path，再 import 它里面的共用模块。
_GEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "地图", "栅格地形数据生成器")
sys.path.insert(0, _GEN)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapdata import FOREIGN_DIR, under                      # noqa: E402

ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"
CACHE_DIR = under("外国县名", "_维基数据")
OUT_TSV = under("外国县名.tsv")

# 53 国：ISO3 → (中文国名, 该国语言的 BCP-47 码表)。
# 语言码只用于「在哪几种语言的标签里找原名」——找错了只是匹配不上，不会写坏数据。
COUNTRIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("AFG", "阿富汗", ("fa", "ps")), ("ARE", "阿拉伯联合酋长国", ("ar",)),
    ("ASM", "美属萨摩亚", ("en",)), ("AUS", "澳大利亚", ("en",)),
    ("AZE", "阿塞拜疆", ("az",)), ("BGD", "孟加拉国", ("bn",)),
    ("BRN", "文莱", ("ms",)), ("BTN", "不丹", ("dz",)),
    ("FJI", "斐济", ("en",)), ("FSM", "密克罗尼西亚联邦", ("en",)),
    ("GEO", "格鲁吉亚", ("ka",)), ("IDN", "印度尼西亚", ("id",)),
    ("IND", "印度", ("hi", "en")), ("IRN", "伊朗", ("fa",)),
    ("IRQ", "伊拉克", ("ar",)), ("JOR", "约旦", ("ar",)),
    ("JPN", "日本", ("ja",)), ("KAZ", "哈萨克斯坦", ("kk",)),
    ("KGZ", "吉尔吉斯斯坦", ("ky",)), ("KHM", "柬埔寨", ("km",)),
    ("KOR", "大韩民国", ("ko",)), ("LAO", "老挝", ("lo",)),
    ("LBN", "黎巴嫩", ("ar",)), ("LKA", "斯里兰卡", ("si", "ta")),
    ("MMR", "缅甸", ("my",)), ("MNG", "蒙古国", ("mn",)),
    ("MYS", "马来西亚", ("ms",)), ("NCL", "新喀里多尼亚", ("fr",)),
    ("NPL", "尼泊尔", ("ne",)), ("NZL", "新西兰", ("en",)),
    ("OMN", "阿曼", ("ar",)), ("PAK", "巴基斯坦", ("ur",)),
    ("PHL", "菲律宾", ("en", "tl")), ("PNG", "巴布亚新几内亚", ("en",)),
    ("PRK", "朝鲜民主主义人民共和国", ("ko",)), ("RUS", "俄罗斯", ("ru",)),
    ("SAU", "沙特阿拉伯", ("ar",)), ("SLB", "所罗门群岛", ("en",)),
    ("SYR", "叙利亚", ("ar",)), ("THA", "泰国", ("th",)),
    ("TJK", "塔吉克斯坦", ("tg",)), ("TKM", "土库曼斯坦", ("tk",)),
    ("TLS", "东帝汶", ("pt",)), ("TON", "汤加", ("to",)),
    ("TUR", "土耳其", ("tr",)), ("TWN", "中华民国", ("zh",)),
    ("USA", "美国", ("en",)), ("UZB", "乌兹别克斯坦", ("uz",)),
    ("VNM", "越南", ("vi",)), ("VUT", "瓦努阿图", ("en", "fr")),
    ("WLF", "瓦利斯和富图纳", ("fr",)), ("WSM", "萨摩亚", ("sm",)),
    ("YEM", "也门", ("ar",)),
]
ZH_LANGS = ("zh", "zh-hans", "zh-cn", "zh-sg", "zh-hant", "zh-tw", "zh-hk", "zh-mo", "zh-my")

PREFIXES = ("PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
            "PREFIX wd: <http://www.wikidata.org/entity/>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n")

# ---------------------------------------------------------------------------
# 归一化：两张表要对得上，只能拿"字母"比。
# GADM 把名字里的空格全抹了（`Алейский район` → `Алейскийрайон`），所以"去掉非字母 + 转小写"
# 就能把两边对齐。\p{L} 在 QLever 上不支持，这里显式列各语系的码位区间。
KEEP_CLASS = ("[^a-z0-9"
              "\\u00c0-\\u024f"      # 拉丁扩展（越南、土耳其、北欧…）
              "\\u0370-\\u03ff"      # 希腊
              "\\u0400-\\u04ff"      # 西里尔
              "\\u0530-\\u058f"      # 亚美尼亚
              "\\u0590-\\u05ff"      # 希伯来
              "\\u0600-\\u06ff"      # 阿拉伯／波斯／乌尔都
              "\\u0900-\\u097f"      # 天城文
              "\\u0980-\\u09ff"      # 孟加拉
              "\\u0b80-\\u0bff"      # 泰米尔
              "\\u0d80-\\u0dff"      # 僧伽罗
              "\\u0e00-\\u0e7f"      # 泰
              "\\u0e80-\\u0eff"      # 老挝
              "\\u1000-\\u109f"      # 缅
              "\\u10a0-\\u10ff"      # 格鲁吉亚
              "\\u1780-\\u17ff"      # 高棉
              "\\u3040-\\u30ff"      # 日文假名
              "\\u4e00-\\u9fff"      # 汉字
              "\\uac00-\\ud7af"      # 谚文
              "]")
_KEEP = re.compile(KEEP_CLASS)
_HAN = re.compile(r"[\u4e00-\u9fff]")


def norm(s: str) -> str:
    """归一化成"只留字母/数字、全小写"的比较键。"""
    return _KEEP.sub("", (s or "").lower())


# ---------------------------------------------------------------------------
# 取数
def sparql(query: str, tries: int = 4, pause: float = 15.0):
    """打 QLever（GET——它的 POST 会被 308 跳到 qlever.dev 然后 429，走不通）。

    两条坑，都踩过：
      · 大查询塞进 URL 会被 **414** 挡掉 → 调用方必须把 VALUES 拆小（见 chunk）；
      · 「429」既表示限流也表示**查询超时**（响应体里写着 `Operation timed out`），
        所以查询本身得便宜，不能只靠重试扛。
    """
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": PREFIXES + query})
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "zhuilu-map-naming/1.0 (research)",
                "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            code = getattr(e, "code", "")
            if code == 429:
                try:
                    detail = e.read().decode("utf-8", "replace")[:150]
                except Exception:
                    detail = ""
                if "timed out" in detail:
                    raise RuntimeError(f"查询太贵被 QLever 超时挡掉，拆小一点：{detail}")
                print(f"    429：{detail[:90]}")
            wait = pause * (i + 1)
            print(f"    {code or type(e).__name__}——等 {wait:.0f}s 重试 {i + 1}/{tries}")
            time.sleep(wait)
    raise RuntimeError(f"取数失败：{last}")


def country_qids(isos: list[str]) -> dict[str, str]:
    """ISO 3166-1 alpha-3 → 国家条目 QID（P298），一次查询搞定，落盘缓存。"""
    p = under("外国县名", "_国家QID.json")
    cache = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    todo = [i for i in isos if i not in cache]
    if todo:
        vals = " ".join(f'"{i}"' for i in todo)
        r = sparql(f"SELECT ?iso ?c WHERE {{ ?c wdt:P298 ?iso . VALUES ?iso {{ {vals} }} }}")
        for b in r["results"]["bindings"]:
            cache[b["iso"]["value"]] = b["c"]["value"].rsplit("/", 1)[-1]
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(cache, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return cache


def fetch_country(iso3: str, qid: str, langs: tuple[str, ...], force: bool = False,
                  chunk: int = 400):
    """取一国的"候选条目"并缓存到 `_维基数据/<ISO3>.json`（逐国缓存，断了能接着跑）。

    口径：**位于本国 ＋ 是行政区域（Q56061 及其子类） ＋ 有中文标签**。
    这一刀把范围砍到与 GADM 单元数同量级（俄罗斯 7,878 条 vs 单元 2,445）；
    不加"行政区域"这一条会退化成"所有有条目的地方"——俄罗斯一国就 21 万条，而且在
    QLever 上直接超时。

    分三步查。**关键**：原名字标签与坐标必须各查各的——两个 OPTIONAL 放在一条里会
    乘成笛卡尔积，QLever 直接判超时（429 里写着 `Sort (internal order) on ?x`）。
      A) 本国 + 行政区域 + 中文标签          → 条目与中文名（俄罗斯 5.5 s / 1.2 万行）
      B) 按 A 的 QID 分块取原名标签（本国语言 + en）
      C) 同法取坐标（只在同名候选之间挑最近时用得上）
    块大小 400：1500 会让 URL 超长（414），而两块 OPTIONAL 合并则超时。
    """
    p = os.path.join(CACHE_DIR, f"{iso3}.json")
    if os.path.exists(p) and not force:
        return json.load(open(p, encoding="utf-8"))

    zh_list = ", ".join(f'"{l}"' for l in ZH_LANGS)
    print(f"  取 {iso3} …")
    a = sparql(f"""SELECT ?x ?zh ?zl WHERE {{
  ?x wdt:P17 wd:{qid} ; wdt:P31/wdt:P279* wd:Q56061 ; rdfs:label ?zh .
  FILTER(lang(?zh) IN ({zh_list})) BIND(lang(?zh) AS ?zl) }}""")
    rows = [{"qid": b["x"]["value"].rsplit("/", 1)[-1], "zh": b["zh"]["value"],
             "zl": b["zl"]["value"], "alt": "", "al": "", "pt": ""}
            for b in a["results"]["bindings"]]
    by_qid = {r["qid"]: r for r in rows}

    qids = sorted(by_qid)
    alt_list = ", ".join(f'"{l}"' for l in (*langs, "en"))
    for i in range(0, len(qids), chunk):
        vals = " ".join(f"wd:{q}" for q in qids[i:i + chunk])
        b = sparql(f"""SELECT ?x ?alt ?al WHERE {{ VALUES ?x {{ {vals} }}
  ?x rdfs:label ?alt . FILTER(lang(?alt) IN ({alt_list})) BIND(lang(?alt) AS ?al) }}""")
        alt: dict[str, list[tuple[str, str]]] = {}
        for x in b["results"]["bindings"]:
            q = x["x"]["value"].rsplit("/", 1)[-1]
            alt.setdefault(q, []).append((x["al"]["value"], x["alt"]["value"]))
        for q, lst in alt.items():
            base = by_qid[q]
            lst.sort()                                  # en 在 ru 前
            base["alt"], base["al"] = lst[0][1], lst[0][0]
            for l, v in lst[1:]:
                rows.append({**base, "alt": v, "al": l})
        c = sparql(f"""SELECT ?x ?coord WHERE {{ VALUES ?x {{ {vals} }} ?x wdt:P625 ?coord }}""")
        for x in c["results"]["bindings"]:
            q = x["x"]["value"].rsplit("/", 1)[-1]
            if q in by_qid:
                by_qid[q]["pt"] = x["coord"]["value"]
        time.sleep(0.5)                                # 别把公共端点打急了

    os.makedirs(CACHE_DIR, exist_ok=True)
    json.dump(rows, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"    {len(rows)} 行 / {len(qids)} 条目 → {os.path.relpath(p)}")
    return rows


# ---------------------------------------------------------------------------
# GADM 读入
def gadm_units(zh_name: str):
    """读一国的 GADM L2，产出 [{gid, n1, name2, nl2, varn2, lon, lat}]。

    GADM 的 JSON 不带质心，用 shapely 的代表点（representative_point，保证落在面内，
    凹面也不会跑出去）——同名候选有多条时要靠它挑最近的那个。
    """
    from shapely.geometry import shape
    path = os.path.join(FOREIGN_DIR, f"{zh_name}_县级_GADM41_2.json.zip")
    z = zipfile.ZipFile(path)
    j = json.loads(z.read([n for n in z.namelist() if n.endswith(".json")][0]))
    out = []
    for f in j["features"]:
        p = f["properties"]
        try:
            c = shape(f["geometry"]).representative_point()
            lon, lat = c.x, c.y
        except Exception:
            lon = lat = None
        out.append({"gid": p.get("GID_2", ""), "n1": p.get("NAME_1", ""),
                    "name2": p.get("NAME_2", ""), "nl2": p.get("NL_NAME_2", ""),
                    "varn2": p.get("VARNAME_2", ""), "lon": lon, "lat": lat})
    return out


def point_of(wkt: str):
    """解析 WKT `Point(lon lat)`。"""
    if not wkt:
        return None
    m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", wkt)
    return (float(m.group(1)), float(m.group(2))) if m else None


# ---------------------------------------------------------------------------
# 匹配
def _to_simp():
    """繁→简。维基数据的中文标签以繁体为主（俄罗斯行政区域：zh 8,934 / zh-hans 只有 978），
    本项目正文是简体，所以统一转一次。opencc 不可用时退化为原文（并在报告里说明）。"""
    try:
        from opencc import OpenCC
        cc = OpenCC("t2s")
        return cc.convert
    except ImportError:
        return None


def build_names(iso3: str, zh_name: str, rows) -> list[dict]:
    """把候选条目回连到 GADM 单元。

    中文标签按 zh-hans > zh-cn > zh > zh-hant 的顺序取（zh 最常见，且多是繁体）。
    同一个归一化名可能对上多个条目（"某区" 与 "某市" 同名），此时按**代表点最近**的取。
    """
    units = gadm_units(zh_name)

    # 候选条目：按归一化名建索引（原名标签 + 中文标签都能当键）
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        for k in {norm(r.get("alt")), norm(r.get("zh"))} - {""}:
            by_key.setdefault(k, []).append(r)

    # 每个条目选一个中文名（变体优先级）
    rank_of = {l: i for i, l in enumerate(
        ("zh-hans", "zh-cn", "zh-sg", "zh", "zh-my", "zh-hant", "zh-tw", "zh-hk", "zh-mo"))}
    zh_of: dict[str, tuple[int, str]] = {}
    for r in rows:
        q, rank = r["qid"], rank_of.get(r["zl"], 99)
        if q not in zh_of or rank < zh_of[q][0]:
            zh_of[q] = (rank, r["zh"])

    out = []
    for u in units:
        cands, seen = [], set()
        for v in (u["nl2"], u["name2"], u["varn2"]):
            for c in by_key.get(norm(v), []):
                if c["qid"] not in seen:
                    seen.add(c["qid"])
                    cands.append(c)

        src, cn, qid = "待人工", "", ""
        if _HAN.search(u["nl2"] or ""):
            src, cn = "自带", u["nl2"]              # ① GADM 自己就是汉字（日本、中华民国）
        elif cands:
            # ② 维基数据：有中文名的优先；多个之间按代表点距离挑
            named = [c for c in cands if zh_of.get(c["qid"], (99, ""))[0] < 99]
            pool = named or cands
            best = pool[0]
            if len(pool) > 1 and u["lon"] is not None:
                def dist(c):
                    pt = point_of(c.get("pt"))
                    if not pt:
                        return 1e9
                    return (pt[0] - u["lon"]) ** 2 + (pt[1] - u["lat"]) ** 2
                best = min(pool, key=dist)
                # 最近的那条要是离得太远（>2°，约 200 km），宁可判为无匹配——多半是同名不同地
                if dist(best) > 4.0:
                    best = None
            if best and zh_of.get(best["qid"], (99, ""))[0] < 99:
                src, cn, qid = "维基数据", zh_of[best["qid"]][1], best["qid"]
        out.append({**u, "中文名": cn, "来源": src, "qid": qid,
                    "原名": u["nl2"] or u["name2"]})
    return out


# ---------------------------------------------------------------------------
def merge_rows(all_rows: list[dict], zh_name: str, named: list[dict]) -> list[dict]:
    """把一家国家的命名结果并进总表；**人工改过的行原样保留**（来源列不是机器写的四种）。"""
    MACHINE = ("", "自带", "维基数据", "音译", "待人工")
    by_gid = {r["GID"]: r for r in all_rows if r.get("国家") == zh_name}
    for n in named:
        old = by_gid.get(n["gid"])
        if old and old.get("来源") not in MACHINE:
            continue                                   # 人工改过 → 不动
        by_gid[n["gid"]] = {"国家": zh_name, "GID": n["gid"], "一级": n["n1"],
                            "原名": n["原名"], "中文名": n["中文名"],
                            "来源": n["来源"], "QID": n["qid"]}
    rest = [r for r in all_rows if r.get("国家") != zh_name]
    return rest + list(by_gid.values())


COLS = ["国家", "GID", "一级", "原名", "中文名", "来源", "QID"]


def read_tsv() -> list[dict]:
    if not os.path.exists(OUT_TSV):
        return []
    with open(OUT_TSV, encoding="utf-8-sig") as f:
        head = f.readline().rstrip("\n").split("\t")
        out = []
        for ln in f:
            if ln.strip():
                out.append(dict(zip(head, ln.rstrip("\n").split("\t"))))
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="*", help="只做这些 ISO3")
    ap.add_argument("--skip", nargs="*", default=[], help="跳过这些 ISO3")
    ap.add_argument("--all", action="store_true", help="全部 53 国")
    ap.add_argument("--report", action="store_true", help="只看现有 TSV 的覆盖情况")
    ap.add_argument("--force", action="store_true", help="忽略候选缓存，重新取数")
    args = ap.parse_args()

    if args.report:
        rows = read_tsv()
        if not rows:
            print(f"还没有 {os.path.relpath(OUT_TSV)}")
            return 1
        return report(rows)

    todo = COUNTRIES if (args.all or not args.countries) else \
        [c for c in COUNTRIES if c[0] in set(args.countries)]
    if args.skip:
        todo = [c for c in todo if c[0] not in set(args.skip)]
    if not todo:
        print("没有匹配的国家")
        return 2

    qids = country_qids([c[0] for c in todo])
    simp = _to_simp()
    if not simp:
        print("！opencc 不可用，中文名会保持繁体（pip install opencc-python-reimplemented）")
    allrows = read_tsv()
    for iso3, zh_name, langs in todo:
        qid = qids.get(iso3)
        if not qid:
            print(f"  跳过 {iso3}：解析不到国家条目")
            continue
        rows = fetch_country(iso3, qid, langs, force=args.force)
        named = build_names(iso3, zh_name, rows)
        if simp:
            for n in named:
                if n["中文名"]:
                    n["中文名"] = simp(n["中文名"])
        allrows = merge_rows(allrows, zh_name, named)
        got = sum(1 for r in named if r["中文名"])
        print(f"  {iso3} {zh_name}：{len(named)} 个单元，有中文名 {got}"
              f"（{got * 100 // max(1, len(named))}%）")

    allrows.sort(key=lambda r: (r.get("国家", ""), r.get("GID", "")))
    os.makedirs(os.path.dirname(OUT_TSV), exist_ok=True)
    with open(OUT_TSV, "w", encoding="utf-8-sig", newline="") as f:
        f.write("\t".join(COLS) + "\n")
        for r in allrows:
            f.write("\t".join(str(r.get(c, "")) for c in COLS) + "\n")
    print(f"\n写出 {os.path.relpath(OUT_TSV)}（{len(allrows)} 行）")
    return report(allrows)


def report(rows) -> int:
    from collections import Counter
    print(f"\n{'国家':<12}{'单元':>6}{'自带':>6}{'维基':>6}{'音译':>6}{'待人工':>7}{'覆盖':>7}")
    by = {}
    for r in rows:
        by.setdefault(r.get("国家", "?"), []).append(r)
    tot = c = Counter()
    for nm, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        cnt = Counter(x.get("来源", "") for x in rs)
        got = len(rs) - cnt.get("待人工", 0)
        print(f"{nm:<12}{len(rs):>6}{cnt.get('自带', 0):>6}{cnt.get('维基数据', 0):>6}"
              f"{cnt.get('音译', 0):>6}{cnt.get('待人工', 0):>7}{got * 100 // max(1, len(rs)):>6}%")
        tot += cnt
    n = sum(tot.values())
    got = n - tot.get("待人工", 0)
    print(f"{'合计':<12}{n:>6}{tot.get('自带', 0):>6}{tot.get('维基数据', 0):>6}"
          f"{tot.get('音译', 0):>6}{tot.get('待人工', 0):>7}{got * 100 // max(1, n):>6}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
