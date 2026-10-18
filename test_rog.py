"""ROG 协议回归检查：python -m unittest -v test_rog。无需连接设备。"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import battery as bt


def interface(pid, page, length=64, path="test"):
    return SimpleNamespace(vid=0x0B05, pid=pid, usage_page=page,
                           output_len=length, path=path, vid_pid=f"0B05:{pid:04X}")


def reply(report_id, cmd, data=b"", sub=b""):
    return (bytes([report_id, 0x12, cmd]) + sub.ljust(2, b"\x00") + data).ljust(64, b"\x00")


class RogTests(unittest.TestCase):
    def read(self, iface, reports):
        dev = MagicMock()
        dev.read_input.side_effect = reports
        with patch.object(bt, "HidDevice") as factory:
            factory.return_value.__enter__.return_value = dev
            result = bt.strategy_rog(iface)
        return result, dev

    def test_mouse_real_capture(self):
        capture = bytes.fromhex("03 12 07 00 00 25 02 14 b7 0e 00").ljust(64, b"\x00")
        result, dev = self.read(interface(0x1ACE, 0xFF01, path="mi_02&col03"), [capture])
        self.assertEqual((result.ok, result.level, result.status), (True, 37, "discharging"))
        dev.write_output.assert_called_once_with(bytes([3, 0x12, 7]).ljust(64, b"\x00"),
                                                 use_hidd=False)

    def test_pelta_usb_real_capture(self):
        power = bytes.fromhex("cc 12 07 00 00 05 64 14 01").ljust(64, b"\x00")
        result, _ = self.read(interface(0x1B82, 0xFF00), [power, reply(0xCC, 8)])
        self.assertEqual((result.ok, result.level, result.status), (True, 100, "full"))

    def test_wired_mouse_real_capture(self):
        capture = bytes.fromhex("00 12 07 00 00 1c 02 14 9c 10 01").ljust(65, b"\x00")
        result, dev = self.read(interface(0x1A92, 0xFF01, 65), [capture])
        self.assertEqual((result.ok, result.level, result.status), (True, 28, "charging"))
        self.assertEqual(result.extra["connection"], "USB 有线")
        dev.write_output.assert_called_once_with(bytes([0, 0x12, 7]).ljust(65, b"\x00"),
                                                 use_hidd=False)

    def test_mouse_prefers_usb_and_falls_back_to_wireless(self):
        wired = interface(0x1A92, 0xFF01, 65)
        wireless = interface(0x1ACE, 0xFF01, path="mi_02&col03")
        good = bt.BatteryResult(ok=True, level=28, status="charging")
        for results, expected in (([good], [0x1A92]),
                                  ([bt.BatteryResult(ok=False), good], [0x1A92, 0x1ACE])):
            with self.subTest(expected=expected), \
                 patch.object(bt.hw, "enumerate_hid", return_value=[wireless, wired]), \
                 patch.object(bt, "strategy_rog", side_effect=results) as read:
                self.assertIs(bt.read_rog_mouse(), good)
                self.assertEqual([call.args[0].pid for call in read.call_args_list], expected)

    def test_wireless_pelta_charging_at_zero(self):
        reports = [reply(0xCC, 0, b"\x01", b"\x00\x01"),
                   reply(0xCC, 7, b"\x05\x00"), reply(0xCC, 8, b"\x01")]
        result, _ = self.read(interface(0x1B84, 0xFF00), reports)
        self.assertEqual((result.ok, result.level, result.status), (True, 0, "charging"))

    def test_disconnected_wireless_pelta(self):
        result, dev = self.read(interface(0x1B84, 0xFF00),
                                [reply(0xCC, 0, sub=b"\x00\x01")])
        self.assertFalse(result.ok)
        self.assertIn("2.4G 未连接", result.detail)
        self.assertEqual(dev.write_output.call_count, 1)

    def test_invalid_and_asleep_mouse(self):
        iface = interface(0x1ACE, 0xFF01, path="mi_02&col03")
        for data in (b"\xff\xaa", b"\x00", b"\x65"):
            with self.subTest(data=data):
                result, _ = self.read(iface, [reply(3, 7, data)])
                self.assertFalse(result.ok)
                self.assertIsNone(result.level)

    def test_short_reply(self):
        result, _ = self.read(interface(0x1B82, 0xFF00), [b"\xcc\x12\x07"])
        self.assertFalse(result.ok)
        self.assertIn("长度不足", result.detail)

    def test_unrelated_interface_is_not_written(self):
        with patch.object(bt, "HidDevice") as factory:
            for iface in (interface(0x1A64, 0xFF00), interface(0x1ACE, 0xFF01),
                          interface(0x1B84, 0xFF07), interface(0x1B82, 0xFF00, 65),
                          interface(0x1A92, 0xFFC1, 65), interface(0x1A92, 0xFF01, 64)):
                self.assertIsNone(bt.strategy_rog(iface))
            factory.assert_not_called()

    def test_timeout_ignores_foreign_reply(self):
        dev = MagicMock()
        dev.read_input.return_value = reply(3, 8)
        with patch.object(bt.time, "monotonic", side_effect=[0, 0, 1]):
            with self.assertRaisesRegex(bt.HidError, "没有回复"):
                bt._rog_query(dev, 3, 7, 64)

    def test_headset_falls_back_to_usb(self):
        wireless = interface(0x1B84, 0xFF00)
        wired = interface(0x1B82, 0xFF00)
        good = bt.BatteryResult(ok=True, level=100)
        with patch.object(bt.hw, "enumerate_hid", return_value=[wired, wireless]), \
             patch.object(bt, "strategy_rog", side_effect=[bt.BatteryResult(ok=False), good]) as read:
            self.assertIs(bt.read_rog_headset(), good)
            self.assertEqual([c.args[0].pid for c in read.call_args_list], [0x1B84, 0x1B82])


if __name__ == "__main__":
    unittest.main()
