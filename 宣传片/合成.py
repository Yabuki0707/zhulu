"""合成.py：把实机产物截图与配音合成为宣传片。

    python 合成.py

十一帧是实机截屏，原图在 `素材/`，都是 2560 × 1440：编辑器四个只读层（样式、覆盖、形态、
气候）、放大到单格并悬停取读数的近景、放大到咸海的覆盖层、行政图的地块层、生成器网页。
三张是说明卡：封面、数据来源、尾卡。画面没有一格是凭空画的。

音频是 `配音.py` 用本机 index-tts 与“月半猫”音色合成的 `配音/句NN.wav`。本脚本按
`配音/时长.json` 把每句配到对应画面上，句前句后各留 0.35 s 气口。
字幕取 `时长.json` 里的 `文本`（数字按规范写阿拉伯数字），
配音用的是 `诵读`（数字写汉字），两种写法在 `旁白.txt` 里用 `|` 隔开。

每帧右上角常驻一行小字：个人项目延伸产物，仅供学习，禁止商用。

**画面是逐帧在 Python 里画的**，直接以 rawvideo 喂给 ffmpeg，不用 ffmpeg 的 zoompan。
原因是抖动：zoompan 把视窗位置取整成整数像素，慢速推近时一帧跳一格，看着就是抖
（实测连续帧差分在 0.47 与 1.39 之间来回跳）。改成给 Pillow 一个**浮点裁剪框**，
由 LANCZOS 做亚像素重采样，差分变成 0.68 上下、极差 0.02，抖动消失。
顺带还有个好处：截图保持 2560 × 1440 原分辨率参与重采样，最高只放大 1.08 倍，比先缩到
1920 再放大清楚得多。字幕用 Pillow 画成 PNG 再叠，也就不必碰 drawtext 的中文转义。

依赖 Pillow 与 ffmpeg。编码用 CRF 21：截图为主，CRF 18 与 21 的同帧差异不到 1/255，
但文件从 55 MB 降到 35 MB，仓库里好放。
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

# 编辑器截屏（2560 × 1440）里画布那一块，不含侧栏与顶栏。
画布 = {"高清_样式.png": (344, 213, 1723, 1136)}


def 字(粗: bool, 号: int):
    return ImageFont.truetype(字体粗 if 粗 else 字体细, 号)


def 满幅(im: Image.Image) -> Image.Image:
    """居中裁成 16:9 再放到 1920 × 1080。"""
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


def 卡_封面() -> Image.Image:
    im = 地图底("高清_样式.png", 0.42)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 366), "《逐鹿》", font=字(True, 156), fill=纸, anchor="mm")
    d.text((W // 2, 516), "世界地图", font=字(True, 100), fill=纸, anchor="mm")
    d.line([(W // 2 - 310, 606), (W // 2 + 310, 606)], fill=强调, width=3)
    d.text((W // 2, 682), "由全球观测数据生成，不是手绘。一格约 5.86 公里",
           font=字(False, 46), fill=(206, 210, 216), anchor="mm")
    d.text((W // 2, 752), "3819 × 2472 格，944 万像元，88 种地形样式",
           font=字(False, 38), fill=灰, anchor="mm")
    d.text((W // 2, 866), "个人项目延伸产物，仅供学习，禁止商用",
           font=字(True, 42), fill=强调, anchor="mm")
    return im


def 卡_字节() -> Image.Image:
    """一格里的答案。全片唯一一处讲做法，一句带过。"""
    im = Image.new("RGB", (W, H), 墨)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 236), "每一格，一个字节", font=字(True, 82), fill=纸, anchor="mm")
    d.text((W // 2, 322), "地表是什么、地势多陡、冷暖干湿，各占几位，凑成一个字节",
           font=字(False, 38), fill=灰, anchor="mm")

    x0, y0, 格宽, 格高 = 452, 470, 150, 160
    for i, (名, 位, 色) in enumerate([("地表", "5 位", 强调), ("地势", "3 位", (132, 180, 218))]):
        数 = 5 if i == 0 else 3
        x = x0 + i * (格宽 * 5 + 60)
        for b in range(数):
            bx = x + b * 格宽
            d.rectangle([bx, y0, bx + 格宽 - 6, y0 + 格高],
                        fill=色 if b == 0 else tuple(int(c * 0.42) for c in 色))
        d.text((x + (格宽 * 数) // 2, y0 - 58), f"{名}（{位}）", font=字(True, 48), fill=纸, anchor="mm")

    d.line([(452, 792), (W - 452, 792)], fill=(66, 70, 76), width=2)
    d.text((W // 2, 856), "游戏读这一格，就知道能不能过、能不能养人、能不能住",
           font=字(True, 42), fill=强调, anchor="mm")
    return im


def 卡_尾() -> Image.Image:
    im = 地图底("高清_样式.png", 0.46)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 330), "逐鹿", font=字(True, 150), fill=纸, anchor="mm")
    d.text((W // 2, 462), "世界地图，由数据生成，不是人工定制", font=字(False, 42), fill=(206, 210, 216), anchor="mm")
    d.text((W // 2, 596), "github.com/Yabuki0707/zhulu", font=字(False, 40), fill=强调, anchor="mm")
    d.text((W // 2, 662), "github.com/Yabuki0707/zhulu-map-editor", font=字(False, 40), fill=强调, anchor="mm")
    d.text((W // 2, 800), "个人项目延伸产物，仅供学习，禁止商用",
           font=字(True, 42), fill=纸, anchor="mm")
    d.text((W // 2, 872), "上游数据各有其许可：GADM 非商用，HydroSHEDS 与 GLWD 不许作独立数据产品再分发",
           font=字(False, 26), fill=(150, 154, 160), anchor="mm")
    return im


def 卡_来源() -> Image.Image:
    """数据从哪儿来。只讲“哪份数据定哪件事”，不列分辨率，一句带过。"""
    im = Image.new("RGB", (W, H), 墨)
    d = ImageDraw.Draw(im)
    d.text((W // 2, 150), "底图来自公开的全球观测", font=字(True, 76), fill=纸, anchor="mm")
    d.text((W // 2, 232), "每一份只定一件事，都是公开数据，各有出处与许可",
           font=字(False, 34), fill=灰, anchor="mm")
    行 = [("高程", "海拔多高，格内起伏多陡"),
          ("地表覆盖", "这里长着森林、草原、耕地还是荒漠"),
          ("气候分类", "一年冷暖与干湿"),
          ("河网", "河流的走向与流量"),
          ("湖沼", "湖泊、盐盘与闭合盆地"),
          ("沙丘形态", "沙漠里是沙，还是砾"),
          ("海冰", "极地冻住的海面"),
          ("火山", "全新世活火山")]
    x, y = 430, 320
    d.line([(x, y - 20), (W - x, y - 20)], fill=(70, 74, 80), width=2)
    for a, b in 行:
        d.text((x, y), a, font=字(True, 32), fill=强调)
        d.text((x + 300, y), b, font=字(False, 32), fill=纸)
        y += 62
    d.line([(x, y + 2), (W - x, y + 2)], fill=(70, 74, 80), width=2)
    return im


卡表 = {"封面": 卡_封面, "来源": 卡_来源, "字节": 卡_字节, "尾": 卡_尾}


def 画字幕(文: str) -> Image.Image:
    """整幅 1920 × 1080 的透明层：底部字幕与右上角常驻小字。

    不用 ffmpeg 的 drawtext：中文要转义冒号、逗号与引号，路径还要转义盘符，
    一次没转对就是花屏。Pillow 画成 PNG 再 overlay，不涉及转义。
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


