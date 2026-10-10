# -*- coding: utf-8 -*-
"""配音.py：用本机 index-tts 与“奶龙”音色给宣传片配音。

    python 配音.py                 # 合成 旁白.txt 里的所有句子
    python 配音.py --句 3          # 只合成第 3 句。改稿后重跑单句，省时间

音色来源是 `Speech-AI-Forge-spks/spks/fishspeech_community/fs_奶龙.spkv1.json`
里内嵌的参考音频，3.82 s，44.1 kHz 单声道 PCM，base64 存放。零样本克隆要的就是
这段东西：给一段参考音和它的文本，模型照着这个嗓子念新词。参考音由 `提参考音.py`
抽成 `素材/奶龙_参考.wav`。

模型在 `C:/Users/Yabuk/Desktop/index-tts/checkpoints`，用的是 v2.5 那一套。
config.yaml 里写着 `version: 2.5`，目录里是 `codec.pth` 与
`multilingual_zh_ja_yue_char_del.tiktoken` 与 `qwen0.6bemo4-merge/`，所以要从
`indextts.infer_v2_5` 导入，不能用 `infer_v2`。后者要 `bpe.model`，而这一份
checkpoint 里没有这个文件。config.yaml 里的 `dataset.bpe_model` 是 v2 留下的死字段，
v2.5 走 tiktoken，用不上它。

显存 8 GB，所以用 bf16，并关掉 `use_cuda_kernel`（要现场编译，第一次很慢，也容易失败）。
v2.5 自带低显存分句，超过 40 字会自动切开，长句不必自己拆。

输出是 `配音/句01.wav` 等，以及一份 `配音/时长.json`，记录每句秒数，合成视频时要用。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import wave

这里 = os.path.dirname(os.path.abspath(__file__))
TTSEd = r"C:\Users\Yabuk\Desktop\index-tts"
参考音 = os.path.join(这里, "素材", "奶龙_参考.wav")
旁白 = os.path.join(这里, "旁白.txt")
输出目录 = os.path.join(这里, "配音")
时长表 = os.path.join(输出目录, "时长.json")
语言 = "zh_CN"


def 读旁白() -> list[str]:
    """旁白.txt：一行一句；`#` 开头是注释、空行跳过。行首序号 `1. ` 由本函数剥掉。"""
    句们 = []
    for line in open(旁白, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s[0].isdigit() and ". " in s[:4]:
            s = s.split(". ", 1)[1]
        句们.append(s)
    return 句们


def 秒数(p: str) -> float:
    with wave.open(p) as f:
        return f.getnframes() / f.getframerate()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--句", type=int, default=0, help="只合成第 N 句（1 起）；0 = 全部")
    ap.add_argument("--texto", default="", help="不走旁白.txt，直接合成这一句（调试用）")
    a = ap.parse_args()

    if not os.path.isfile(参考音):
        print("缺参考音：", 参考音, "。先跑 提参考音.py", file=sys.stderr)
        return 2
    sys.path.insert(0, TTSEd)
    os.chdir(TTSEd)                                   # config.yaml 里是相对路径
    import torch
    from indextts.infer_v2_5 import IndexTTS2

    t0 = time.time()
    print("[1/2] 载模型，首次约 1 至 2 分钟", flush=True)
    bf16 = torch.cuda.is_bf16_supported()
    print(f"      bf16 支持：{bf16}", flush=True)
    tts = IndexTTS2(cfg_path=os.path.join(TTSEd, "checkpoints", "config.yaml"),
                    model_dir=os.path.join(TTSEd, "checkpoints"),
                    use_bf16=bf16, use_cuda_kernel=False, use_deepspeed=False,
                    use_accel=False, use_torch_compile=False, use_qwen_emo=False)
    print(f"      模型就绪（{time.time() - t0:.1f} s）", flush=True)

    if a.texto:
        任务 = [(1, a.texto)]
    else:
        全部 = 读旁白()
        任务 = [(a.句, 全部[a.句 - 1])] if a.句 else list(enumerate(全部, 1))
    os.makedirs(输出目录, exist_ok=True)

    print(f"[2/2] 合成 {len(任务)} 句 → {输出目录}", flush=True)
    表 = {}
    for i, txt in 任务:
        out = os.path.join(输出目录, f"句{i:02d}.wav")
        t = time.time()
        tts.infer(spk_audio_prompt=参考音, text=txt, output_path=out, lang=语言,
                  verbose=False, text_normalization=True)
        d = 秒数(out)
        表[f"句{i:02d}"] = {"文本": txt, "秒": round(d, 2), "字/秒": round(len(txt) / d, 2)}
        print(f"      句{i:02d}  {d:6.2f} s  {len(txt):>3} 字  （合成 {time.time() - t:.1f} s）  {txt}", flush=True)

    if os.path.isfile(时长表):
        try:
            旧 = json.load(open(时长表, encoding="utf-8"))
            旧.update(表)
            表 = 旧
        except Exception:                                                 # noqa: BLE001
            pass
    json.dump(表, open(时长表, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"      共 {sum(v['秒'] for v in 表.values()):.1f} s；时长表 {时长表}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
