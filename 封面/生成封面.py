# -*- coding: utf-8 -*-
"""生成封面.py：用 AIHubMix 的 gpt-image-2.5-flare 生成项目封面。

    python 生成封面.py --试                 # 小尺寸冒烟测试，验证接口与参数
    python 生成封面.py                     # 出正式封面（1536 × 1024，quality high）
    python 生成封面.py --提示 "…" --尺寸 1536x1024 --质量 high --出 我的封面.png

密钥走环境变量 `AIHUBMIX_API_KEY`，不写进文件。
接口是 OpenAI 兼容的 `/v1/images/generations`；gpt-image 系列固定回 b64_json，
所以不传 response_format，拿到 base64 自己落盘。

封面画什么：这张图是给“数据生成的古代架空世界地图”做脸面，所以主体是**羊皮纸质感的世界地图
＋细密的栅格**——古地图的调子与栅格的现代感叠在一起。图里**不要文字**：图像模型写不好汉字，
标题另外用 Pillow 叠，字体与排版才可控。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

接口 = "https://aihubmix.com/v1/images/generations"
默认提示 = (
    "An ancient parchment world map seen from above, rendered as a modern raster grid. "
    "The land is split into fine square cells, each cell a flat muted terrain colour: dark pine green "
    "forests, ochre and pale-yellow deserts, dusty steppe, jade river valleys, slate-blue lakes, "
    "snow-white mountain ridges, cold grey sea ice in the far north. Rivers and coastlines stay "
    "organic and hand-drawn, while the cell grid stays crisp and regular. Warm aged-paper texture, "
    "faint golden grid lines, soft top-down light, muted earthy palette, cartographic and dignified. "
    "No text, no letters, no numbers, no labels, no watermark, no border."
)


def 生成(提示: str, 尺寸: str, 质量: str, 张数: int = 1):
    key = os.environ.get("AIHUBMIX_API_KEY")
    if not key:
        raise SystemExit("没有 AIHUBMIX_API_KEY 这个环境变量")
    体 = {"model": "gpt-image-2.5-flare", "prompt": 提示, "size": 尺寸, "quality": 质量, "n": 张数}
    请求 = urllib.request.Request(
        接口, method="POST",
        data=json.dumps(体).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(请求, timeout=600) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        详情 = e.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {e.code}：{详情[:800]}")


def 取图(回包: dict, 出: str) -> int:
    数据 = 回包.get("data") or []
    if not 数据:
        print("回包里没有 data：", json.dumps(回包, ensure_ascii=False)[:600])
        return 1
    件 = 数据[0]
    if 件.get("b64_json"):
        open(出, "wb").write(base64.b64decode(件["b64_json"]))
    elif 件.get("url"):
        with urllib.request.urlopen(件["url"], timeout=120) as r:
            open(出, "wb").write(r.read())
    else:
        print("回包里既没有 b64_json 也没有 url：", list(件))
        return 1
    print(f"写出 {出}  {os.path.getsize(出) / 1e6:.2f} MB")
    if 回包.get("usage"):
        print("用量：", json.dumps(回包["usage"], ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--提示", default=默认提示)
    ap.add_argument("--尺寸", default="1536x1024")
    ap.add_argument("--质量", default="high", choices=["low", "medium", "high", "xhigh", "max", "auto"])
    ap.add_argument("--出", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "封面_原图.png"))
    ap.add_argument("--试", action="store_true", help="小尺寸冒烟测试")
    a = ap.parse_args()
    if a.试:
        a.尺寸, a.质量 = "1024x1024", "low"
        a.出 = os.path.join(os.path.dirname(a.出), "封面_测试.png")
    print(f"请求 gpt-image-2.5-flare：{a.尺寸} / {a.质量} …（大图要等一两分钟）", flush=True)
    return 取图(生成(a.提示, a.尺寸, a.质量), a.出)


if __name__ == "__main__":
    raise SystemExit(main())
