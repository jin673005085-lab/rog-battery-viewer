"""圆环回归检查：python -m unittest -v test_ui。"""
import math
import tkinter as tk
import unittest

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

    def test_tray_ring_fill_and_legible_digits(self):
        color = (93, 220, 138)
        for size in win_icon.SIZES:
            counts = []
            for level in (0, 25, 50, 75, 100):
                raw = win_icon.render_rgba(str(level), size, color)
                pixels = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
                self.assertEqual(len(pixels), size * size)
                self.assertEqual(pixels[0][3], 0)
                counts.append(sum(pixel[:3] == color for pixel in pixels))
                self.assertTrue(any(p[:3] == (239, 243, 249) for p in pixels),
                                f"{size}px / {level}% 中央数字丢失")
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
