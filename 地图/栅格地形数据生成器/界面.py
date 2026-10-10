# -*- coding: utf-8 -*-
"""界面.py —— 栅格地形数据生成器的**可视化入口**（tkinter，只用标准库）。

    python 界面.py         # 或双击 生成地形.bat

它做四件事，对应界面的四块：

  ┌──────────────────────────────────────────────────────────────────────────┐
  │ ① 参数    管线参数（格边长、跳过的步骤、河网密度）＋ 规则门槛（形态三个数…）│
  │ ② 阶段    管线阶段表：勾掉不想跑的、跑起来后每行的耗时与状态会亮          │
  │ ③ 日志    子进程的实时输出（一行不落，出错的 traceback 也在里面）          │
  │ ④ 产物    跑完后的文件清单（大小 + 打开目录）                             │
  └──────────────────────────────────────────────────────────────────────────┘

⚠️ **为什么把生成跑在子进程里**（`subprocess.Popen` 调 `生成.py`）：
   · tkinter 与 numpy/多进程不对付，同进程跑会把界面冻住（一冻就是 90 秒）；
   · 子进程与界面**完全解耦** —— 界面可以关掉，管线照跑；命令行参数与界面走的是同一个
     `参数.py`，两条路不会分叉（界面上改的参数就是 `生成.py` 的 argv）。
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 契约 as Q                                                    # noqa: E402
from 参数 import 管线参数, 规则门槛, 做命令行, 读JSON, 存JSON          # noqa: E402

记忆文件 = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".参数记忆.json")


def 阶段清单():
    """→ `[(名称, 说明)]`。**从 管线.py 的阶段表读**（别在界面上另抄一份）。"""
    import 管线
    return [(s["名称"], s["说明"], s["跳过"]) for s in 管线.阶段]


class 生成界面:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.进程: subprocess.Popen | None = None
        self.队列: queue.Queue[str] = queue.Queue()
        self.参数 = 读JSON(记忆文件) or 管线参数()
        self.门槛控件: dict[str, tk.Variable] = {}
        self.阶段行: dict[str, tuple] = {}
        root.title("逐鹿 · 栅格地形数据生成器")
        root.geometry("1080x760")
        self._搭界面()
        self._载入参数()
        self.root.after(80, self._抽日志)

    # ---------------------------------------------------------------- 界面
    def _搭界面(self):
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="栅格地形数据生成器", font=("", 13, "bold")).pack(side="left")
        self.提示 = ttk.Label(top, text="", foreground="#8a6d00")
        self.提示.pack(side="left", padx=12)
        self.按钮 = ttk.Button(top, text="开始生成", command=self._开始)
        self.按钮.pack(side="right")
        ttk.Button(top, text="打开产物目录", command=self._打开产物).pack(side="right", padx=6)

        mid = ttk.Frame(self.root, padding=(10, 0))
        mid.pack(fill="both", expand=True)
        # 左：参数；右：阶段
        左 = ttk.LabelFrame(mid, text="参数", padding=8)
        左.pack(side="left", fill="y")
        右 = ttk.LabelFrame(mid, text="阶段（顺序即语义；勾掉的整步跳过）", padding=8)
        右.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self._参数区(左)
        self._阶段区(右)

        下 = ttk.LabelFrame(self.root, text="日志", padding=6)
        下.pack(fill="both", expand=True, padx=10, pady=(8, 10))
        self.日志 = tk.Text(下, height=16, wrap="none", font=("Consolas", 9), bg="#12161c",
                            fg="#cfd6df", insertbackground="#cfd6df")
        sb = ttk.Scrollbar(下, command=self.日志.yview)
        self.日志.configure(yscrollcommand=sb.set, state="disabled")
        self.日志.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _参数区(self, box):
        r = 0
        ttk.Label(box, text="管线参数", font=("", 10, "bold")).grid(row=r, column=0, sticky="w", pady=(0, 4))
        r += 1
        self.格边长 = tk.StringVar()
        ttk.Label(box, text="格边长（度）").grid(row=r, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.格边长, width=18).grid(row=r, column=1, sticky="w")
        r += 1
        self.河网门槛 = tk.StringVar()
        ttk.Label(box, text="河网流量门槛 (m³/s)").grid(row=r, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.河网门槛, width=18).grid(row=r, column=1, sticky="w")
        r += 1
        self.不读覆盖 = tk.BooleanVar()
        ttk.Checkbutton(box, text="不读土地覆盖（只剩海陆两档，快）",
                        variable=self.不读覆盖).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self.只出地块 = tk.BooleanVar()
        ttk.Checkbutton(box, text="只出地块层（不读高程）",
                        variable=self.只出地块).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 2

        ttk.Label(box, text="规则门槛（⚠️ 改了就**不再是契约产品**）",
                  font=("", 10, "bold")).grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 4))
        r += 1
        门槛说明 = [
            ("山地起伏", "起伏 > 此值 → 山地（adr/0013）"),
            ("丘陵起伏", "起伏 > 此值 → 丘陵"),
            ("高原海拔", "海拔 > 此值且起伏小 → 高原"),
            ("高原起伏上限", "高原的起伏上限"),
            ("沙占比", "GSDP30 有沙占比 ≥ 此值 → 沙质裸地（adr/0012）"),
            ("盐盘占比", "GLWD-3 盐盘占比 ≥ 此值 → 盐漠（adr/0014）"),
            ("水体占比", "格内水占比 ≥ 此值 → 算水"),
            ("湖岸收口上限格", "「海洋」块大于它当海（adr/0014）"),
            ("盐田距海格", "沿海盐田：距真海 ≤ 此值"),
            ("海冰频率", "30 个 3 月里的结冰比例（1.0 = 常年）"),
            ("海冰最低纬度", "只判这条线以北"),
        ]
        for 名, 说 in 门槛说明:
            v = tk.StringVar()
            self.门槛控件[名] = v
            ttk.Label(box, text=名).grid(row=r, column=0, sticky="w")
            ttk.Entry(box, textvariable=v, width=18).grid(row=r, column=1, sticky="w")
            v.trace_add("write", self._查门槛)          # 一改就检查"是不是还等于契约值"
            self._提示条(box, r, 2, 说)
            r += 1
        self.接回沙砾 = tk.BooleanVar()
        ttk.Checkbutton(box, text="干湖床接回沙/砾裸地", variable=self.接回沙砾).grid(
            row=r, column=0, columnspan=2, sticky="w"); r += 1
        self.接回草地 = tk.BooleanVar()
        ttk.Checkbutton(box, text="干湖床接回草甸/草原", variable=self.接回草地).grid(
            row=r, column=0, columnspan=2, sticky="w"); r += 1
        ttk.Button(box, text="恢复契约默认", command=self._恢复默认).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=6)

    def _提示条(self, box, r, c, text):
        lb = ttk.Label(box, text=text, foreground="#777", font=("", 8))
        lb.grid(row=r, column=c, sticky="w", padx=6)

    def _阶段区(self, box):
        ttk.Label(box, text="管线按这张表跑（`管线.py` 的 阶段表）：", foreground="#555").pack(anchor="w")
        for i, (名, 说明, 跳过) in enumerate(阶段清单(), 1):
            row = ttk.Frame(box)
            row.pack(fill="x", pady=1)
            chk = tk.BooleanVar(value=True)
            ttk.Checkbutton(row, text=f"{i}. {名}", variable=chk).pack(side="left")
            st = ttk.Label(row, text="·", width=12, foreground="#999")
            st.pack(side="right")
            ttk.Label(row, text=说明, foreground="#666", font=("", 8)).pack(side="left", padx=8)
            self.阶段行[名] = (chk, st, 跳过)

    # ---------------------------------------------------------------- 参数读写
    def _载入参数(self):
        p = self.参数
        self.格边长.set(repr(p.cell)); self.河网门槛.set(repr(p.river_min))
        self.不读覆盖.set(p.no_veg); self.只出地块.set(p.no_terrain)
        for 名, v in self.门槛控件.items():
            v.set(repr(getattr(p.门槛, 名)))
        self.接回沙砾.set(p.门槛.干湖床接回沙砾); self.接回草地.set(p.门槛.干湖床接回草甸草原)
        self._查门槛()

    def _读参数(self) -> 管线参数:
        m = {}
        for 名, v in self.门槛控件.items():
            raw = v.get().strip()
            m[名] = int(float(raw)) if 名 in ("湖岸收口上限格", "盐田距海格") else float(raw)
        m["干湖床接回沙砾"] = bool(self.接回沙砾.get())
        m["干湖床接回草甸草原"] = bool(self.接回草地.get())
        return 管线参数(cell=float(self.格边长.get()), river_min=float(self.河网门槛.get()),
                        no_veg=bool(self.不读覆盖.get()), no_terrain=bool(self.只出地块.get()),
                        门槛=规则门槛(**m))

    def _恢复默认(self):
        self.参数 = self.参数.__class__(cell=self.参数.cell, river_min=self.参数.river_min,
                                     no_veg=self.参数.no_veg, no_terrain=self.参数.no_terrain)
        self._载入参数()

    def _查门槛(self, *_: object):
        try:
            diff = self._读参数().门槛.与契约值有别()
        except Exception:                                                     # noqa: BLE001
            self.提示.configure(text="参数读不出来（有非数字？）", foreground="#a33")
            return
        self.提示.configure(
            text=("⚠️ 规则门槛已改：" + "、".join(diff) + " —— 产物不算契约产品")
            if diff else "", foreground="#8a6d00")

    # ---------------------------------------------------------------- 跑
    def _开始(self):
        if self.进程 and self.进程.poll() is None:
            self.进程.terminate()
            self._写("… 已请求中断\n")
            self.按钮.configure(text="开始生成")
            return
        try:
            p = self._读参数()
        except Exception as e:                                                # noqa: BLE001
            messagebox.showerror("参数读不出来", str(e)); return
        存JSON(p, 记忆文件)
        argv = [sys.executable, "-u", os.path.join(os.path.dirname(os.path.abspath(__file__)), "生成.py")]
        argv += 做命令行(p)
        self.日志.configure(state="normal"); self.日志.delete("1.0", "end")
        self.日志.configure(state="disabled")
        for 名, (chk, st, _) in self.阶段行.items():
            st.configure(text="·", foreground="#999")
        self._写("$ python 生成.py " + " ".join(argv[3:]) + "\n\n")
        self.进程 = subprocess.Popen(argv, cwd=os.path.dirname(os.path.abspath(__file__)),
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._读进程, args=(self.进程,), daemon=True).start()
        self.按钮.configure(text="中断")

    def _读进程(self, proc):
        for line in proc.stdout:                                              # type: ignore[union-attr]
            self.队列.put(line)
        self.队列.put(f"\n（进程退出，返回码 {proc.wait()}）\n")

    def _抽日志(self):
        try:
            while True:
                line = self.队列.get_nowait()
                self._写(line)
                self._认阶段(line)
        except queue.Empty:
            pass
        self.root.after(80, self._抽日志)

    def _写(self, s: str):
        self.日志.configure(state="normal")
        self.日志.insert("end", s)
        self.日志.see("end")
        self.日志.configure(state="disabled")

    def _认阶段(self, line: str):
        """`[3/6] 气候与派生 —— …` / `[3/6] 气候与派生 完成（0.9 s）` → 点亮那一行。"""
        if not line.startswith("[") or "]" not in line:
            return
        head, _, rest = line[1:].partition("]")
        if "/" not in head:
            return
        idx = int(head.split("/")[0])
        for i, (名, (chk, st, _)) in enumerate(self.阶段行.items(), 1):
            if i != idx:
                continue
            if "完成" in rest:
                st.configure(text=rest.split("（")[-1].rstrip("）\n"), foreground="#2a7a2a")
                if i == len(self.阶段行):
                    self.按钮.configure(text="开始生成")
            elif "跳过" in rest:
                st.configure(text="跳过", foreground="#999")
            else:
                st.configure(text="跑…", foreground="#1a5fa8")

    def _打开产物(self):
        p = os.path.dirname(Q.OUT)
        try:
            os.startfile(p)                                                   # type: ignore[attr-defined]
        except Exception:                                                     # noqa: BLE001
            subprocess.Popen(["explorer", p])


def main() -> int:
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.25)
    except Exception:                                                         # noqa: BLE001
        pass
    生成界面(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
