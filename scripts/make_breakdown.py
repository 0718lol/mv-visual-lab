# -*- coding: utf-8 -*-
"""make_breakdown.py — 出一张「图层拆解图」。

把合成过程里 7 个关键阶段的画面横排成一张联图，每格带阶段名与 PS 对应操作，
用来向面试/合作方说明「这张图不是一键生成的，是这么一层层搭出来的」。

用法::

    python3 scripts/make_breakdown.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import core as C            # noqa: E402
from render_artboards import base_layer, font_builder  # noqa: E402

OUT = os.path.join(ROOT, "out")

# 阶段名 → 对应的 PS 操作，写进图注
PS_NOTE = {
    "01_原片裁切": "PS：置入原片，裁切构图",
    "02_景深": "PS：高斯模糊图层 + 黑白渐变蒙版",
    "03_渐变映射与调色": "PS：渐变映射 + 色阶 + 黑白场 + 分离色调",
    "04_压暗与蒙版渐变": "PS：线性渐变填充层（正片叠底）当蒙版",
    "05_主体光与辉光": "PS：径向渐变 + 滤色，高光选区模糊做辉光",
    "06_雨雾天气": "PS：笔刷雨丝 + 滤镜库云雾，近景虚焦",
    "07_暗角与颗粒": "PS：镜头校正暗角 + 添加杂色（柔光）",
}


def main():
    os.makedirs(OUT, exist_ok=True)
    stages = []

    def emit(name, arr):
        stages.append((name, arr))

    size = 1100
    base_layer(size, size, center=(0.5, 0.5), glow_xy=(0.50, 0.55), vign=0.52, emit=emit)
    print("阶段数", len(stages))

    cols = 4
    rows = (len(stages) + cols - 1) // cols
    pad = 26
    label_h = 62
    cell = size
    W = cols * cell + (cols + 1) * pad
    H = rows * (cell + label_h) + (rows + 1) * pad

    sheet = Image.new("RGB", (W, H), (14, 15, 18))
    d = ImageDraw.Draw(sheet)

    for i, (name, arr) in enumerate(stages):
        r, c = divmod(i, cols)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + label_h + pad)
        sheet.paste(C.to_pil(arr).resize((cell, cell), Image.LANCZOS), (x, y))
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(70, 76, 88), width=2)

        idx = name.split("_", 1)[0]
        title = name.split("_", 1)[1]
        f_num = C.latin_font(30, bold=True)
        f_cjk = C.cjk_font(30, bold=True)
        C._draw_mixed(d, (x, y + cell + 8), f"{idx}  {title}", f_num, f_cjk, (238, 236, 230), 1.0)
        note = PS_NOTE.get(name, "")
        d.text((x, y + cell + 40), note, font=C.cjk_font(23), fill=(146, 154, 170))

    # 空位补上标题
    for i in range(len(stages), rows * cols):
        r, c = divmod(i, cols)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + label_h + pad)
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(40, 44, 52), width=2)
        C._draw_mixed(d, (x + 24, y + 24), "图层拆解 · 夜航 NIGHT PASSAGE",
                      C.latin_font(34, bold=True), C.cjk_font(34, bold=True), (120, 128, 144), 1.5)
        for k, line in enumerate([
            "原片：Blender Cycles 渲染的黄铜提灯静物（自有资产）",
            "7 个阶段全部可复现：scripts/render_artboards.py",
            "每一层都能在 Photoshop 里找到对应操作，见每格下方注",
        ]):
            d.text((x + 24, y + 84 + k * 40), line, font=C.cjk_font(23), fill=(96, 104, 120))

    p = os.path.join(OUT, "04_图层拆解_7阶段.png")
    sheet.save(p, optimize=True)
    print(f"[ok] {p}  {sheet.size[0]}x{sheet.size[1]}  {os.path.getsize(p)/1e6:.2f} MB")


if __name__ == "__main__":
    main()
