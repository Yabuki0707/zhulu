# -*- coding: utf-8 -*-
"""run.py —— **bat 与 Python 之间的桥**（名字故意用 ASCII）。

为什么需要它：`生成地形.bat` 必须是 **ASCII-only** —— `chcp 65001` 之后 cmd.exe 会带着一个
字节偏移重新读批处理文件，多字节字符会让它错位、把后面的行撕成乱码（编辑器那支 bat 里记着
这个坑）。可本包的两个入口是中文名（`界面.py` / `生成.py`），写在 bat 里就带了多字节。
于是：bat 只调这一个 ASCII 名字的文件，由它去 import 中文名的模块。

    python run.py                     # 同双击 bat：开可视化界面
    python run.py --no-veg            # 直接走命令行（参数与界面同一份 参数.py）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    argv = sys.argv[1:]
    if argv:
        import 生成
        return 生成.main(argv)
    import 界面
    return 界面.main()


if __name__ == "__main__":
    raise SystemExit(main())
