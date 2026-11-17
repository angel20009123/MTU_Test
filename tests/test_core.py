import threading
import unittest
from mtu_core import Probe, discover_mtu, summarize, WindowsPing
import sys


class CoreTests(unittest.TestCase):
    def discover(self, ping, upper=1600):
        return discover_mtu(ping, 576, upper, 3, 100, threading.Event(), lambda p: None)

    def test_boundary(self):
        result = self.discover(lambda size, *args: Probe(size, "ok" if size + 28 <= 1492 else "too_big"))
        self.assertEqual(result["mtu"], 1492)
        self.assertEqual(result["state"], "complete")

    def test_cap_is_lower_bound(self):
        self.assertEqual(self.discover(lambda size, *args: Probe(size, "ok"))["state"], "lower_bound")

    def test_timeout_is_not_mtu_boundary(self):
        result = self.discover(lambda size, *args: Probe(size, "ok" if size == 548 else "timeout"))
        self.assertIsNone(result["mtu"])
        self.assertEqual(result["verified_lower_bound"], 576)

    def test_retries_recover(self):
        seen = set()
        def ping(size, *args):
            if size not in seen:
                seen.add(size)
                return Probe(size, "timeout")
            return Probe(size, "ok" if size + 28 <= 1500 else "too_big")
        self.assertEqual(self.discover(ping)["mtu"], 1500)

    def test_cancel(self):
        event = threading.Event()
        event.set()
        result = discover_mtu(lambda *args: self.fail("must not probe"), 576, 1500, 3, 100, event, lambda p: None)
        self.assertEqual(result["state"], "cancelled")

    def test_statistics(self):
        result = summarize([Probe(32, "ok", 10), Probe(32, "timeout"), Probe(32, "ok", 20)])
        self.assertEqual(result["avg_ms"], 15)
        self.assertEqual(result["loss_percent"], 33.33)
        self.assertEqual(result["jitter_ms"], 10)
        self.assertIsNone(summarize([])["avg_ms"])

    @unittest.skipUnless(sys.platform == "win32", "Windows API")
    def test_loopback(self):
        client = WindowsPing("127.0.0.1")
        try:
            result = client.ping(32)
            self.assertEqual(result.status, "ok", result.detail)
        finally:
            client.close()

    @unittest.skipUnless(sys.platform == "win32", "Windows API")
    def test_large_payloads_loopback(self):
        client = WindowsPing("127.0.0.1")
        try:
            for size in (20000, 24000, 32768, 48000, 60000, 65500):
                with self.subTest(payload=size):
                    result = client.ping(size, 1000, False)
                    self.assertEqual(result.status, "ok", result.detail)
                    self.assertIn("校验通过", result.detail)
            for size in (-1, 65501):
                with self.assertRaises(ValueError):
                    client.ping(size)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
