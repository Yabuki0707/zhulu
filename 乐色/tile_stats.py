# -*- coding: utf-8 -*-
"""附录C-世界地域清单 · 地块分布统计与校验。

用法:
    python tile_stats.py                 # 默认读取 ../附录C-世界地域清单.md
    python tile_stats.py <清单.md路径>

输出:
    控制台报告, 并在脚本同目录写一份 统计报告.md。

参考值说明:
    REF 中的面积/人口为「约10~13世纪」的量级估计(取历史人口学常见区间的中间值),
    仅用于地缘之间的配比横比, 不作精确考据依据。
"""

import os
import re
import sys
import unicodedata
import statistics as st
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MD = os.path.normpath(os.path.join(HERE, '..', '附录C-世界地域清单.md'))
REPORT_MD = os.path.join(HERE, '统计报告.md')

SEC_RE = re.compile(r'^##\s*C(\d+)\.\s*(.+?)（\s*(\d+)\s*地域\s*/\s*(\d+)\s*地块\s*）\s*$')
ROW_RE = re.compile(r'^\|([^|]+)\|([^|]+)\|\s*(\d+)\s*\|([^|]*)\|\s*$')
OVR_RE = re.compile(r'^\|\s*(\S[^|]*?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*$')
INTRO_RE = re.compile(r'(\d+)\s*个地缘.*?(\d+)\s*个地域.*?约\s*(\d+)\s*个地块')

# 地缘 -> (面积/百万km², 人口/百万)  量级参考, 见文件头说明
REF = OrderedDict([
    ('汉地', (4.0, 105)),   # 两宋+大理+陇右河湟(不含辽夏)
    ('海东', (0.5, 13)),    # 平安末~镰仓初的日本 + 王氏高丽 + 琉球
    ('辽海', (1.0, 3)),     # 东北+外东北+库页
    ('北荒', (13.0, 0.3)),  # 西伯利亚
    ('瀚海', (2.6, 2)),     # 蒙古高原+贝加尔周边
    ('西域', (1.7, 1.5)),   # 今天山南北
    ('青藏', (3.0, 5)),     # 青藏高原+尼婆罗+不丹+拉达克
    ('河中', (0.9, 5)),     # 河中+花剌子模
    ('波斯', (3.1, 15)),    # 伊朗+两河+阿富汗+阿塞拜疆+俾路支
    ('天竺', (4.4, 80)),    # 南亚次大陆+锡兰
    ('扶南', (1.9, 12)),    # 中南半岛
    ('南洋', (2.5, 8)),     # 马来群岛+菲律宾
    ('红洲', (7.7, 0.5)),   # 澳大利亚
    ('沧溟', (0.05, 1)),    # 太平洋岛屿(陆地面积粗估)
])


# ---------- 展示辅助(中日韩字符按2列宽对齐) ----------

def dlen(s):
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in str(s))


def pad(s, n, right=False):
    s = str(s)
    gap = max(0, n - dlen(s))
    return f'{" " * gap}{s}' if right else f'{s}{" " * gap}'


def row(cells, widths, right_cols=()):
    out = []
    for i, (c, w) in enumerate(zip(cells, widths)):
        out.append(pad(c, w, right=(i in right_cols)))
    return '  '.join(out)


# ---------- 解析 ----------

def parse(text):
    sections = OrderedDict()   # 地缘 -> dict(no, name, claim_r, claim_t, rows)
    overview = OrderedDict()   # 地缘(或'合计') -> (地域数, 地块数)
    intro_claim = None
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        m = INTRO_RE.search(line)
        if m and intro_claim is None:
            intro_claim = tuple(int(x) for x in m.groups())
        m = SEC_RE.match(line)
        if m:
            cur = {'no': int(m.group(1)), 'name': m.group(2).strip(),
                   'claim_r': int(m.group(3)), 'claim_t': int(m.group(4)), 'rows': []}
            sections[cur['name']] = cur
            continue
        m = OVR_RE.match(line.replace('**', ''))
        if m and not line.startswith('#'):
            overview[m.group(1)] = (int(m.group(2)), int(m.group(3)))
            continue
        m = ROW_RE.match(line)
        if m:
            name = m.group(1).strip()
            if cur is not None and name.endswith('域'):
                cur['rows'].append({'name': name, 'range': m.group(2).strip(),
                                    'tiles': int(m.group(3)), 'remark': m.group(4).strip()})
    return sections, overview, intro_claim


# ---------- 校验 ----------

