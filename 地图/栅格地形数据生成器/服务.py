# -*- coding: utf-8 -*-
"""服务.py —— 生成器的**网页前端**（stdlib 起一个本地服务，浏览器里就是那个界面）。

    python 服务.py            # 起服务并打开浏览器（双击 生成地形.bat 走的就是这条路）

为什么不用 tkinter 而改成网页（2026-10-10 需求方定）：参数表有二十来项、阶段有六步、
日志要一直滚 —— 这些东西在 tkinter 里排版挤、字号小、没法贴代码；网页上一屏能放完，
而且"数据一键下载"要有进度条与分组状态，那是网页的强项。tkinter 那版（`界面.py`）留着当
**离线兜底**（`run.py --桌面`），两者读的是同一份 `参数.py`，不会分叉。

约定：
  · **一个进程一个活**：跑管线与下载数据互斥（都是重活，且都会写 地图数据/），同时来第二件
    返回 409，前端把它显示成一句提示。
  · **日志走 SSE**（`/api/流`），带序号，页面刷新后能从 `?from=N` 补上错过的行。
  · 子进程都是 `[sys.executable, -u, <脚本>, ...]`，工作目录 = 本目录，输出按行读。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote_to_bytes, urlparse

这里 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 这里)

import 契约 as Q                                                     # noqa: E402
import 参数 as P                                                     # noqa: E402
import 管线                                                          # noqa: E402
import fetch_map_data as FETCH                                       # noqa: E402

网页目录 = os.path.join(这里, "网页")
记忆文件 = os.path.join(这里, ".参数记忆.json")
端口起点 = 8780                # 编辑器（serve.py）占 8770，这里从 8780 起错开
端口数 = 20


class 服务(ThreadingHTTPServer):
    """⚠️ `allow_reuse_address` 默认是 1，在 Windows 上 SO_REUSEADDR **不禁重复绑定** ——
    两个进程能同时"绑上"同一个端口，后绑的那个悄悄接管全部连接（踩过：我的服务明明报
    "起于 8770"，回的却是编辑器那边的页面）。关掉它，端口被占就老老实实 OSError 往上抛，
    由 main() 往后试下一个。
    """
    allow_reuse_address = False
    daemon_threads = True

# ================================================================ 一个活（跑管线 / 取数据）
class 会话:
    """当前在跑的那个子进程 ＋ 它的日志。**一次只有一个**（见文件头）。"""

    def __init__(self):
        self.进程: subprocess.Popen | None = None
        self.标题 = ""
        self.日志: list[str] = []
        self.锁 = threading.Lock()
        self.起于 = 0.0
        self.返回码: int | None = None

    def 忙(self) -> bool:
        return self.进程 is not None and self.进程.poll() is None

    def 起(self, 标题: str, argv: list[str]) -> bool:
        if self.忙():
            return False
        self.标题 = 标题
        self.日志 = []
        self.返回码 = None
        self.起于 = time.time()
        self.进程 = subprocess.Popen(argv, cwd=这里, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._读, daemon=True).start()
        return True

    def _读(self):
        assert self.进程 and self.进程.stdout
        for line in self.进程.stdout:
            with self.锁:
                self.日志.append(line.rstrip("\n"))
        code = self.进程.wait()
        with self.锁:
            self.返回码 = code
            self.日志.append(f"（进程退出，返回码 {code}）")

    def 快照(self, 从: int) -> dict:
        with self.锁:
            return {"标题": self.标题, "行": self.日志[从:], "下一行": len(self.日志),
                    "运行中": self.忙(), "返回码": self.返回码,
                    "已跑秒": round(time.time() - self.起于, 1) if self.起于 else 0}

    def 停(self):
        if self.忙():
            self.进程.terminate()


会话 = 会话()


def _参数快照() -> dict:
    """→ 上次用的那套参数（没有就用契约默认），展平成前端好读的形状。"""
    p = P.读JSON(记忆文件) or P.管线参数()
    d = dict(p.__dict__)
    d["门槛"] = dict(p.门槛.__dict__)
    return d


def 数据组状态() -> list[dict]:
    """→ 每个数据组的本地状态（有几个文件、几项已就绪、共多少字节、缺多少）。"""
    组: dict[str, dict] = {}
    for it in FETCH.ITEMS:
        g = it[0]
        d = 组.setdefault(g, {"组": g, "项": 0, "有": 0, "缺": 0, "残": 0, "字节": 0, "说明": it[5]})
        d["项"] += 1
        st = FETCH.state(it)
        d["有" if st == "有" else ("缺" if st == "缺" else "残")] += 1
        d["字节"] += it[4] or 0
    order = ["core", "basins", "modern", "foreign", "climate", "rivers", "soil", "ice", "lake",
             "volcano"]
    return [组[g] for g in order if g in 组]


def 产物清单() -> list[dict]:
    import hashlib
    out = []
    for d in (Q.OUT, Q.RUN_DIR):
        if not os.path.isdir(d): continue
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if not os.path.isfile(p) or fn.endswith(".npy"): continue
            h = hashlib.md5()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out.append({"名": fn, "目录": os.path.basename(d), "字节": os.path.getsize(p),
                        "时间": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
                        "md5": h.hexdigest()[:12]})
    return out


# ================================================================ HTTP
class 处理(BaseHTTPRequestHandler):
    server_version = "ZhuluTerrain/1.0"

    def log_message(self, fmt, *args):                                   # noqa: A003
        pass                                                             # 别把每个请求都喷到控制台

    # ---- 工具
    def _发(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._发(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                 "application/json; charset=utf-8")

    def _文本(self, s: str, code: int = 200):
        self._发(code, s.encode("utf-8"), "text/plain; charset=utf-8")

    def _体(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n: return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:                                                 # noqa: BLE001
            return {}

    @staticmethod
    def _路径(raw: str) -> tuple[str, dict]:
        """把请求行里的路径还原成明文（＋查参数）。

        三层编码坑，缺一层就永远 404（都踩过，最后是**实测**打出来的，不是猜的）：
          ① `BaseHTTPRequestHandler` 按 **latin-1** 解请求行（HTTP 规定），裸 UTF-8 的
             `/api/会话` 到这里已经是乱码 —— 得 `latin-1 编回字节`才算拿到原始字节；
          ② 路径可能被**百分号编码**，要 `unquote_to_bytes`；
          ③ **编码不一定是 UTF-8**：浏览器发 UTF-8，而 Windows 中文控制台里的 curl 发的是
             **GBK**（实测 `/api/会话` → `%BB%E1%BB%B0`）。所以按字节还原之后要**逐个试
             编码**，UTF-8 解不通再退 GBK。

        关键是把三步拆开：**百分比还原永远在字节层做，编码判断放在最后**——若先按某一种
        编码把字符串 unquote 掉，另一种就永远解不出来。
        """
        u = urlparse(raw)
        b = unquote_to_bytes(u.path.encode("latin-1", "replace"))
        for enc in ("utf-8", "gbk"):
            try:
                p = b.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            p = b.decode("utf-8", "replace")
        return p, parse_qs(u.query)

    def _静态(self, path: str):
        # path 到这里**已经解过码**（`_路径` 干的），这里再 unquote 一次会把文件名里的
        # 合法 `%` 解坏，所以只用它、不还原。
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        p = os.path.normpath(os.path.join(网页目录, rel))
        if os.path.commonpath([os.path.abspath(p), 网页目录]) != 网页目录 \
                or not os.path.isfile(p):
            return self._文本("404", 404)
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon"}.get(
                     os.path.splitext(p)[1], "application/octet-stream")
        self._发(200, io.open(p, "rb").read(), ctype)

    def handle_one_request(self):
        """一个请求出岔子只回 500，**别把连接直接掐了**——掐了浏览器只看到"连接被重置"，
        什么线索都没有（踩过：`unquote` 没导入，前端表现为"页面白屏"）。"""
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as e:                                            # noqa: BLE001
            import traceback
            traceback.print_exc(file=sys.stderr)
            try:
                self._文本(f"服务端出错：{type(e).__name__}: {e}", 500)
            except Exception:                                             # noqa: BLE001
                pass

    # ---- 路由
    def do_GET(self):                                                    # noqa: N802
        path, q = self._路径(self.path)
        if path == "/api/会话":
            return self._json({
                "阶段": [{"名": s["名称"], "说明": s["说明"], "跳过": s["跳过"]} for s in 管线.阶段],
                "契约门槛": P.规则门槛().__dict__,
                "参数": _参数快照(),
                "数据组": 数据组状态(),
                "产物目录": Q.OUT,
                "运行中": 会话.快照(0)["运行中"],
            })
        if path == "/api/流":
            return self._流(int(q.get("from", ["0"])[0]))
        if path == "/api/产物":
            return self._json({"产物": 产物清单()})
        return self._静态(path)

    def do_POST(self):                                                   # noqa: N802
        path, _q = self._路径(self.path)
        b = self._体()
        if path == "/api/跑":
            p = P.管线参数(**{k: v for k, v in (b.get("参数") or {}).items()
                            if k in P.管线参数.__dataclass_fields__ and k != "门槛"},
                          门槛=P.规则门槛(**{k: v for k, v in ((b.get("参数") or {}).get("门槛") or {}).items()
                                          if k in P.规则门槛.__dataclass_fields__}))
            P.存JSON(p, 记忆文件)
            argv = [sys.executable, "-u", os.path.join(这里, "生成.py")] + P.做命令行(p)
            if not 会话.起("生成栅格地形", argv):
                return self._json({"错": "已经有一件活在跑（等它结束，或先中断）"}, 409)
            return self._json({"好": True})
        if path == "/api/取数":
            组 = (b.get("组") or "core")
            argv = [sys.executable, "-u", os.path.join(这里, "fetch_map_data.py"), "--group", 组]
            if not 会话.起(f"下载数据 · {组}", argv):
                return self._json({"错": "已经有一件活在跑（等它结束，或先中断）"}, 409)
            return self._json({"好": True})
        if path == "/api/停":
            会话.停()
            return self._json({"好": True})
        if path == "/api/打开目录":
            try:
                os.startfile(Q.OUT)                                       # type: ignore[attr-defined]
            except Exception:                                             # noqa: BLE001
                subprocess.Popen(["explorer", Q.OUT])
            return self._json({"好": True})
        if path == "/api/自检":
            argv = [sys.executable, "-u", os.path.join(这里, "check_terrain.py"), "--all"]
            if not 会话.起("底图自检 check_terrain", argv):
                return self._json({"错": "已经有一件活在跑"}, 409)
            return self._json({"好": True})
        return self._json({"错": "没有这个接口"}, 404)

    # ---- SSE
    def _流(self, 从: int):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        n = 从
        空转 = 0
        try:
            while True:
                s = 会话.快照(n)
                for line in s["行"]:
                    self.wfile.write(f"data: {json.dumps(line, ensure_ascii=False)}\n\n"
                                     .encode("utf-8"))
                    n += 1
                self.wfile.write(f"event: 状态\ndata: {json.dumps({'运行中': s['运行中'], '行数': n, '标题': s['标题'], '返回码': s['返回码'], '已跑秒': s['已跑秒']}, ensure_ascii=False)}\n\n"
                                 .encode("utf-8"))
                self.wfile.flush()
                if s["行"]:
                    空转 = 0
                else:
                    空转 += 1
                    if not s["运行中"] and 空转 > 2:      # 活干完了、也没新行 → 收尾
                        self.wfile.write("event: 完\ndata: {}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        return
                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> int:
    port = 端口起点
    srv = None
    for _ in range(端口数):
        try:
            srv = 服务(("127.0.0.1", port), 处理)
            break
        except OSError:
            port += 1
    if srv is None:
        print(f"端口 {端口起点}–{端口起点 + 端口数 - 1} 都被占了，起不来。", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{port}/"
    print(f"栅格地形数据生成器 · 网页界面：{url}", flush=True)
    print(f"  产物目录 {Q.OUT}", flush=True)
    print("  （Ctrl+C 关掉服务；关掉这个窗口界面也就打不开了）", flush=True)
    try:
        webbrowser.open(url)
    except Exception:                                                     # noqa: BLE001
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        if 会话.忙():
            会话.停()
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
