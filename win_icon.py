# -*- coding: utf-8 -*-
"""win_icon.py —— 用纯 Python 画托盘图标（不依赖 Pillow / 任何第三方库）

做法：圆环长度表示剩余电量，中央用点阵数字显示百分比，
再手写 ICO 文件格式，最后交给 LoadImageW 变成 HICON。
支持 16/24/32 三种尺寸，Windows 会按 DPI 自动挑合适的那张。
"""

from __future__ import annotations

import ctypes
import math
import os
import struct
import tempfile
from ctypes import wintypes
from typing import Optional

# ---- 3x5 点阵数字（每行 3 位，"1" 点亮）----
DIGITS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "%": ("101", "001", "010", "100", "101"),
}


def render_rgba(text: str, size: int, color: tuple[int, int, int],
                plate: bool = False, plate_color=(28, 30, 34, 235)) -> bytes:
    """把文字渲染成 size×size 的 RGBA 像素（返回 size*size*4 字节，行优先）。"""
    level = int(text) if text.isdecimal() else None
    if level is not None and not 0 <= level <= 100:
        raise ValueError("电量必须在 0–100 之间")
    # 在 16×16 逻辑画布上绘制，4 倍采样让小圆环边缘平滑。
    samples = 4
    high = size * samples
    unit = high / 16
    center, radius, half_width = 8, 6.65, 0.95
    sweep = 0 if level is None else math.tau * level / 100
    end_x, end_y = radius * math.sin(sweep), -radius * math.cos(sweep)
    background = plate_color[:3] if plate else (18, 22, 28)
    track = (77, 85, 97)
    glyphs = [("1",) * 5 if ch == "1" else
              ("000", "000", "111", "000", "000") if ch == "-" else DIGITS[ch]
              for ch in text]
    width = sum(len(glyph[0]) for glyph in glyphs) + len(glyphs) - 1
    origin, top = (16 - width) // 2, 5
    left = 0
    ink = set()
    for glyph in glyphs:
        for y, row in enumerate(glyph):
            for x, bit in enumerate(row):
                if bit == "1":
                    ink.add((left + x, y))
        left += len(glyph[0]) + 1

    pixels = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            total = [0, 0, 0, 0]
            for sy in range(samples):
                for sx in range(samples):
                    px = (x * samples + sx + 0.5) / unit
                    py = (y * samples + sy + 0.5) / unit
                    dx, dy = px - center, py - center
                    distance = math.hypot(dx, dy)
                    if distance > 7.8:
                        continue
                    rgb = background
                    if abs(distance - radius) <= half_width:
                        angle = math.atan2(dx, -dy) % math.tau
                        active = level is not None and level > 0 and (
                            angle <= sweep or math.hypot(dx, dy + radius) <= half_width
                            or math.hypot(dx - end_x, dy - end_y) <= half_width)
                        rgb = color if active else track
                    if (math.floor(px - origin), math.floor(py - top)) in ink:
                        rgb = (239, 243, 249) if level is not None else (155, 164, 177)
                    for channel in range(3):
                        total[channel] += rgb[channel]
                    total[3] += 255
            count = samples * samples
            i = (y * size + x) * 4
            # RGB 除以覆盖样本数，透明边缘不预乘，避免浅色任务栏上出现黑边。
            covered = total[3] // 255
            if covered:
                pixels[i:i + 4] = bytes([round(total[c] / covered) for c in range(3)]
                                       + [round(total[3] / count)])
    return bytes(pixels)


def build_ico(pngs: list[tuple[int, bytes]]) -> bytes:
    """把多张 RGBA 位图打包成 ICO 文件内容。"""
    entries = []
    blobs = []
    offset = 6 + 16 * len(pngs)
    for size, rgba in pngs:
        # BITMAPINFOHEADER
        bih = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                          size * size * 4, 0, 0, 0, 0)
        # XOR 位图：32bpp BGRA，自下而上
        xor = bytearray()
        for y in range(size - 1, -1, -1):
            row = rgba[y * size * 4:(y + 1) * size * 4]
            for x in range(size):
                r, g, b, a = row[x * 4:x * 4 + 4]
                # 预乘不必要，Windows 直接用 alpha
                xor += bytes((b, g, r, a))
        # AND 掩码：1bpp，每行按 4 字节对齐，全 0（靠 alpha 通道）
        row_bytes = ((size + 31) // 32) * 4
        mask = b"\x00" * (row_bytes * size)
        blob = bih + bytes(xor) + mask
        blobs.append(blob)
        entries.append(struct.pack("<BBBBHHII", size if size < 256 else 0,
                                   size if size < 256 else 0, 0, 0, 1, 32,
                                   len(blob), offset))
        offset += len(blob)
    return (struct.pack("<HHH", 0, 1, len(pngs)) + b"".join(entries)
            + b"".join(blobs))


# ---------------- HICON 缓存 ----------------
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010

user32.LoadImageW.restype = ctypes.c_void_p
user32.LoadImageW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.UINT,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.DestroyIcon.restype = wintypes.BOOL
user32.DestroyIcon.argtypes = [ctypes.c_void_p]

SIZES = (16, 24, 32)
_icon_cache: dict[tuple, int] = {}
_tmp_dir: Optional[str] = None


def _ensure_tmp() -> str:
    global _tmp_dir
    if _tmp_dir is None:
        _tmp_dir = os.path.join(tempfile.gettempdir(), "device_battery_icons")
        os.makedirs(_tmp_dir, exist_ok=True)
    return _tmp_dir


def make_hicon(text: str, color: tuple[int, int, int], plate: bool = False) -> int:
    """按文字+颜色生成（带缓存的）HICON；失败返回 0。"""
    key = (text, color, plate)
    if key in _icon_cache:
        return _icon_cache[key]
    images = [(s, render_rgba(text, s, color, plate)) for s in SIZES]
    ico = build_ico(images)
    path = os.path.join(_ensure_tmp(), f"ring_{text}_{color[0]:02x}{color[1]:02x}"
                                       f"{color[2]:02x}_{int(plate)}.ico")
    try:
        with open(path, "wb") as f:
            f.write(ico)
    except OSError:
        return 0
    h = user32.LoadImageW(None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
    hicon = int(h) if h else 0
    _icon_cache[key] = hicon
    return hicon


def destroy_all() -> None:
    for h in _icon_cache.values():
        if h:
            try:
                user32.DestroyIcon(ctypes.c_void_p(h))
            except Exception:
                pass
    _icon_cache.clear()


def cleanup_files() -> None:
    """清掉临时目录里的 ico 文件。"""
    global _tmp_dir
    if _tmp_dir and os.path.isdir(_tmp_dir):
        for name in os.listdir(_tmp_dir):
            try:
                os.remove(os.path.join(_tmp_dir, name))
            except OSError:
                pass


if __name__ == "__main__":
    # 生成几个样例，方便肉眼检查
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_icon_preview")
    os.makedirs(out, exist_ok=True)
    for text, color, plate, name in (
        ("82", (93, 220, 138), False, "mouse82"),
        ("70", (93, 220, 138), True, "headset70"),
        ("9", (255, 107, 107), False, "mouse9"),
        ("100", (93, 220, 138), True, "headset100"),
        ("25", (245, 196, 81), False, "mouse25"),
    ):
        imgs = [(s, render_rgba(text, s, color, plate)) for s in SIZES]
        p = os.path.join(out, name + ".ico")
        with open(p, "wb") as f:
            f.write(build_ico(imgs))
        print("生成", p)