def run_checks(sections, overview, intro_claim):
    checks = []

    def check(ok, msg):
        checks.append((ok, msg))

    n_sec = len(sections)
    n_reg = sum(len(s['rows']) for s in sections.values())
    n_tile = sum(r['tiles'] for s in sections.values() for r in s['rows'])
    if intro_claim:
        check((n_sec, n_reg, n_tile) == intro_claim,
              f"文件头声明({intro_claim[0]}地缘/{intro_claim[1]}地域/{intro_claim[2]}地块) vs 实际({n_sec}/{n_reg}/{n_tile})")
    else:
        check(False, '未找到文件头「N个地缘→N个地域→约N个地块」声明')

    ov_total = overview.get('合计')
    check(ov_total == (n_reg, n_tile) if ov_total else False,
          f"C1合计行 {ov_total} vs 实际({n_reg}, {n_tile})")

    for name, s in sections.items():
        got_r, got_t = len(s['rows']), sum(r['tiles'] for r in s['rows'])
        ok = (got_r == s['claim_r'] and got_t == s['claim_t']
              and overview.get(name) == (got_r, got_t))
        check(ok, f"{name}: 表头声明{s['claim_r']}域/{s['claim_t']}块, C1表{overview.get(name)}, 实际{got_r}域/{got_t}块")

    names = [r['name'] for s in sections.values() for r in s['rows']]
    dup = [n for n in set(names) if names.count(n) > 1]
    check(not dup, f"地域名重复: {dup}" if dup else '96个地域名无重复')
    bad_name = [n for n in names if not re.fullmatch(r'[\u4e00-\u9fff]{2}域', n)]
    check(not bad_name, f"违反「二字+域」命名: {bad_name}" if bad_name else '全部地域名符合「二字+域」')

    collide = sorted({n for n in names if n[:-1] in sections})
    check(not collide, f"地域名与地缘名同源(易混): {collide}" if collide else '无地域名与地缘名同源')

    hd = sections.get('汉地')
    hd_t = sum(r['tiles'] for r in hd['rows']) if hd else 0
    check(hd_t >= 100, f"【需求】汉地≥三位数: {hd_t}块 -> {'满足' if hd_t >= 100 else '不满足'}")

    return checks, n_reg, n_tile


# ---------- 统计 ----------

def bucket(t):
    for hi, label in ((3, '3'), (4, '4'), (5, '5'), (7, '6-7'), (9, '8-9'),
                      (11, '10-11'), (13, '12-13'), (15, '14-15'), (19, '16-19')):
        if t <= hi:
            return label
    return '20+'


def run_stats(sections, n_tile):
    per_geo = OrderedDict()
    all_tiles = []
    for name, s in sections.items():
        ts = [r['tiles'] for r in s['rows']]
        all_tiles += ts
        per_geo[name] = {
            'r': len(ts), 't': sum(ts),
            'avg': sum(ts) / len(ts), 'med': st.median(ts),
            'min': min(ts), 'max': max(ts),
            'sd': st.pstdev(ts),
        }
    glob = {'n': len(all_tiles), 'sum': sum(all_tiles),
            'avg': sum(all_tiles) / len(all_tiles), 'med': st.median(all_tiles),
            'min': min(all_tiles), 'max': max(all_tiles), 'sd': st.pstdev(all_tiles)}

    hist = OrderedDict()
    for t in sorted(all_tiles):
        hist[bucket(t)] = hist.get(bucket(t), 0) + 1

    big = [(r['name'], s['name'], r['tiles']) for s in sections.values() for r in s['rows'] if r['tiles'] >= 16]
    small = [(r['name'], s['name'], r['tiles']) for s in sections.values() for r in s['rows'] if r['tiles'] <= 4]

    ref_rows = []
    pop_sum = sum(v[1] for v in REF.values())
    for name, s in sections.items():
        t = per_geo[name]['t']
        area, pop = REF.get(name, (None, None))
        share = t / n_tile * 100
        pop_share = pop / pop_sum * 100 if pop else None
        ref_rows.append({
            'geo': name, 'tiles': t, 'share': share,
            'pop_share': pop_share, 'x_pop': (share / pop_share) if pop_share else None,
            'per_area': t / area if area else None,
            'per_pop': t / pop if pop else None,
        })
    return per_geo, glob, hist, big, small, ref_rows


# ---------- 报告 ----------

