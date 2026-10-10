# -*- coding: utf-8 -*-
"""合成.py：把实机产物截图与奶龙旁白合成宣传片。

    python 合成.py

画面全部来自实机产物，没有一张是画的（封面、布局、许可、尾卡四张说明卡除外，
那四张的文字是设计稿，底图仍取自实机截屏）：
  · 编辑器四层截屏（样式、覆盖、形态、气候，都是真跑出来的颜色与图例）
  · 编辑器放大到咸海的截屏（悬停读数写着咸湖、平原、温带、干旱，60°E 44.9°N）
  · 生成器网页截屏（参数、六步阶段、日志里那次真下载的进度）

音频是 `配音.py` 用本机 index-tts ＋ 奶龙音色合成的 `配音/句NN.wav`；
本脚本按 `配音/时长.json` 把每句配到对应画面上（句前句后各留 0.35 s 气口）。

每帧右上角常驻一行小字：个人项目延伸产物，仅供学习，禁止商用。
需求方要求整片都能看出性质，不只结尾打一行。

两处经验写在这里：
其一，静图送进 zoompan 必须显式写 `-framerate 30`。默认是 25 fps，输出是 30 fps，
   每段悄悄短掉六分之一（整片 98 s 变 82 s）。末尾有一道时长断言兜着。
其二，不要预先裁剪再放大。曾把 530 px 宽的图例裁出来拉到 1920 宽，3.6 倍上采样，糊成一团。
   改成给 zoompan 一个目标点，只在原图上放大 1.2–1.5 倍，字还是清的。

依赖 Pillow（卡片与字幕条，避开 drawtext 的中文转义坑）＋ ffmpeg（zoompan ＋ overlay）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import wave

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

这里 = os.path.dirname(os.path.abspath(__file__))
素材 = os.path.join(这里, "素材")
配音目录 = os.path.join(这里, "配音")
场景目录 = os.path.join(这里, "场景")
片名 = os.path.join(这里, "《逐鹿》栅格地形管线·宣传片.mp4")

W, H, FPS = 1920, 1080, 30
气口 = 0.35                        # 每句前后的静音
开场留白 = 1.2                     # 封面多留一点
常驻小字 = "个人项目延伸产物，仅供学习，禁止商用"

字体粗 = r"C:\Windows\Fonts\msyhbd.ttc"
字体细 = r"C:\Windows\Fonts\msyh.ttc"
墨 = (18, 20, 24)
纸 = (243, 241, 236)
灰 = (152, 157, 164)
强调 = (222, 172, 96)

# 编辑器截屏里画布那一块。量过，整块 99.9% 不是白底，即全是地图，不含侧栏与顶栏。
# 说明卡拿它当底图，比把整个界面压暗好看。界面里大片是白底，压到 38% 还是灰的。
画布 = {"编辑器_样式.png": (258, 160, 1292, 852),
        "编辑器_咸湖_样式.png": (258, 160, 1292, 852)}


def 字(粗: bool, 号: int):
    return ImageFont.truetype(字体粗 if 粗 else 字体细, 号)


def 满幅(im: Image.Image) -> Image.Image:
    """居中裁成 16:9 再放到 1920×1080。"""
    比 = im.width / im.height
    if 比 > W / H:
        新w = int(im.height * W / H)
        im = im.crop(((im.width - 新w) // 2, 0, (im.width + 新w) // 2, im.height))
    else:
        新h = int(im.width * H / W)
        im = im.crop((0, (im.height - 新h) // 2, im.width, (im.height + 新h) // 2))
    return im.resize((W, H), Image.LANCZOS)


def 压暗(im: Image.Image, 系数: float) -> Image.Image:
    """按亮度压暗。往黑里 blend 会把白色拉成灰，亮度乘法才是真的暗下去。"""
    return ImageEnhance.Brightness(im).enhance(系数)


def 地图底(名: str, 系数: float) -> Image.Image:
    return 压暗(满幅(Image.open(os.path.join(素材, 名)).convert("RGB").crop(画布[名])), 系数)


# ------------------------------------------------------------------ 说明卡
def 卡_封面() -> Image.Image:
    im = 地图底("编辑器_样式.png", 0.42)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 372), "《逐鹿》", font=字(True, 156), fill=纸, anchor="mm")
    d.text((W // 2, 522), "栅格地形管线", font=字(True, 100), fill=纸, anchor="mm")
    d.line([(W // 2 - 310, 612), (W // 2 + 310, 612)], fill=强调, width=3)
    d.text((W // 2, 686), "覆盖 × 形态 × 气候，合成样式", font=字(False, 52), fill=(206, 210, 216), anchor="mm")
    d.text((W // 2, 756), "3819 × 2472 格，944 万像元，一格约 5.86 km",
           font=字(False, 38), fill=灰, anchor="mm")
    d.text((W // 2, 866), "个人项目延伸产物，仅供学习，禁止商用",
           font=字(True, 42), fill=强调, anchor="mm")
    return im


def 卡_字节() -> Image.Image:
    """布局卡：一格一个字节长什么样（覆盖 5 位 ＋ 形态 3 位），气候另存一张。

    文字全部排在 y<900 以上。字幕条占底部 y≈933 至 1035，压上去就叠字了。
    """
    im = Image.new("RGB", (W, H), 墨)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 150), "每一格，只用一个字节", font=字(True, 78), fill=纸, anchor="mm")
    d.text((W // 2, 232), "一个字节 = 地形；覆盖与形态合起来才叫地形", font=字(False, 36), fill=灰, anchor="mm")

    x0, y0, 格宽, 格高 = 372, 344, 148, 150
    for i, (名, 位, 释, 色) in enumerate([
            ("覆盖", "5 位", "海洋、湖泊、密林、草原、\n沙质裸地、咸湖等，共 20 类", 强调),
            ("形态", "3 位", "平原、丘陵、高原、山地\n共 4 类", (132, 180, 218))]):
        数 = 5 if i == 0 else 3
        x = x0 + i * (格宽 * 5 + 56)
        for b in range(数):
            bx = x + b * 格宽
            d.rectangle([bx, y0, bx + 格宽 - 6, y0 + 格高],
                        fill=色 if b == 0 else tuple(int(c * 0.42) for c in 色))
        d.text((x + (格宽 * 数) // 2, y0 - 54), f"{名}（{位}）", font=字(True, 48), fill=纸, anchor="mm")
        for j, line in enumerate(释.split("\n")):
            d.text((x, y0 + 格高 + 42 + j * 46), line, font=字(False, 30), fill=灰)

    d.line([(372, 700), (W - 372, 700)], fill=(66, 70, 76), width=2)
    d.text((W // 2, 768), "气候另存一张图：热量带 4 档，干湿 8 档，与地形是两张图",
           font=字(False, 38), fill=(202, 206, 212), anchor="mm")
    d.text((W // 2, 856), "三根轴一交叉，得到 88 个显示类",
           font=字(True, 44), fill=强调, anchor="mm")
    return im


def 卡_许可() -> Image.Image:
    im = Image.new("RGB", (W, H), 墨)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 172), "许可", font=字(True, 86), fill=纸, anchor="mm")
    d.line([(W // 2 - 150, 240), (W // 2 + 150, 240)], fill=强调, width=3)
    行 = [("这是个人项目的延伸产物", 纸, True),
          ("为一个自己的世界观服务，不隶属任何公司、机构或组织", 灰, False),
          ("仅供学习交流    禁止商用", 强调, True),
          ("再分发须署名，以相同方式共享，并标明改动", 灰, False),
          ("上游数据各有各的许可：GADM 非商用，", (198, 202, 208), False),
          ("HydroRIVERS 与 HydroBASINS、GLWD 不许作独立数据产品再分发", (198, 202, 208), False),
          ("完整条款见仓库根目录的 LICENSE 与 地图数据/说明.md 第三节", 灰, False)]
    y = 340
    for 文, 色, 粗 in 行:
        d.text((W // 2, y), 文, font=字(粗, 46 if 粗 else 34), fill=色, anchor="mm")
        y += 82 if 粗 else 64
    return im


def 卡_尾() -> Image.Image:
    im = 地图底("编辑器_咸湖_样式.png", 0.46)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 366), "逐鹿", font=字(True, 156), fill=纸, anchor="mm")
    d.text((W // 2, 498), "栅格地形管线，只读视图层编辑器", font=字(False, 42), fill=(206, 210, 216), anchor="mm")
    d.text((W // 2, 634), "github.com/Yabuki0707/zhulu", font=字(False, 40), fill=强调, anchor="mm")
    d.text((W // 2, 700), "github.com/Yabuki0707/zhulu-map-editor", font=字(False, 40), fill=强调, anchor="mm")
    d.text((W // 2, 848), "个人项目延伸产物，仅供学习，禁止商用", font=字(True, 42), fill=纸, anchor="mm")
    return im


卡表 = {"封面": 卡_封面, "字节": 卡_字节, "许可": 卡_许可, "尾": 卡_尾}
卡号 = {1: "封面", 3: "字节", 13: "许可", 14: "尾"}


# ------------------------------------------------------------------ 字幕条
def 画字幕(文: str) -> Image.Image:
    """整幅 1920×1080 的透明层：底部字幕 ＋ 右上角常驻小字。

    为什么不用 ffmpeg 的 drawtext：中文要转义冒号逗号引号，路径还要转义盘符，
    一次没转对就是花屏；Pillow 画成 PNG 再 overlay，零转义、样式也好调。
    """
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = 字(True, 46)
    框 = d.textbbox((0, 0), 文, font=f)
    宽, 高 = 框[2] - 框[0], 框[3] - 框[1]
    cx, cy = W // 2, H - 96
    d.rounded_rectangle([cx - 宽 // 2 - 34, cy - 高 // 2 - 20, cx + 宽 // 2 + 34, cy + 高 // 2 + 20],
                        radius=14, fill=(10, 11, 14, 196))
    d.text((cx + 2, cy + 2), 文, font=f, fill=(0, 0, 0, 150), anchor="mm")
    d.text((cx, cy), 文, font=f, fill=(246, 246, 246, 255), anchor="mm")

    f2 = 字(False, 26)
    框2 = d.textbbox((0, 0), 常驻小字, font=f2)
    d.text((W - 44 - (框2[2] - 框2[0]), 38), 常驻小字, font=f2, fill=(255, 255, 255, 130))
    return im


# ------------------------------------------------------------------ 场景表
# (号, 配图 或 None=说明卡, 效果, 目标点 x, 目标点 y, 推到底的倍数)
# 目标点是归一化坐标，0 是最左或最上，1 是最右或最下。推近时视窗收拢到它附近。
场景 = [
    (1,  None,                 "静",   0.50, 0.50, 1.00),
    (2,  "编辑器_形态.png",      "推近", 0.50, 0.50, 1.18),
    (3,  None,                 "静",   0.50, 0.50, 1.00),
    (4,  "编辑器_覆盖.png",      "推近", 0.055, 0.48, 1.55),  # 左栏：20 类覆盖的色块与占比
    (5,  "编辑器_样式.png",      "推近", 0.050, 0.48, 1.62),  # 左栏：88 个显示类的名字与配色
    (6,  "编辑器_咸湖_样式.png",  "右移", 0.50, 0.50, 1.20),
    (7,  "编辑器_气候.png",      "推近", 0.50, 0.46, 1.20),
    (8,  "编辑器_咸湖_覆盖.png",  "推近", 0.30, 0.44, 1.52),   # 咸海那一片水 ＋ 悬停读数
    (9,  "生成器网页.png",       "推近", 0.76, 0.34, 1.50),   # 右栏：六步阶段表
    (10, "生成器网页.png",       "左移", 0.50, 0.50, 1.20),
    (11, "生成器网页.png",       "推近", 0.52, 0.82, 1.45),   # 下半：日志里那次真下载
    (12, "编辑器_样式.png",      "右移", 0.50, 0.50, 1.25),
    (13, None,                 "静",   0.50, 0.50, 1.00),
    (14, None,                 "静",   0.50, 0.50, 1.00),
]


def 推拉表(效果: str, 帧数: int, fx: float, fy: float, zmax: float) -> str:
    """→ zoompan 的 z/x/y 表达式（输入输出都是 1920×1080）。"""
    g = max(帧数 - 1, 1)
    夹x = f"max(0\\,min({fx}*iw-(iw/zoom)/2\\,iw-iw/zoom))"
    夹y = f"max(0\\,min({fy}*ih-(ih/zoom)/2\\,ih-ih/zoom))"
    if 效果 == "推近":
        return f"z='1+{zmax - 1:.4f}*on/{g}':x='{夹x}':y='{夹y}'"
    if 效果 == "拉远":
        return f"z='{zmax}-{zmax - 1:.4f}*on/{g}':x='{夹x}':y='{夹y}'"
    if 效果 == "左移":                      # 画面往左走 = 视窗往右挪
        return (f"z='{zmax}':x='(iw-iw/zoom)*on/{g}':y='{夹y}'")
    if 效果 == "右移":
        return (f"z='{zmax}':x='(iw-iw/zoom)*(1-on/{g})':y='{夹y}'")
    return "z='1.0005':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"      # 静：几乎不动


def 跑(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("ffmpeg 失败：", " ".join(cmd[:8]), "⋯⋯")
        print((p.stderr or "")[-2500:])
        raise SystemExit(1)


def 拼音频(句: list[dict]) -> tuple[str, list[float]]:
    """按“气口 ＋ 句 ＋ 气口”把各句拼成一条音轨，并返回每段时长，即画面上每段该多长。"""
    out = os.path.join(这里, "旁白_整条.wav")
    时长 = []
    with wave.open(os.path.join(配音目录, "句01.wav")) as f:
        sr, ch, sw = f.getframerate(), f.getnchannels(), f.getsampwidth()
    每帧字节 = sr * sw * ch
    片 = []
    for i in range(1, len(句) + 1):
        with wave.open(os.path.join(配音目录, f"句{i:02d}.wav")) as f:
            assert (f.getframerate(), f.getnchannels(), f.getsampwidth()) == (sr, ch, sw), "各句格式不一致"
            data = f.readframes(f.getnframes())
        before = b"\x00" * int(每帧字节 * (开场留白 if i == 1 else 气口))
        after = b"\x00" * int(每帧字节 * 气口)
        片 += [before, data, after]
        时长.append((len(before) + len(data) + len(after)) / 每帧字节)
    with wave.open(out, "wb") as f:
        f.setnchannels(ch); f.setsampwidth(sw); f.setframerate(sr)
        f.writeframes(b"".join(片))
    print(f"音轨：{os.path.basename(out)}  {sum(时长):.1f} s  {sr} Hz")
    return out, 时长


def main() -> int:
    时长文件 = os.path.join(配音目录, "时长.json")
    if not os.path.isfile(时长文件):
        print("没有 配音/时长.json，先跑 python 配音.py", file=sys.stderr)
        return 2
    os.makedirs(场景目录, exist_ok=True)
    表 = json.load(open(时长文件, encoding="utf-8"))
    句 = [表[f"句{i:02d}"] for i in range(1, len(表) + 1)]

    音轨, 时长 = 拼音频(句)

    print(f"渲染 {len(场景)} 段⋯⋯")
    段 = []
    for (号, 图名, 效果, fx, fy, zmax), 秒 in zip(场景, 时长):
        底 = 卡表[卡号[号]]() if 图名 is None else 满幅(Image.open(os.path.join(素材, 图名)).convert("RGB"))
        帧数 = max(int(round(秒 * FPS)), 1)
        底.save(os.path.join(场景目录, f"底_{号:02d}.png"))
        画字幕(句[号 - 1]["文本"]).save(os.path.join(场景目录, f"字_{号:02d}.png"))
        out = os.path.join(场景目录, f"场{号:02d}.mp4")
        跑(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{秒:.3f}",
             "-i", os.path.join(场景目录, f"底_{号:02d}.png"),
             "-i", os.path.join(场景目录, f"字_{号:02d}.png"),
             "-filter_complex",
             f"[0:v]zoompan={推拉表(效果, 帧数, fx, fy, zmax)}:d=1:s={W}x{H}:fps={FPS}[z];"
             f"[z][1:v]overlay=0:0,format=yuv420p[v]",
             "-map", "[v]", "-t", f"{秒:.3f}", "-r", str(FPS),
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", out])
        段.append(out)
        print(f"  场{号:02d}  {秒:5.2f}s  {效果:<2}  {'（卡）' if 图名 is None else 图名}"
              f"  {句[号-1]['文本'][:26]}⋯⋯", flush=True)

    lst = os.path.join(场景目录, "清单.txt")
    open(lst, "w", encoding="utf-8").write("".join(f"file '{os.path.basename(p)}'\n" for p in 段))
    无声 = os.path.join(场景目录, "无声.mp4")
    跑(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", 无声])
    跑(["ffmpeg", "-y", "-i", 无声, "-i", 音轨, "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         "-shortest", 片名])
    总 = sum(时长)
    实测 = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", 片名], capture_output=True, text=True).stdout.strip() or 0)
    print(f"\n成片：{片名}")
    print(f"  预期 {总:.1f} s ｜ 实测 {实测:.1f} s ｜ {W}×{H} {FPS} fps ｜ {os.path.getsize(片名) / 1e6:.1f} MB")
    if abs(实测 - 总) > 0.6:
        print(f"  ⚠️ 实测与预期差 {abs(实测 - 总):.1f} s，检查输入帧率是否等于 {FPS}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
