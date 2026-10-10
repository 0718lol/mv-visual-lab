# -*- coding: utf-8 -*-
"""render_artboards.py — 把提灯实拍图调成「夜航」单曲的视觉物料。

产出三张版面（对应QQ音乐/视频号的三种投放位）：
    out/01_专辑封面_3000x3000.png      方形封面
    out/02_MV主视觉_1920x1080.png      横版主视觉
    out/03_竖版短视频封面_1200x2133.png 竖版封面

用法::

    python3 scripts/render_artboards.py            # 全部
    python3 scripts/render_artboards.py 01         # 只出某张（按前缀）

设计说明见 README.md「合成拆解」一节。
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import core as C  # noqa: E402

SRC = os.path.join(os.path.dirname(ROOT), "3d-portfolio", "04_render", "01_hero.png")
OUT = os.path.join(ROOT, "out")

TRACK_CN = "夜航"
TRACK_EN = "NIGHT PASSAGE"
META_L = "腾讯音乐人 · AI MV 企划 / 002"
META_R = "词曲 王安畅　编曲 王安畅　视觉 王安畅"

def font_builder(size, script):
    """按条目声明的字族风格返回 (主字体, 中文字体)。

    混排文案里中文一律走中文字体，否则 Songti/Helvetica 之外的字体拿不到汉字字形，会掉成方框。
    """
    if script == "latin-serif":
        main = C.latin_font(size, serif=True, bold=True)
    elif script == "latin-bold":
        main = C.latin_font(size, bold=True)
    else:
        main = C.latin_font(size)
    return main, C.cjk_font(size, bold=True)


# ------------------------------------------------------------------ 共用底层

def base_layer(W, H, center=(0.5, 0.52), blur_near=2.6, glow_xy=(0.50, 0.545), glow_scale=1.0, vign=0.50,
               emit=None):
    """底图：影棚实拍 → 冷夜双色调 → 主体光 → 雨雾 → 颗粒。

    这是所有版面共用的底层，不同版面只改裁切与铺光比例。
    emit(stage_name, array) 会在每个关键阶段回调一次，用来出「图层拆解图」。
    """
    def _emit(name, arr):
        if emit is not None:
            emit(name, arr.copy())

    hero = Image.open(SRC).convert("RGB")
    sharp = C.fit_cover(hero, W, H, center=center)
    soft = sharp.filter(ImageFilter.GaussianBlur(blur_near))
    _emit("01_原片裁切", C.to_arr(sharp))

    # 轻微景深：上虚下实，模拟焦平面落在灯上
    ramp = np.linspace(0.55, 0.0, H, dtype=np.float32)[:, None] * np.ones((1, W), np.float32)
    a = C.alpha_over(C.to_arr(soft), C.to_arr(sharp), np.clip(ramp / 0.55, 0, 1), "normal")
    _emit("02_景深", a)

    # 渐变映射：暗部冷靛蓝，高光是黄铜暖金
    a = C.duotone(a, shadow=(0.014, 0.022, 0.052), mid=(0.14, 0.14, 0.17),
                  high=(0.95, 0.74, 0.44), mid_pos=0.55)
    a = C.curve(a, lift=-0.012, gain=1.18, gamma=0.94, pivot=0.40)
    a = C.saturate(a, 1.06)
    a = C.split_tone(a, shadow_tint=(0.10, 0.20, 0.36), high_tint=(1.0, 0.80, 0.52),
                     balance=0.42, strength=0.34)
    _emit("03_渐变映射与调色", a)

    # 局部渐变：右上压暗、底部压暗，让影棚地板读成夜里的地面
    a = C.linear_ramp(a, (W, H), 0.0, 0.62, 0.60, 0.0, angle_deg=115, color=(0.20, 0.30, 0.50))
    a = C.linear_ramp(a, (W, H), 0.55, 1.0, 0.0, 0.30, angle_deg=90, color=(0.10, 0.16, 0.28))
    # 右缘那面背景板偏亮，径向压回去
    a = C.alpha_over(a, np.ones_like(a) * np.array([0.06, 0.10, 0.18], np.float32),
                     C.radial(W, H, W * 1.02, H * 0.42, W * 0.62, 2.0) * 0.94, "multiply")
    _emit("04_压暗与蒙版渐变", a)

    # 主体光：宽环境光 + 灯芯近处强光
    cx, cy = W * glow_xy[0], H * glow_xy[1]
    a = C.glow(a, cx, cy, W * 0.60 * glow_scale, (0.62, 0.44, 0.24), strength=0.58, power=2.4)
    a = C.glow(a, cx, cy, W * 0.17 * glow_scale, (1.0, 0.82, 0.54), strength=0.78, power=2.1)
    a = C.bloom(a, threshold=0.60, radius=max(6, int(W * 0.030)), strength=0.60)
    a = C.halation(a, threshold=0.72, radius=max(5, int(W * 0.020)), strength=0.34)
    _emit("05_主体光与辉光", a)

    # 天气：雨丝 + 雾 + 近景虚焦雨滴 + 地面溅水
    rgb, al = C.rain((W, H), count=int(W * 0.95), angle=-7,
                     length=(int(H * 0.02), int(H * 0.16)), width=(1, 2),
                     opacity=(0.04, 0.26), seed=7)
    a = C.alpha_over(a, rgb, al * 0.9, "screen")
    a = C.fog(a, y_top=0.42, y_bot=1.0, density=0.40, seed=5)
    rgb, al = C.bokeh((W, H), count=int(W * 0.06), r=(3, 18), opacity=(0.05, 0.24), seed=11, blur=5)
    a = C.alpha_over(a, rgb, al, "screen")
    rgb, al = C.splashes((W, H), count=int(W * 0.10), r=(2, 8), opacity=(0.05, 0.20), seed=17)
    a = C.alpha_over(a, rgb, al, "screen")
    _emit("06_雨雾天气", a)

    a = C.vignette(a, amount=vign, power=1.5)
    a = C.chroma_shift(a, dx=max(1.0, W / 860))
    a = C.grain(a, amount=0.028, seed=3)
    _emit("07_暗角与颗粒", a)
    return a


def print_texture(a, seed=21, strength=0.34, period=4):
    """印刷质感：纸纹（叠加）+ 极淡扫描线（正片叠底），让成品不像纯数字渲染。"""
    W = a.shape[1]
    H = a.shape[0]
    pap = C.paper((W, H), seed=seed, strength=0.05)
    a = C.alpha_over(a, np.ones_like(a) * pap[..., None], np.full((H, W), strength, np.float32), "softlight")
    rgb, al = C.scanlines((W, H), period=period, opacity=0.05)
    a = C.alpha_over(a, np.clip(rgb, 0, 1), al, "multiply")
    return a


def cmyk_misregistration(a, items, W, H, dx=None):
    """套印不准：文字层用青/品红两个偏移版本滤色叠底，做出印刷错版感。"""
    dx = dx or max(1.5, W / 1500)
    rgb, al = C.text_layer((W, H), items, font_builder)
    for tint, off in (((0.10, 0.85, 1.0), -dx), ((1.0, 0.16, 0.30), dx)):
        lay = np.ones_like(a) * np.array(tint, np.float32)
        sh = np.roll(np.roll(al, int(round(off)), axis=1), int(round(off * 0.4)), axis=0)
        a = C.alpha_over(a, lay, np.clip(sh * 0.30, 0, 1), "screen")
    # 主体文字
    a = C.alpha_over(a, rgb * 0 + np.array([0.965, 0.945, 0.905], np.float32), al, "normal")
    return a


def rules_and_marks(a, W, H, spec):
    """细线、十字规矩线、色标条 —— 印刷打样上的那套记号。"""
    ink = (0.92, 0.90, 0.86)
    arr = (np.clip(a, 0, 1) * 255).astype(np.uint8)
    im = Image.fromarray(arr)
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    for (x0, y0, x1, y1) in spec.get("rules", []):
        d.line([x0, y0, x1, y1], fill=tuple(int(c * 255) for c in ink) + (int(0.30 * 255),),
               width=max(1, int(round(W / 1800))))
    for (cx, cy, r) in spec.get("crosses", []):
        wt = max(1, int(round(W / 1600)))
        d.line([cx - r, cy, cx + r, cy], fill=tuple(int(c * 255) for c in ink) + (int(0.50 * 255),), width=wt)
        d.line([cx, cy - r, cx, cy + r], fill=tuple(int(c * 255) for c in ink) + (int(0.50 * 255),), width=wt)
    bx, by, bw, bh = spec["bar"]
    for i, col in enumerate([(0.10, 0.85, 1.0), (1.0, 0.16, 0.30), (1.0, 0.86, 0.10),
                             (0.10, 0.10, 0.10), (0.95, 0.95, 0.95)]):
        x = bx + i * bw
        d.rectangle([x, by, x + bw * 0.82, by + bh],
                    fill=tuple(int(c * 255) for c in col) + (int(0.85 * 255),))
    return C.to_arr(im.convert("RGB"))


# ------------------------------------------------------------------ 版面

def artboard_square():
    """3000×3000 专辑封面。"""
    W = H = 3000
    a = base_layer(W, H, center=(0.50, 0.50), glow_xy=(0.50, 0.55), vign=0.52)
    a = print_texture(a, seed=21)
    M = W * 0.075                                  # 版心边距
    title = int(W * 0.125)
    tsize = int(W * 0.026)
    items = [
        # 片名：中文大字 + 西文小字，字距拉开
        (TRACK_CN, M, H * 0.066, title, (0.97, 0.95, 0.91), 1.0, W * 0.012, "left", "cjk"),
        (TRACK_EN, M, H * 0.066 + title * 1.14, tsize, (0.80, 0.82, 0.88), 0.92, W * 0.008, "left", "latin-bold"),
        # 右上：企划编号
        (META_L, W - M, H * 0.068, int(W * 0.0135), (0.80, 0.82, 0.88), 0.88, W * 0.004, "right", "latin-bold"),
        ("SINGLE  ·  2026", W - M, H * 0.068 + W * 0.024, int(W * 0.0125),
         (0.62, 0.66, 0.74), 0.80, W * 0.003, "right", "latin"),
        # 底部：左制作信息 / 右版面标尺，色标条居中偏右，互不打架
        (META_R, M, H * 0.900, int(W * 0.0125), (0.74, 0.77, 0.84), 0.82, W * 0.003, "left", "cjk"),
        ("AI MV PIPELINE  ·  SHOT 07 / 24", W - M, H * 0.900, int(W * 0.0120),
         (0.72, 0.76, 0.84), 0.80, W * 0.003, "right", "latin-bold"),
    ]
    a = cmyk_misregistration(a, items, W, H)

    spec = {
        "rules": [(M, H * 0.056, W - M, H * 0.056),
                  (M, H * 0.056, M, H * 0.056 + W * 0.010),
                  (W - M, H * 0.056, W - M, H * 0.056 + W * 0.010),
                  (M, H * 0.888, W - M, H * 0.888)],
        "crosses": [(M * 0.42, H * 0.42, W * 0.010), (W - M * 0.42, H * 0.42, W * 0.010),
                    (M * 0.42, H * 0.62, W * 0.010), (W - M * 0.42, H * 0.62, W * 0.010)],
        "bar": [W - M - W * 0.086, H * 0.945, W * 0.017, H * 0.0055],
    }
    a = rules_and_marks(a, W, H, spec)

    rgb, al = C.rain((W, H), count=int(W * 0.16), angle=-7, length=(int(H * 0.03), int(H * 0.10)),
                     width=(1, 2), opacity=(0.03, 0.12), seed=31)
    a = C.alpha_over(a, rgb, al * 0.7, "screen")
    return a, "01_专辑封面_3000x3000"


def artboard_mv_wide():
    """1920×1080 横版 MV 主视觉，留出字幕安全区。"""
    W, H = 1920, 1080
    a = base_layer(W, H, center=(0.50, 0.46), blur_near=2.0, glow_xy=(0.52, 0.58), vign=0.54)
    a = print_texture(a, seed=33, strength=0.28)
    M = W * 0.055
    title = int(H * 0.185)
    items = [
        (TRACK_CN, M, H * 0.125, title, (0.97, 0.95, 0.91), 1.0, H * 0.020, "left", "cjk"),
        (TRACK_EN, M, H * 0.125 + title * 1.12, int(H * 0.040), (0.80, 0.82, 0.88), 0.92,
         H * 0.014, "left", "latin-bold"),
        (META_L, M, H * 0.078, int(H * 0.022), (0.80, 0.82, 0.88), 0.88, H * 0.006, "left", "latin-bold"),
        ("OFFICIAL VISUAL  ·  24 SHOTS  ·  3'42\"", W - M, H * 0.882, int(H * 0.0195),
         (0.74, 0.77, 0.85), 0.82, H * 0.004, "right", "latin-bold"),
        (META_R, W - M, H * 0.928, int(H * 0.0195), (0.72, 0.75, 0.82), 0.80, H * 0.004, "right", "cjk"),
    ]
    a = cmyk_misregistration(a, items, W, H, dx=1.8)
    spec = {
        "rules": [(M, H * 0.062, W - M, H * 0.062), (M, H * 0.866, W - M, H * 0.866)],
        "crosses": [(M * 0.45, H * 0.30, H * 0.020), (W - M * 0.45, H * 0.30, H * 0.020)],
        "bar": [W - M - W * 0.072, H * 0.930, W * 0.014, H * 0.011],
    }
    a = rules_and_marks(a, W, H, spec)
    rgb, al = C.rain((W, H), count=int(W * 0.18), angle=-7, length=(int(H * 0.04), int(H * 0.16)),
                     width=(1, 2), opacity=(0.03, 0.12), seed=41)
    a = C.alpha_over(a, rgb, al * 0.7, "screen")
    return a, "02_MV主视觉_1920x1080"


def artboard_vertical():
    """1200×2133 竖版短视频封面：留出上下两条安全区（账号名 + 进度条）。"""
    W, H = 1200, 2133
    a = base_layer(W, H, center=(0.50, 0.42), blur_near=2.4, glow_xy=(0.50, 0.62), vign=0.56)
    a = print_texture(a, seed=45, strength=0.30)
    M = W * 0.085
    title = int(W * 0.155)
    items = [
        ("腾讯音乐人", M, H * 0.052, int(W * 0.040), (0.95, 0.93, 0.90), 0.95, W * 0.006, "left", "cjk"),
        ("TENCENT MUSICIANS", M, H * 0.052 + W * 0.052, int(W * 0.021), (0.72, 0.75, 0.83), 0.85,
         W * 0.006, "left", "latin-bold"),
        (TRACK_CN, M, H * 0.700, title, (0.97, 0.95, 0.91), 1.0, W * 0.016, "left", "cjk"),
        (TRACK_EN, M, H * 0.700 + title * 1.16, int(W * 0.032), (0.82, 0.84, 0.90), 0.92,
         W * 0.010, "left", "latin-bold"),
        ("AI MV  ·  竖版封面  ·  24 SHOTS", M, H * 0.908, int(W * 0.0215), (0.76, 0.79, 0.86), 0.82,
         W * 0.005, "left", "latin-bold"),
        (META_R, M, H * 0.944, int(W * 0.0195), (0.72, 0.75, 0.82), 0.78, W * 0.004, "left", "cjk"),
    ]
    a = cmyk_misregistration(a, items, W, H, dx=1.5)
    spec = {
        "rules": [(M, H * 0.040, W - M, H * 0.040), (M, H * 0.688, W - M, H * 0.688),
                  (M, H * 0.898, W - M, H * 0.898)],
        "crosses": [(M * 0.42, H * 0.34, W * 0.016), (W - M * 0.42, H * 0.34, W * 0.016)],
        "bar": [W - M - W * 0.112, H * 0.972, W * 0.024, H * 0.0040],
    }
    a = rules_and_marks(a, W, H, spec)
    rgb, al = C.rain((W, H), count=int(W * 0.22), angle=-7, length=(int(H * 0.02), int(H * 0.09)),
                     width=(1, 2), opacity=(0.03, 0.12), seed=51)
    a = C.alpha_over(a, rgb, al * 0.7, "screen")
    return a, "03_竖版短视频封面_1200x2133"


ARTBOARDS = {
    "01": artboard_square,
    "02": artboard_mv_wide,
    "03": artboard_vertical,
}


def main():
    only = sys.argv[1:] or list(ARTBOARDS)
    os.makedirs(OUT, exist_ok=True)
    for key in only:
        fn = ARTBOARDS[key]
        t0 = time.time()
        arr, name = fn()
        p = os.path.join(OUT, name + ".png")
        C.to_pil(arr).save(p, optimize=True)
        h, w, _ = arr.shape
        print(f"[ok] {name}  {w}x{h}  {os.path.getsize(p)/1e6:.2f} MB  {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