def build_report(sections, overview, intro_claim, checks,
                 per_geo, glob, hist, big, small, ref_rows, n_tile):
    L = []
    A = L.append

    A('# 附录C · 地块分布统计报告')
    A('')
    A('> 由 乐色/tile_stats.py 生成。人口/面积参考值仅为约10~13世纪的量级估计, 用于横比。')
    A('')

    A('## 一、一致性校验')
    A('')
    fails = [c for c in checks if not c[0]]
    for ok, msg in checks:
        A(f"- {'✅' if ok else '❌'} {msg}")
    A('')
    A(f"**小结: {len(checks) - len(fails)}/{len(checks)} 项通过**。")
    A('')

    A('## 二、全域分布')
    A('')
    A(f"- 地域数 {glob['n']}, 地块数 {glob['sum']}")
    A(f"- 每域地块: 均值 {glob['avg']:.2f}, 中位数 {glob['med']:.0f}, 标准差 {glob['sd']:.2f}, "
      f"最小 {glob['min']}, 最大 {glob['max']} (极差 {glob['max'] / glob['min']:.1f}倍)")
    A('')
    A('| 地块数区间 | 地域个数 | 分布 |')
    A('|---|---:|---|')
    for k, v in hist.items():
        A(f"| {k} | {v} | {'█' * v} |")
    A('')

    A('## 三、分地缘统计')
    A('')
    w = [6, 6, 6, 9, 8, 9, 9, 5]
    A(row(['地缘', '地域数', '地块数', '地块占比', '均值/域', '中位数', '最小~最大', 'CV'], w, right_cols={1, 2, 3, 4, 5, 6, 7}))
    A(row(['-' * c for c in w], w))
    for name, d in per_geo.items():
        A(row([name, d['r'], d['t'], f"{d['t'] / n_tile * 100:.1f}%",
               f"{d['avg']:.1f}", f"{d['med']:.0f}", f"{d['min']}~{d['max']}",
               f"{d['sd'] / d['avg']:.2f}"], w, right_cols={1, 2, 3, 4, 5, 6, 7}))
    A(row(['合计', glob['n'], glob['sum'], '100%', f"{glob['avg']:.1f}",
           f"{glob['med']:.0f}", f"{glob['min']}~{glob['max']}",
           f"{glob['sd'] / glob['avg']:.2f}"], w, right_cols={1, 2, 3, 4, 5, 6, 7}))
    A('')

    A('## 四、极值')
    A('')
    big_t = sum(t for _, _, t in big)
    small_t = sum(t for _, _, t in small)
    A(f"**巨型域 (≥16块, {len(big)}个 / {big_t}块 / {big_t / n_tile * 100:.1f}%)**:")
    A('')
    for n, g, t in sorted(big, key=lambda x: -x[2]):
        A(f"- {n}({g}) {t}块")
    A('')
    A(f"**微型域 (≤4块, {len(small)}个 / {small_t}块 / {small_t / n_tile * 100:.1f}%)**:")
    A('')
    for n, g, t in sorted(small, key=lambda x: x[2]):
        A(f"- {n}({g}) {t}块")
    A('')

    A('## 五、配比横比 (量级参考)')
    A('')
    w2 = [6, 5, 8, 8, 10, 10, 10]
    A(row(['地缘', '地块', '块占比', '人口占比', '块占比/人口占比', '块/百万人', '块/百万km²'], w2,
           right_cols={1, 2, 3, 4, 5, 6}))
    A(row(['-' * c for c in w2], w2))
    for d in sorted(ref_rows, key=lambda x: -(x['per_pop'] or 0)):
        A(row([d['geo'], d['tiles'], f"{d['share']:.1f}%", f"{d['pop_share']:.1f}%",
               f"{d['x_pop']:.1f}x", f"{d['per_pop']:.1f}", f"{d['per_area']:.1f}"],
              w2, right_cols={1, 2, 3, 4, 5, 6}))
    A('')
    A('解读: 「块占比/人口占比」≈1 表示地块配额与人口相称; 明显>1 属于"超配"')
    A('(边缘地区为了让玩家有事可做, 超配是常态, 但倍数过高意味着地块性价比低)。')
    A('')

    A('## 六、脚本自动提示')
    A('')
    world_avg = glob['avg']
    for name, d in per_geo.items():
        if d['avg'] > world_avg * 1.5:
            A(f"- 【粒度】{name} 平均 {d['avg']:.1f} 块/域, 为全图均值({world_avg:.1f})的 {d['avg'] / world_avg:.1f} 倍, 地域粒度显著偏粗。")
        if d['avg'] < world_avg * 0.65:
            A(f"- 【粒度】{name} 平均 {d['avg']:.1f} 块/域, 仅为全图均值的 {d['avg'] / world_avg:.2f} 倍, 地域碎片化。")
    over = [d for d in ref_rows if d['x_pop'] and d['x_pop'] >= 8]
    for d in sorted(over, key=lambda x: -x['x_pop']):
        A(f"- 【超配】{d['geo']}: 地块占比 {d['share']:.1f}% 是人口占比({d['pop_share']:.1f}%)的 {d['x_pop']:.0f} 倍, "
          f"每块仅摊 {d['per_pop'] * 10000:.0f} 人量级。")
    A('')
    return '\n'.join(L)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MD
    with open(path, encoding='utf-8') as f:
        text = f.read()
    sections, overview, intro_claim = parse(text)
    checks, n_reg, n_tile = run_checks(sections, overview, intro_claim)
    per_geo, glob, hist, big, small, ref_rows = run_stats(sections, n_tile)
    report = build_report(sections, overview, intro_claim, checks,
                          per_geo, glob, hist, big, small, ref_rows, n_tile)
    with open(REPORT_MD, 'w', encoding='utf-8') as f:
        f.write(report)
    print(report)
    print(f"\n(报告已写入: {REPORT_MD})")


if __name__ == '__main__':
    main()
