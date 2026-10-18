"""圆环回归检查：python -m unittest -v test_ui。"""
import math
import struct
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import battery as bt
import my_devices as ui
import tray_app
import win_icon


class RingTests(unittest.TestCase):
    def test_color_boundaries_match_panel_and_tray(self):
        for level, expected in ((0, "#ff6b6b"), (29, "#ff6b6b"), (30, "#f5c451"),
                                (59, "#f5c451"), (60, "#5ddc8a"), (100, "#5ddc8a")):
            self.assertEqual(ui.level_color(level), expected)
            rgb = tray_app.TrayApp._color(level)
            self.assertEqual("#%02x%02x%02x" % rgb, expected)

    def test_tray_ring_fill_without_digits(self):
        color = (93, 220, 138)
        for size in win_icon.SIZES:
            counts = []
            for level in (0, 25, 50, 75, 100):
                raw = win_icon.render_rgba(str(level), size, color)
                pixels = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
                self.assertEqual(len(pixels), size * size)
                self.assertEqual(pixels[0][3], 0)
                counts.append(sum(pixel[:3] == color for pixel in pixels))
                self.assertFalse(any(p[:3] == (239, 243, 249) for p in pixels),
                                 f"{size}px / {level}% 仍有中央数字")
            self.assertEqual(counts, sorted(set(counts)), f"{size}px 环长没有随电量增长")

    def test_quarter_ring_runs_clockwise_from_top(self):
        size, color = 160, (245, 196, 81)
        raw = win_icon.render_rgba("25", size, color)
        def pixel(x, y):
            offset = (y * size + x) * 4
            return tuple(raw[offset:offset + 3])
        self.assertEqual(pixel(80, 13), color)
        self.assertEqual(pixel(146, 80), color)
        self.assertNotEqual(pixel(80, 146), color)
        self.assertNotEqual(pixel(13, 80), color)

    def test_unknown_is_gray_and_different_from_empty(self):
        unknown = win_icon.render_rgba("--", 16, (150, 155, 160))
        empty = win_icon.render_rgba("0", 16, (255, 107, 107))
        self.assertNotEqual(unknown, empty)
        self.assertNotIn(bytes((255, 107, 107, 255)), unknown)

    def test_charging_bolt_keeps_ring_and_hides_when_unknown(self):
        for size in win_icon.SIZES:
            for level in (0, 32, 100):
                with self.subTest(size=size, level=level):
                    plain = win_icon.render_rgba(str(level), size, (93, 220, 138))
                    charging = win_icon.render_rgba(str(level), size, (93, 220, 138),
                                                    charging=True)
                    self.assertIn(bytes((239, 243, 249, 255)), charging)
                    for y in range(size):
                        for x in range(size):
                            if math.hypot(x + .5 - size / 2, y + .5 - size / 2) >= size * .36:
                                offset = (y * size + x) * 4
                                self.assertEqual(plain[offset:offset + 4], charging[offset:offset + 4])
            self.assertEqual(win_icon.render_rgba("--", size, (150, 155, 160)),
                             win_icon.render_rgba("--", size, (150, 155, 160), charging=True))

    def test_charging_state_has_separate_cached_icon(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(win_icon._icon_cache, {}, clear=True), \
             patch.object(win_icon, "_ensure_tmp", return_value=directory), \
             patch.object(win_icon.user32, "LoadImageW", side_effect=[101, 202]) as load:
            plain = win_icon.make_hicon("32", (245, 196, 81))
            charging = win_icon.make_hicon("32", (245, 196, 81), charging=True)
            self.assertNotEqual(plain, charging)
            self.assertEqual(win_icon.make_hicon("32", (245, 196, 81)), plain)
            self.assertNotEqual(load.call_args_list[0].args[1], load.call_args_list[1].args[1])

    def test_device_status_reaches_tray_and_tooltip(self):
        app = tray_app.TrayApp.__new__(tray_app.TrayApp)
        app.hwnd = None
        app.readings = {}
        tips = []
        def notify(action, pointer):
            tips.append(pointer._obj.szTip)
            return True
        cases = [(32, "discharging", True), (32, "charging", True),
                 (32, "discharging", True), (100, "full", True),
                 (0, "charging", True), (32, "charging", False)]
        for level, status, ok in cases:
            result = bt.BatteryResult(ok=ok, level=level, status=status, detail="未连接" if not ok else "")
            with self.subTest(level=level, status=status, ok=ok), \
                 patch.object(bt, "read_rog_mouse", return_value=result), \
                 patch.object(bt, "read_rog_headset", return_value=result), \
                 patch.object(tray_app.USER32, "PostMessageW"), \
                 patch.object(win_icon, "make_hicon", return_value=1) as icon, \
                 patch.object(tray_app.SHELL32, "Shell_NotifyIconW", side_effect=notify):
                app._worker(0)
                for uid, key, title in tray_app.TRAY_ICONS:
                    self.assertTrue(app._apply_icon(tray_app.NIM_MODIFY, uid, key, title))
                    self.assertEqual(icon.call_args.kwargs["charging"], ok and status == "charging")
                    self.assertIn(f"{level}% · {result.status_text}" if ok else "未连接", tips[-1])
                    self.assertEqual(icon.call_args.args[0], str(level) if ok else "--")

    def test_background_is_transparent_in_rgba_and_ico(self):
        for size in win_icon.SIZES:
            for text, charging in (("0", False), ("32", False), ("100", False),
                                   ("32", True), ("--", False)):
                with self.subTest(size=size, text=text, charging=charging):
                    raw = win_icon.render_rgba(text, size, (93, 220, 138), charging=charging)
                    alphas = raw[3::4]
                    center = (size // 2 * size + size // 2) * 4
                    if text.isdecimal() and not charging:
                        self.assertEqual(raw[center:center + 4], bytes(4))
                    self.assertIn(0, alphas)
                    self.assertIn(255, alphas)
                    self.assertTrue(any(0 < alpha < 255 for alpha in alphas))
                    ico = win_icon.build_ico([(size, raw)])
                    offset = struct.unpack_from("<I", ico, 18)[0] + 40
                    stored = ico[offset:offset + size * size * 4]
                    rows = [alphas[y * size:(y + 1) * size] for y in range(size)]
                    self.assertEqual(stored[3::4], b"".join(reversed(rows)))
                    self.assertNotIn(bytes((18, 22, 28, 255)), raw)
                    self.assertNotIn(bytes((28, 30, 34, 255)), raw)

    def test_panel_clears_old_level_when_disconnected(self):
        root = tk.Tk()
        root.withdraw()
        try:
            card = ui.DeviceCard(root, "ROG PELTA 耳机")
            for level in (100, 60, 30, 0):
                card.update(ui.Reading("耳机", "USB", level=level, status="充电中"))
                self.assertEqual(card.ring.itemcget(card.value, "text"), f"{level}%")
                self.assertEqual(card.ring.itemcget(card.value, "fill"), ui.level_color(level))
                extent = abs(float(card.ring.itemcget(card.arc, "extent")))
                self.assertTrue(math.isclose(extent, min(level * 3.6, 359.99), abs_tol=.01))
            card.update(ui.Reading("耳机", "未连接", error="请连接耳机"))
            self.assertEqual(card.ring.itemcget(card.value, "text"), "--")
            self.assertEqual(card.ring.itemcget(card.arc, "state"), "hidden")
            self.assertEqual(card.ring.itemcget(card.end_cap, "state"), "hidden")
            self.assertEqual(card.lab_detail.cget("text"), "请连接耳机")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
