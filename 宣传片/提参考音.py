# -*- coding: utf-8 -*-
"""提参考音.py：从“奶龙”音色预设里抽出参考音频，供 index-tts 零样本克隆用。

    python 提参考音.py

输入 `Speech-AI-Forge-spks/spks/fishspeech_community/fs_奶龙.spkv1.json`：
那是 Speech-AI-Forge 的音色包（`DcSpk`），结构是
`data.refs[0].data.{text, wav:{data: base64}, wav_sr}`。参考音与它的文本都内嵌在
JSON 里，是 base64 的裸 PCM，所以不需要另外找音频文件。

输出 `素材/奶龙_参考.wav`，44.1 kHz 单声道 16 位。index-tts 的 `infer()` 要的就是
一段参考音和参考音的文本，它照着这个嗓子念新词。
"""
from __future__ import annotations

import base64
import json
import os
import wave

这里 = os.path.dirname(os.path.abspath(__file__))
预设 = r"C:\Users\Yabuk\Desktop\Speech-AI-Forge-spks\spks\fishspeech_community\fs_奶龙.spkv1.json"
输出 = os.path.join(这里, "素材", "奶龙_参考.wav")


def main() -> int:
    if not os.path.isfile(预设):
        print("找不到音色预设：", 预设)
        return 2
    d = json.load(open(预设, encoding="utf-8"))["data"]
    ref = d["refs"][0]["data"]
    raw = base64.b64decode(ref["wav"]["data"])
    sr = ref["wav_sr"]

    os.makedirs(os.path.dirname(输出), exist_ok=True)
    if raw[:4] == b"RIFF":                      # 已经是 wav 容器就原样落盘
        open(输出, "wb").write(raw)
        with wave.open(输出) as f:
            时长 = f.getnframes() / f.getframerate()
    else:                                        # 裸 PCM：自己包一层头（16 位单声道）
        with wave.open(输出, "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr)
            f.writeframes(raw)
        时长 = len(raw) / 2 / sr

    print(f"音色：{d['meta']['data']['name']}（{d['meta']['data']['desc']}，"
          f"{d['meta']['data']['gender']}）")
    print(f"参考文本：{ref['text']}")
    print(f"写出 {输出}  {os.path.getsize(输出)} B  {时长:.2f} s  {sr} Hz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
