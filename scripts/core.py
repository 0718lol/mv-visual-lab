# -*- coding: utf-8 -*-
"""core.py — 图层合成的底层积木。

整体思路刻意对齐 PS 的图层工作流，每一类操作都能在 PS 里找到对应项：

    luma()          去色 / 明度提取
    gradient_map()  渐变映射（Gradient Map，双色调/三色调）
    glow()          径向渐变 + 滤色（Screen）混合
    bloom()         高光阈值 + 高斯模糊 + 滤色，即 PS 的「高光溢出 / 辉光」
    light_wrap()    主体边缘暖色包裹，即合成里的 Light Wrap
    chroma_shift()  通道错位，即「色差 / 套印不准」
    rain()          直线笔刷 + 不同不透明度
    grain()         添加杂色 + 柔光（Overlay）混合
    vignette()      径向渐变压暗

这些函数全部作用于 float32 的 (h, w, 3) 数组，取值 0..1。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------- 基础工具

FS = 1.0  # 画布尺度系数，由 make_artboards 在渲染高分辨率时设置


def new_canvas(w: int, h: int, color=(0, 0, 0)):
    im = Image.new("RGB", (w, h), tuple(int(c * 255) for c in color))
    return np.asarray(im).astype(np.float32) / 255.0


def to_pil(a: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))


def to_arr(im: Image.Image) -> np.ndarray:
    return np.asarray(im).astype(np.float32) / 255.0


def hexc(s: str):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def fonts(size: int, cjk: bool = False, serif: bool = False, bold: bool = False):
    """按用途挑系统字体。返回可渲染的字体对象列表（含回退）。"""
    cands = []
    if cjk:
        cands += ["/System/Library/Fonts/Supplemental/Songti.ttc",
                  "/System/Library/Fonts/Hiragino Sans GB.ttc",
                  "/System/Library/Fonts/STHeiti Medium.ttc",
                  "/System/Library/Fonts/STHeiti Light.ttc"]
    if serif:
        cands += ["/System/Library/Fonts/Supplemental/Didot.ttc",
                  "/System/Library/Fonts/Supplemental/Baskerville.ttc",
                  "/System/Library/Fonts/Supplemental/Georgia.ttf",
                  "/System/Library/Fonts/Supplemental/Times New Roman.ttf"]
    else:
        cands += ["/System/Library/Fonts/Supplemental/Futura.ttc",
                  "/System/Library/Fonts/Supplemental/Avenir Next.ttc",
                  "/System/Library/Fonts/Supplemental/Helvetica.ttc",
                  "/System/Library/Fonts/Supplemental/Arial.ttf"]
    cands += ["/System/Library/Fonts/Supplemental/Songti.ttc"]
    out = []
    for p in cands:
        for idx in ((1, 0) if bold else (0,)):
            try:
                out.append(ImageFont.truetype(p, size, index=idx))
                break
            except Exception:
                continue
        if out and cjk:
            break
    if not out:
        out = [ImageFont.load_default()]
    return out


def cjk_font(size: int, bold: bool = False):
    """明确要一个能出中日韩字形的字体（中文文案专用）。"""
    return fonts(size, cjk=True, bold=bold)[0]


def latin_font(size: int, serif: bool = False, bold: bool = False):
    return fonts(size, cjk=False, serif=serif, bold=bold)[0]


def _runs(text):
    """按「中日韩」与「其它」切分文本，返回 [(片段, 是否中文)]。"""
    out = []
    for ch in text:
        cjk = ("\u3000" <= ch <= "\u9fff") or ("\uff00" <= ch <= "\uffef")
        if out and out[-1][1] == cjk:
            out[-1][0] += ch
        else:
            out.append([ch, cjk])
    return out


def _draw_mixed(d, xy, text, f_lat, f_cjk, fill, track=0.0):
    """混排绘制：中文用中文字体，拉丁用西文字体，两段之间不额外加字距。"""
    x, y = xy
    for seg, is_cjk in _runs(text):
        f = f_cjk if is_cjk else f_lat
        if track:
            for ch in seg:
                d.text((x, y), ch, font=f, fill=fill)
                x += d.textlength(ch, font=f) + track
        else:
            d.text((x, y), text=seg, font=f, fill=fill)
            x += d.textlength(seg, font=f)
    return x


def measure_mixed(d, text, f_lat, f_cjk, track=0.0):
    w = 0.0
    for seg, is_cjk in _runs(text):
        f = f_cjk if is_cjk else f_lat
        if track:
            w += sum(d.textlength(ch, font=f) + track for ch in seg)
        else:
            w += d.textlength(seg, font=f)
    return w


def text_layer(size_wh, items, font_builder=None):
    """items: [(text, x, y, size, color, opacity, tracking, align, script)]

    script 取 "cjk" / "latin" / "latin-serif"，决定这一条的主字体；
    条内混排时中文自动切到中文字体（否则会掉成方框）。
    font_builder(size, script, bold) -> (f_main, f_cjk)
    """
    w, h = size_wh
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for it in items:
        txt, x, y, size = it[0], it[1], it[2], int(it[3])
        col = it[4] if len(it) > 4 and it[4] is not None else (1, 1, 1)
        op = it[5] if len(it) > 5 else 1.0
        track = it[6] if len(it) > 6 else 0.0
        align = it[7] if len(it) > 7 else "left"
        script = it[8] if len(it) > 8 else "latin"
        rgb = tuple(int(c * 255) for c in col) + (int(np.clip(op, 0, 1) * 255),)
        f_main, f_cjk = font_builder(size, script) if font_builder else (ImageFont.load_default(), ImageFont.load_default())
        total = measure_mixed(d, txt, f_main, f_cjk, track)
        tx = x - (total / 2 if align == "center" else total if align == "right" else 0)
        _draw_mixed(d, (tx, y), txt, f_main, f_cjk, rgb, track)
    return to_arr(im.convert("RGB")), to_arr(im.split()[3])


def alpha_over(base: np.ndarray, rgb: np.ndarray, alpha: np.ndarray, mode: str = "normal"):
    """把带透明度的图层合成到 base 上，支持 normal / screen / multiply / overlay / softlight。"""
    a = alpha[..., None]
    if mode == "normal":
        out = base * (1 - a) + rgb * a
    elif mode == "screen":
        s = 1 - (1 - base) * (1 - rgb)
        out = base * (1 - a) + s * a
    elif mode == "multiply":
        out = base * (1 - a) + (base * rgb) * a
    elif mode == "overlay":
        o = np.where(base < 0.5, 2 * base * rgb, 1 - 2 * (1 - base) * (1 - rgb))
        out = base * (1 - a) + o * a
    elif mode == "softlight":
        o = np.where(rgb < 0.5,
                     2 * base * rgb + base ** 2 * (1 - 2 * rgb),
                     2 * base * (1 - rgb) + np.sqrt(np.maximum(base, 0)) * (2 * rgb - 1))
        out = base * (1 - a) + o * a
    else:
        raise ValueError(mode)
    return np.clip(out, 0, 1)


# ---------------------------------------------------------------- 颜色

def luma(a: np.ndarray) -> np.ndarray:
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def gradient_map(gray: np.ndarray, stops):
    """渐变映射。stops: [(位置0..1, (r,g,b)), ...] 按位置升序。"""
    xs = np.array([s[0] for s in stops], np.float32)
    cols = np.array([s[1] for s in stops], np.float32)
    g = np.clip(gray, 0, 1)
    out = np.empty(g.shape + (3,), np.float32)
    for c in range(3):
        out[..., c] = np.interp(g, xs, cols[:, c])
    return out


def duotone(a: np.ndarray, shadow, mid, high, mid_pos=0.5):
    g = luma(a)
    return gradient_map(g, [(0.0, shadow), (mid_pos, mid), (1.0, high)])


def curve(a: np.ndarray, lift=-0.03, gain=1.08, gamma=1.0, pivot=0.42):
    """基础影调：提黑位 + 拉对比 + 幂次。"""
    x = np.clip(a, 0, 1)
    x = (x - pivot) * gain + pivot + lift
    x = np.clip(x, 0, 1) ** gamma
    return x


def saturate(a: np.ndarray, amt: float):
    g = luma(a)[..., None]
    return np.clip(g + (a - g) * amt, 0, 1)


def split_tone(a: np.ndarray, shadow_tint, high_tint, balance=0.5, strength=0.5):
    """分离色调：暗部染冷色、亮部染暖色。"""
    g = luma(a)[..., None]
    w_s = np.clip((balance - g) / max(balance, 1e-6), 0, 1) * strength
    w_h = np.clip((g - balance) / max(1 - balance, 1e-6), 0, 1) * strength
    sh = np.array(shadow_tint, np.float32)
    hi = np.array(high_tint, np.float32)
    out = a + (sh - 0.5) * w_s * 2 * 0.5 + (hi - 0.5) * w_h * 2 * 0.5
    return np.clip(out, 0, 1)


# ---------------------------------------------------------------- 光效

def radial(w: int, h: int, cx: float, cy: float, r: float, power: float = 2.0, aspect=1.0):
    """径向渐变遮罩，返回 0..1。cx/cy 为像素坐标，r 为半径。"""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xs - cx) / aspect) ** 2 + (ys - cy) ** 2) / max(r, 1e-6)
    return np.clip(1 - d, 0, 1) ** power


def glow(base: np.ndarray, cx, cy, r, color, strength=1.0, power=2.6, aspect=1.0, mode="screen"):
    h, w, _ = base.shape
    m = radial(w, h, cx, cy, r, power, aspect) * strength
    m = np.clip(m, 0, 1)
    lay = np.ones_like(base) * np.array(color, np.float32)
    return alpha_over(base, lay, m, mode)


def linear_ramp(base, size_wh, p0, p1, r0: float, r1: float, angle_deg: float = 90.0, color=(0, 0, 0), mode="multiply"):
    """线性渐变叠层：沿给定角度从 r0 过渡到 r1，再按 color/mode 叠加。

    对应 PS 里的「线性渐变填充图层 + 蒙版」，用来局部压暗或提亮。
    """
    w, h = size_wh
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    th = np.deg2rad(angle_deg)
    t = (xs * np.cos(th) + ys * np.sin(th))
    t = (t - t.min()) / max(t.max() - t.min(), 1e-6)
    m = np.clip(np.interp(t, [p0, p1], [r0, r1]), 0, 1)
    lay = np.ones((h, w, 3), np.float32) * np.array(color, np.float32)
    return alpha_over(base, lay, m, mode)


def bloom(base: np.ndarray, threshold=0.72, radius=40, strength=0.55, tint=(1.0, 0.95, 0.82), mode="screen"):
    """高光阈值 → 模糊 → 滤色。PS 里对应「高光选区 + 高斯模糊 + 滤色叠层」。"""
    g = luma(base)
    m = np.clip((g - threshold) / max(1 - threshold, 1e-6), 0, 1) ** 0.85
    src = base * m[..., None]
    im = to_pil(src).filter(ImageFilter.GaussianBlur(radius))
    bl = to_arr(im) * np.array(tint, np.float32) * strength
    return alpha_over(base, np.clip(bl, 0, 1), np.ones_like(g), mode)


def light_wrap(base: np.ndarray, alpha: np.ndarray, color, radius=26, strength=0.65, mode="screen"):
    """主体边缘暖色包裹：用蒙版的模糊外扩当遮罩，往边缘刷一层主体光色。"""
    a = to_pil(np.repeat(alpha[..., None], 3, 2))
    a = np.asarray(a.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32) / 255.0
    edge = np.clip(a[..., 0] * (1 - alpha) * 2.2, 0, 1) * strength
    lay = np.ones_like(base) * np.array(color, np.float32)
    return alpha_over(base, lay, edge, mode)


def vignette(a: np.ndarray, amount=0.5, power=1.6, cx=0.5, cy=0.52, radius=0.78):
    h, w, _ = a.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xs / w) - cx) ** 2 + ((ys / h) - cy) ** 2)
    m = np.clip((d / radius) ** power, 0, 1) * amount
    return np.clip(a * (1 - m[..., None]), 0, 1)


# ---------------------------------------------------------------- 质感

def rain(size_wh, count=900, angle=-7.0, length=(30, 200), width=(1, 3),
         opacity=(0.05, 0.30), seed=7, blur=0.0, bright_frac=0.12):
    """雨丝图层：多条直线，长度/不透明度随机，模拟不同景深。返回 (rgb, alpha)。

    分两档：大部分是细弱雨丝，少量是靠近镜头、更亮更长的雨条，拉开景深层次。
    """
    w, h = size_wh
    rng = np.random.default_rng(seed)
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    rad = np.deg2rad(angle)
    for i in range(count):
        near = rng.random() < bright_frac
        x = rng.uniform(-w * 0.25, w * 1.25)
        y = rng.uniform(-h * 0.20, h * 1.05)
        if near:
            L = rng.uniform(length[1] * 0.9, length[1] * 2.1)
            wd = int(round(rng.uniform(width[1], width[1] + 2)))
            op = int(rng.uniform(0.20, 0.48) * 255)
        else:
            L = rng.uniform(*length)
            wd = int(round(rng.uniform(*width)))
            op = int(rng.uniform(*opacity) * 255)
        d.line([x, y, x + np.sin(rad) * L, y + np.cos(rad) * L], fill=op, width=max(1, wd))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    al = np.asarray(im).astype(np.float32) / 255.0
    rgb = np.ones((h, w, 3), np.float32) * np.array([0.86, 0.91, 1.0], np.float32)
    return rgb, al


def splashes(size_wh, count=90, r=(2, 9), opacity=(0.06, 0.22), seed=17, y_from=0.55, blur=1.2):
    """地面溅水：扁椭圆的亮点，只出现在画面下半部。"""
    w, h = size_wh
    rng = np.random.default_rng(seed)
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    for _ in range(count):
        x = rng.uniform(0, w)
        y = rng.uniform(h * y_from, h)
        rr = rng.uniform(*r)
        # 越靠下越大（近大远小）
        rr *= 1.0 + (y / h - y_from) * 1.8
        op = int(rng.uniform(*opacity) * 255)
        d.ellipse([x - rr * 1.9, y - rr * 0.42, x + rr * 1.9, y + rr * 0.42], fill=op)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    al = np.asarray(im).astype(np.float32) / 255.0
    rgb = np.ones((h, w, 3), np.float32) * np.array([0.78, 0.86, 0.98], np.float32)
    return rgb, al


def bokeh(size_wh, count=70, r=(4, 22), opacity=(0.04, 0.22), seed=11, blur=3.0):
    """近景虚焦雨滴：模糊的圆点，做出前后景分离。"""
    w, h = size_wh
    rng = np.random.default_rng(seed)
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    for _ in range(count):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        rr = rng.uniform(*r)
        op = int(rng.uniform(*opacity) * 255)
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=op)
    im = im.filter(ImageFilter.GaussianBlur(blur))
    al = np.asarray(im).astype(np.float32) / 255.0
    return np.ones((h, w, 3), np.float32), al


def fog(base: np.ndarray, y_top=0.45, y_bot=1.0, color=(0.42, 0.52, 0.62),
        density=0.5, seed=5, scale=6):
    """雾/水汽：低频噪声在指定纵向区间内做滤色叠加。"""
    h, w, _ = base.shape
    rng = np.random.default_rng(seed)
    small = rng.random((max(2, h // (28 * scale // 6)), max(2, w // (28 * scale // 6)))).astype(np.float32)
    n = np.asarray(Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)).astype(np.float32) / 255.0
    n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(24))).astype(np.float32) / 255.0
    ys = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    band = np.clip((ys - y_top) / max(y_bot - y_top, 1e-6), 0, 1) * np.clip((1.0 - ys) / 0.25, 0, 1)
    m = np.clip(n * band * density, 0, 1)
    lay = np.ones_like(base) * np.array(color, np.float32)
    return alpha_over(base, lay, m, "screen")


def grain(a: np.ndarray, amount=0.035, seed=3, size=1.0):
    """35mm 颗粒：高频噪声 + 柔光混合，暗部更明显。"""
    h, w, _ = a.shape
    rng = np.random.default_rng(seed)
    if size != 1.0:
        sw, sh = max(2, int(w / size)), max(2, int(h / size))
        n = rng.normal(0, 1, (sh, sw)).astype(np.float32)
        n = np.asarray(Image.fromarray(((n * 0.25 + 0.5) * 255).clip(0, 255).astype(np.uint8))
                      .resize((w, h), Image.BILINEAR)).astype(np.float32) / 255.0 - 0.5
    else:
        n = rng.normal(0, 1, (h, w)).astype(np.float32) * 0.25
    m = np.abs(n) * 2 * amount
    lay = np.clip(a + n[..., None], 0, 1)
    return alpha_over(a, lay, np.clip(m, 0, 1), "softlight")


def scanlines(size_wh, period=4, opacity=0.06, angle=0.0):
    w, h = size_wh
    ys = np.arange(h) % period
    m = ((ys < period / 2).astype(np.float32) * opacity)[:, None] * np.ones((1, w), np.float32)
    if angle:
        im = Image.fromarray((m * 255).astype(np.uint8)).rotate(angle, resample=Image.BILINEAR, expand=False)
        m = np.asarray(im).astype(np.float32) / 255.0
    return np.zeros((h, w, 3), np.float32), m


def paper(size_wh, seed=9, strength=0.05, fibers=True):
    """纸纹 / 印刷底纹：低频起伏 + 细纤维，用叠加模式。"""
    w, h = size_wh
    rng = np.random.default_rng(seed)
    base = rng.random((max(2, h // 60), max(2, w // 60))).astype(np.float32)
    n = np.asarray(Image.fromarray((base * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)).astype(np.float32) / 255.0
    n = n - n.mean()
    if fibers:
        fib = rng.random((h, w)).astype(np.float32)
        fib = np.asarray(Image.fromarray((fib * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))).astype(np.float32) / 255.0
        n = n * 0.7 + (fib - 0.5) * 0.6
    return n * strength + 0.5


def chroma_shift(a: np.ndarray, dx=2.0, dy=0.0, keep_green=True):
    """通道错位：R/B 各偏移一点，模拟色差或套印不准。"""
    h, w, _ = a.shape
    r = np.asarray(Image.fromarray((a[..., 0] * 255).astype(np.uint8)).transform(
        (w, h), Image.AFFINE, (1, 0, -dx, 0, 1, -dy), resample=Image.BILINEAR)).astype(np.float32) / 255.0
    b = np.asarray(Image.fromarray((a[..., 2] * 255).astype(np.uint8)).transform(
        (w, h), Image.AFFINE, (1, 0, dx, 0, 1, dy), resample=Image.BILINEAR)).astype(np.float32) / 255.0
    out = a.copy()
    out[..., 0] = r
    out[..., 2] = b
    return np.clip(out, 0, 1)


def halation(a: np.ndarray, threshold=0.80, radius=30, color=(1.0, 0.42, 0.30), strength=0.45):
    """胶片光晕：高光溢出后偏红橙，PS 里是「高光选区 + 模糊 + 颜色叠加 + 滤色」。"""
    g = luma(a)
    m = np.clip((g - threshold) / max(1 - threshold, 1e-6), 0, 1)
    im = to_pil(np.repeat(m[..., None], 3, 2)).filter(ImageFilter.GaussianBlur(radius))
    mm = np.asarray(im).astype(np.float32) / 255.0
    lay = np.ones_like(a) * np.array(color, np.float32)
    return alpha_over(a, lay, np.clip(mm[..., 0] * strength, 0, 1), "screen")


# ---------------------------------------------------------------- 变换

def fit_cover(img: Image.Image, box_w: int, box_h: int, scale: float = 1.0,
              center=(0.5, 0.5), mode=Image.LANCZOS) -> Image.Image:
    """等比缩放到铺满目标框的 scale 倍，再按 center 裁切。"""
    w, h = img.size
    r = max(box_w / w, box_h / h) * scale
    nw, nh = max(1, int(round(w * r))), max(1, int(round(h * r)))
    im = img.resize((nw, nh), mode)
    cx, cy = int(nw * center[0]), int(nh * center[1])
    x0 = int(np.clip(cx - box_w / 2, 0, max(0, nw - box_w)))
    y0 = int(np.clip(cy - box_h / 2, 0, max(0, nh - box_h)))
    return im.crop((x0, y0, x0 + box_w, y0 + box_h))


def place(base: np.ndarray, rgb: np.ndarray, alpha: np.ndarray, x: int, y: int, mode="normal"):
    """把 (rgb, alpha) 贴到 base 的 (x, y)，超出画布自动裁切。"""
    h, w, _ = base.shape
    lh, lw = alpha.shape
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + lw), min(h, y + lh)
    if x1 <= x0 or y1 <= y0:
        return base
    sx0, sy0 = x0 - x, y0 - y
    sub_rgb = rgb[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
    sub_al = alpha[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
    out = base.copy()
    out[y0:y1, x0:x1] = alpha_over(base[y0:y1, x0:x1], sub_rgb, sub_al, mode)
    return out
