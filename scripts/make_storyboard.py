# -*- coding: utf-8 -*-
"""make_storyboard.py — 出「AI MV 分镜表（6 张关键帧）」。

同一份素材，用蒙版 + 局部光 + 裁切做出 6 个明显不同的镜头，
每格标注镜号 / 景别 / 时长 / 运镜 / 对应 prompt 编号，
可以直接当分镜脚本给制作方或上游 AI 生成环节看。

用法::

    python3 scripts/make_storyboard.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import core as C  # noqa: E402

SRC = os.path.join(os.path.dirname(ROOT), "3d-portfolio", "04_render", "01_hero.png")
OUT = os.path.join(ROOT, "out")

# 镜号, 中文镜名, 景别, 时长(秒), 运镜, prompt 编号
SHOTS = [
    ("01", "远景推进", "大远景", 6.0, "缓慢推近", "S01"),
    ("02", "灯芯特写", "特写", 4.5, "微手持呼吸感", "S02"),
    ("03", "雨打玻璃", "近景", 5.0, "慢速横移", "S03"),
    ("04", "光柱穿雾", "中景", 7.0, "固定 + 雾流动", "S04"),
    ("05", "地面倒影", "近景", 5.5, "低机位跟移", "S05"),
    ("06", "背影剪影", "全景", 6.0, "缓慢拉远", "S06"),
]


def frame(kind: str, size: int = 720):
    """按镜头类型渲染一张关键帧。"""
    hero = Image.open(SRC).convert("RGB")

    if kind == "01":      # 大远景：灯小、环境大，靠暗角把四周吃掉
        a = C.to_arr(C.fit_cover(hero, size, size, scale=1.0, center=(0.50, 0.60)))
        glow = (0.50, 0.72); gr = 0.34; vig = 0.72; blur = 3.2
    elif kind == "02":    # 灯芯特写：怼近，强光溢出
        a = C.to_arr(C.fit_cover(hero, size, size, scale=3.1, center=(0.50, 0.46)))
        glow = (0.50, 0.52); gr = 0.62; vig = 0.50; blur = 1.6
    elif kind == "03":    # 雨打玻璃：偏右下，看到雨丝
        a = C.to_arr(C.fit_cover(hero, size, size, scale=1.5, center=(0.58, 0.42)))
        glow = (0.46, 0.52); gr = 0.40; vig = 0.56; blur = 2.4
    elif kind == "04":    # 光柱穿雾：灯偏左，右侧大片雾
        a = C.to_arr(C.fit_cover(hero, size, size, scale=1.15, center=(0.40, 0.50)))
        glow = (0.38, 0.56); gr = 0.72; vig = 0.44; blur = 2.8
    elif kind == "05":    # 地面倒影：低机位，画面下三分之二是地
        a = C.to_arr(C.fit_cover(hero, size, size, scale=1.35, center=(0.50, 0.86)))
        glow = (0.50, 0.20); gr = 0.46; vig = 0.58; blur = 2.2
    else:                 # 背影剪影：整体压到近乎剪影
        a = C.to_arr(C.fit_cover(hero, size, size, scale=0.95, center=(0.50, 0.48)))
        glow = (0.50, 0.50); gr = 0.34; vig = 0.70; blur = 3.0

    a = C.duotone(a, shadow=(0.010, 0.016, 0.040), mid=(0.12, 0.13, 0.17),
                  high=(0.95, 0.74, 0.44), mid_pos=0.55)
    a = C.curve(a, lift=-0.012, gain=1.20, gamma=0.93, pivot=0.40)
    a = C.split_tone(a, shadow_tint=(0.10, 0.20, 0.36), high_tint=(1.0, 0.80, 0.52),
                     balance=0.42, strength=0.34)
    a = C.linear_ramp(a, (size, size), 0.0, 0.62, 0.58, 0.0, angle_deg=115, color=(0.20, 0.30, 0.50))
    a = C.linear_ramp(a, (size, size), 0.55, 1.0, 0.0, 0.30, angle_deg=90, color=(0.10, 0.16, 0.28))
    cx, cy = size * glow[0], size * glow[1]
    a = C.glow(a, cx, cy, size * gr, (0.62, 0.44, 0.24), strength=0.56, power=2.4)
    a = C.glow(a, cx, cy, size * gr * 0.28, (1.0, 0.84, 0.56), strength=0.80, power=2.0)
    a = C.bloom(a, threshold=0.60, radius=max(4, int(size * 0.035)), strength=0.62)
    a = C.halation(a, threshold=0.72, radius=max(3, int(size * 0.022)), strength=0.34)

    density = 0.75 if kind in ("01", "04", "06") else 0.95
    rgb, al = C.rain((size, size), count=int(size * 1.0 * density), angle=-7,
                     length=(int(size * 0.03), int(size * 0.20)), width=(1, 2),
                     opacity=(0.04, 0.26), seed=int(kind) * 13)
    a = C.alpha_over(a, rgb, al * 0.9, "screen")
    a = C.fog(a, y_top=0.36, y_bot=1.0, density=0.46 if kind in ("04", "06") else 0.34, seed=int(kind) * 7)
    rgb, al = C.bokeh((size, size), count=int(size * 0.10), r=(3, 16), opacity=(0.05, 0.24),
                      seed=int(kind) * 5, blur=5)
    a = C.alpha_over(a, rgb, al, "screen")
    rgb, al = C.splashes((size, size), count=70, r=(2, 7), opacity=(0.05, 0.20), seed=int(kind) * 3)
    a = C.alpha_over(a, rgb, al, "screen")

    a = C.vignette(a, amount=vig, power=1.5)
    a = C.chroma_shift(a, dx=0.9)
    a = C.grain(a, amount=0.030, seed=int(kind) * 11)
    if kind == "06":      # 剪影镜：整体再压一档，只留灯的光
        a = C.linear_ramp(a, (size, size), 0.0, 0.8, 0.55, 0.0, angle_deg=90, color=(0.05, 0.08, 0.16))
    return a


def main():
    os.makedirs(OUT, exist_ok=True)
    cell, pad, cap_h = 720, 20, 118
    cols, rows = 3, 2
    W = cols * cell + (cols + 1) * pad
    H = rows * (cell + cap_h) + (rows + 1) * pad
    sheet = Image.new("RGB", (W, H), (14, 15, 18))
    d = ImageDraw.Draw(sheet)

    for i, (no, name, shot, dur, move, pid) in enumerate(SHOTS):
        r, c = divmod(i, cols)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + cap_h + pad)
        arr = frame(no, cell)
        sheet.paste(C.to_pil(arr), (x, y))
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(70, 76, 88), width=2)
        # 镜头信息条
        d.rectangle([x, y + cell, x + cell - 1, y + cell + cap_h - 1], fill=(20, 22, 27))
        C._draw_mixed(d, (x + 16, y + cell + 12), f"镜 {no}  {name}",
                      C.latin_font(30, bold=True), C.cjk_font(30, bold=True), (240, 238, 232), 1.0)
        C._draw_mixed(d, (x + 16, y + cell + 56), f"{shot}   {dur:.1f}s   {move}",
                      C.latin_font(23), C.cjk_font(23), (168, 176, 190), 0.5)
        d.text((x + cell - 16 - d.textlength(pid, font=C.latin_font(24, bold=True)), y + cell + 54),
               pid, font=C.latin_font(24, bold=True), fill=(226, 178, 96))
        # 画幅安全框（4:5 裁切提示）
        d.rectangle([x + 4, y + 4, x + cell - 5, y + cell - 5], outline=(120, 126, 140), width=1)

    p = os.path.join(OUT, "05_AI分镜表_6镜.png")
    sheet.save(p, optimize=True)
    print(f"[ok] {p}  {sheet.size[0]}x{sheet.size[1]}  {os.path.getsize(p)/1e6:.2f} MB")


if __name__ == "__main__":
    main()
