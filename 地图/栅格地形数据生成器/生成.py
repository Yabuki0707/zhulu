#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成.py —— **命令行入口**（原 `地图/栅格地形数据生成器/生成.py` 的 main，2026-10-10 瘦成这一层）。

    python 生成.py                        # 全跑（默认 1/19° ≈ 5.86 km）
    python 生成.py --no-veg               # 不读土地覆盖（地形只剩海陆两档，快）
    python 生成.py --只跑到 2             # 只跑前两步（调试某一步用）
    python 生成.py --山地起伏 300         # 改规则门槛（⚠️ 产物不再算契约产品，见 参数.py）

流程本身在 `管线.py` 的**阶段表**里，一步一个模块（`阶段/*.py`）。本文件只做三件事：
解析参数 → 建上下文 → 报告产物。**别再往这里加逻辑** —— 加的是"阶段"。

双击 `生成地形.bat` 走的是 `界面.py`（同一个 参数.py，两条路不会分叉）。
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from 契约 import OUT, RUN_DIR, F_PLOT, F_TERRAIN, F_CLIM, F_DIST, F_REFV, F_META   # noqa: E402
from 参数 import 加命令行参数, 从命令行                                              # noqa: E402
from 管线 import 建上下文, 跑                                                        # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="逐鹿 · 栅格地形数据生成器")
    加命令行参数(ap)
    args = ap.parse_args(argv)
    try:
        ctx = 建上下文(从命令行(args))
    except FileNotFoundError as e:
        print(f"缺 基础单元.json —— {e}", file=sys.stderr)
        return 1
    跑(ctx, 只跑到=args.只跑到)
    # 产物清单（大小 + 路径）：一眼看出"这一趟到底写了什么"
    print("\n产物：")
    for d, fns in ((OUT, (F_PLOT, F_TERRAIN, F_CLIM, F_DIST, F_REFV, F_META)),):
        for fn in fns:
            p = os.path.join(d, fn)
            if os.path.exists(p):
                print(f"  {os.path.relpath(p, os.path.dirname(os.path.dirname(d)))}"
                      f"  {os.path.getsize(p) / 1048576:6.2f} MB")
    for p in (os.path.join(RUN_DIR, "底图.bin"),):
        if os.path.exists(p):
            print(f"  {os.path.relpath(p, os.path.dirname(os.path.dirname(os.path.dirname(p))))}"
                  f"  {os.path.getsize(p) / 1048576:6.2f} MB")
    print("\n改完记得跑一遍自检：python check_terrain.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:                                                         # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