# 场景表。一句对一帧，顺序与 旁白.txt 一一对应，改一边要连着改另一边。
# (号, 配图 或 卡名, 效果, 目标点 x, 目标点 y, 推到底的倍数)
# 目标点是归一化坐标，0 是最左或最上，1 是最右或最下。
场景 = [
    (1,  "封面",                 "静",   0.50, 0.50, 1.00),
    (2,  "高清_样式.png",         "推近", 0.50, 0.50, 1.10),   # 全图：亚洲与大洋洲
    (3,  "来源",                 "静",   0.50, 0.50, 1.00),
    (4,  "高清_近景_样式.png",     "推近", 0.50, 0.50, 1.16),   # 放大到看得见单格
    (5,  "高清_样式.png",         "推近", 0.56, 0.44, 1.26),   # 森林、草原、沙漠与高原
    (6,  "高清_覆盖.png",         "推近", 0.40, 0.34, 1.44),   # 中亚：沙与砾
    (7,  "高清_咸湖_覆盖.png",     "推近", 0.35, 0.45, 1.34),   # 咸海：水面分类
    (8,  "高清_覆盖.png",         "推近", 0.67, 0.10, 1.42),   # 勘察加与北极：火山与海冰
    (9,  "字节",                 "静",   0.50, 0.50, 1.00),
    (10, "高清_样式.png",         "推近", 0.07, 0.48, 1.30),   # 左栏：88 种样式的名字与颜色
    (11, "高清_地块.png",         "推近", 0.50, 0.50, 1.14),   # 行政图：地块层
    (12, "生成器网页.png",        "推近", 0.76, 0.34, 1.40),   # 六步管线
    (13, "高清_形态.png",         "推近", 0.52, 0.40, 1.38),   # 形态层：山与平原
    (14, "尾",                   "静",   0.50, 0.50, 1.00),
]



