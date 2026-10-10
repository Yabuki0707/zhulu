# -*- coding: utf-8 -*-
"""提参考音.py：从音色预设里抽出参考音频，供 index-tts 零样本克隆用。

    python 提参考音.py                 # 默认取“麦克阿瑟”
    python 提参考音.py 奶龙            # 换一个音色
    python 提参考音.py --列            # 列出可用的音色名

预设来自 Speech-AI-Forge 的音色包，结构是 `DcSpk`：
`data.refs[0].data.{text, wav:{data: base64}, wav_sr}`。参考音与它的文本都内嵌在
JSON 里，是 base64 的裸 PCM，所以不需要另外找音频文件。

输出 `素材/<音色>_参考.wav`，44.1 kHz 单声道 16 位。index-tts 的 `infer()` 要的就是
一段参考音和参考音的文本，它照着这个嗓子念新词。换了音色，`配音.py` 里的文件名要跟着改。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import wave

这里 = os.path.dirname(os.path.abspath(__file__))
预设目录 = r"C:\Users\Yabuk\Desktop\Speech-AI-Forge-spks\spks"
默认音色 = "麦克阿瑟"


def 找预设(名: str):
    """先找 `fs_<名>.spkv1.json`，找不到再模糊匹配一次。"""
    for 目录, _, 文件们 in os.walk(预设目录):
        for f in 文件们:
            if f in (f"fs_{名}.spkv1.json", f"{名}.spkv1.json"):
                return os.path.join(目录, f)
    候选 = [os.path.join(目录, f)
            for 目录, _, 文件们 in os.walk(预设目录)
            for f in 文件们 if f.endswith(".spkv1.json") and 名 in f]
    return 候选[0] if len(候选) == 1 else None


def 列一遍() -> int:
    for 目录, _, 文件们 in os.walk(预设目录):
        for f in sorted(文件们):
            if f.endswith(".spkv1.json"):
                print("  ", f[: -len(".spkv1.json")])
    return 0


def main() -> int:
    参数 = sys.argv[1:]
    if "--列" in 参数 or "-l" in 参数:
        return 列一遍()
    名 = 参数[0] if 参数 else 默认音色
    p = 找预设(名)
    if not p:
        print(f"没找到音色 {名}，用 --列 看看有哪些", file=sys.stderr)
        return 2

    d = json.load(open(p, encoding="utf-8"))["data"]
    meta = d["meta"]["data"]
    ref = d["refs"][0]["data"]
    val = ref["wav"]["data"]
    raw = base64.b64decode(val) if isinstance(val, str) else bytes(val)
    sr = ref["wav_sr"]

    输出 = os.path.join(这里, "素材", meta["name"].replace("fs_", "") + "_参考.wav")
    os.makedirs(os.path.dirname(输出), exist_ok=True)
    if raw[:4] == b"RIFF":
        open(输出, "wb").write(raw)
        with wave.open(输出) as f:
            时长 = f.getnframes() / f.getframerate()
    else:
        with wave.open(输出, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(sr)
            f.writeframes(raw)
        时长 = len(raw) / 2 / sr

    print(f"音色：{meta['name']}（{meta.get('desc')}，{meta.get('gender')}）")
    print(f"参考文本：{ref['text']}")
    print(f"写出 {输出}  {os.path.getsize(输出)} B  {时长:.2f} s  {sr} Hz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