def 取窗口(源, 效果: str, fx: float, fy: float, zmax: float, t: float):
    """→ Pillow 的浮点裁剪框 (left, top, right, bottom)。

    `t` 是这一段里的进度 0 至 1。推近时视窗由整幅收拢到 1 / zmax，
    平移固定倍数只挪视窗。**框是浮点数**：zoompan 会把它取整成像素，
    慢推时一格格跳，看着就是抖；浮点框交给 LANCZOS 做亚像素重采样才平滑。
    """
    宽, 高 = 源.size
    if 效果 == "推近":
        z = 1 + (zmax - 1) * t
    elif 效果 == "拉远":
        z = zmax - (zmax - 1) * t
    else:
        z = zmax if 效果 in ("左移", "右移") else 1.0 + 0.02 * t
    vw, vh = 宽 / z, 高 / z
    cx = min(max(fx * 宽, vw / 2), 宽 - vw / 2)
    cy = min(max(fy * 高, vh / 2), 高 - vh / 2)
    if 效果 == "左移":
        cx = (vw / 2) + (宽 - vw) * t
    elif 效果 == "右移":
        cx = (宽 - vw / 2) - (宽 - vw) * t
    return (cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2)


def 出段(底, 字层, 效果: str, fx: float, fy: float, zmax: float, 秒: float, out: str) -> None:
    """逐帧渲染这一段并直接喂给 ffmpeg 编码（rawvideo 走管道，不落中间图）。"""
    n = max(int(round(秒 * FPS)), 1)
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
         "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS), out],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for k in range(n):
        t = k / max(n - 1, 1)
        if 效果 == "静":
            帧 = 底.convert("RGB")
        else:
            帧 = 底.resize((W, H), Image.LANCZOS, box=取窗口(底, 效果, fx, fy, zmax, t)).convert("RGB")
        帧.paste(字层, (0, 0), 字层)
        p.stdin.write(帧.tobytes())
    p.stdin.close()
    p.stderr.read()
    if p.wait() != 0:
        raise SystemExit(f"ffmpeg 编码失败：{out}")


def 跑(cmd: list) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("ffmpeg 失败：", " ".join(cmd[:8]), "…")
        print((p.stderr or "")[-2500:])
        raise SystemExit(1)


def 拼音频(句: list) -> tuple:
    """按“气口 ＋ 句 ＋ 气口”拼成一条音轨，返回音轨路径与每段时长。"""
    out = os.path.join(这里, "旁白_整条.wav")
    时长 = []
    with wave.open(os.path.join(配音目录, "句01.wav")) as f:
        sr, ch, sw = f.getframerate(), f.getnchannels(), f.getsampwidth()
    每帧 = sr * sw * ch
    片 = []
    for i in range(1, len(句) + 1):
        with wave.open(os.path.join(配音目录, f"句{i:02d}.wav")) as f:
            assert (f.getframerate(), f.getnchannels(), f.getsampwidth()) == (sr, ch, sw), "各句格式不一致"
            data = f.readframes(f.getnframes())
        before = b"\x00" * int(每帧 * (开场留白 if i == 1 else 气口))
        after = b"\x00" * int(每帧 * 气口)
        片 += [before, data, after]
        时长.append((len(before) + len(data) + len(after)) / 每帧)
    with wave.open(out, "wb") as f:
        f.setnchannels(ch)
        f.setsampwidth(sw)
        f.setframerate(sr)
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
    if len(句) != len(场景):
        print(f"旁白 {len(句)} 句，场景 {len(场景)} 段，对不上。改文案时两边要一起改。", file=sys.stderr)
        return 2

    音轨, 时长 = 拼音频(句)

    print(f"渲染 {len(场景)} 段…")
    段 = []
    for (号, 图名, 效果, fx, fy, zmax), 秒 in zip(场景, 时长):
        if 图名 in 卡表:
            底, 标注 = 卡表[图名](), "（卡）"
        else:
            底 = Image.open(os.path.join(素材, 图名)).convert("RGB")
            标注 = 图名
        字层 = 画字幕(句[号 - 1]["文本"])
        out = os.path.join(场景目录, f"场{号:02d}.mp4")
        出段(底, 字层, 效果, fx, fy, zmax, 秒, out)
        段.append(out)
        print(f"  场{号:02d}  {秒:5.2f}s  {效果:<2}  {标注}  {句[号-1]['文本'][:24]}…", flush=True)

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
        print(f"  实测与预期差 {abs(实测 - 总):.1f} s，检查输入帧率是否等于 {FPS}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
