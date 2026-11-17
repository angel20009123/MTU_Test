import threading
import unittest
from mtu_core import (Probe, discover_mtu, summarize, WindowsPing,
                      WindowsIPv6Ping, WindowsIPv6MTU, decode_ipv6_reply, resolve_ipv6)
import ctypes
import socket
import struct
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

    def test_ipv6_boundary_and_overhead(self):
        probes = []
        result = discover_mtu(lambda size, *args: Probe(size, 'ok' if size + 48 <= 1648 else 'too_big', ip_version=6),
                              1280, 2000, 3, 100, threading.Event(), probes.append, 6)
        self.assertEqual(result['mtu'], 1648)
        self.assertEqual(probes[0].payload, 1232)
        self.assertEqual(Probe(1800, 'ok', ip_version=6).packet_size, 1848)

    def test_ipv6_timeout_is_not_boundary(self):
        result = discover_mtu(lambda size, *args: Probe(size, 'ok' if size == 1232 else 'timeout', ip_version=6),
                              1280, 2000, 2, 100, threading.Event(), lambda p: None, 6)
        self.assertIsNone(result['mtu'])
        self.assertEqual(result['verified_lower_bound'], 1280)

    def test_ipv6_reply_matching(self):
        payload = b'payload'
        reply = struct.pack('!BBHHH', 129, 0, 0, 123, 456) + payload
        self.assertEqual(decode_ipv6_reply(reply, '::1', '::1', 123, 456, payload)[0], 'ok')
        self.assertIsNone(decode_ipv6_reply(reply, '::1', '::1', 123, 457, payload))
        self.assertIsNone(decode_ipv6_reply(reply, '::2', '::1', 123, 456, payload))
        self.assertEqual(decode_ipv6_reply(reply[:-1], '::1', '::1', 123, 456, payload)[0], 'corrupt')
        header = struct.pack('!IHBB16s16s', 6 << 28, 15, 58, 64, socket.inet_pton(socket.AF_INET6, '::2'), socket.inet_pton(socket.AF_INET6, '::1'))
        request = struct.pack('!BBHHH', 128, 0, 0, 123, 456) + payload
        error = struct.pack('!BBHI', 2, 0, 0, 1500) + header + request
        decoded = decode_ipv6_reply(error, '::3', '::1', 123, 456, payload)
        self.assertEqual(decoded[0], 'too_big')
        self.assertIn('1500', decoded[1])
        self.assertIsNone(decode_ipv6_reply(error, '::3', '::1', 123, 457, payload))

    def test_ipv6_resolve(self):
        self.assertEqual(resolve_ipv6('[::1]')[0], '::1')
        self.assertEqual(resolve_ipv6('fe80::1%12')[3], 12)
        for address in ('::', 'ff02::1', 'fe80::1'):
            with self.assertRaises(ValueError):
                resolve_ipv6(address)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows API')
    def test_ipv6_loopback(self):
        client = WindowsIPv6Ping('::1')
        try:
            for size in (0, 32, 1600, 1800, 20000, 65500):
                with self.subTest(payload=size):
                    result = client.ping(size)
                    self.assertEqual(result.status, 'ok', result.detail)
                    self.assertEqual(result.packet_size, size + 48)
            with self.assertRaises(ValueError):
                client.ping(32, df=True)
        finally:
            client.close()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows raw sockets')
    def test_ipv6_raw_or_permission_message(self):
        try:
            client = WindowsIPv6MTU('::1')
        except PermissionError as exc:
            self.assertIn('管理员权限', str(exc))
            return
        try:
            for size in (32, 1232, 1600, 1800):
                result = client.ping(size)
                self.assertEqual(result.status, 'ok', result.detail)
            result = discover_mtu(client.ping, 1280, 2000, 2, 1000, threading.Event(), lambda p: None, 6)
            self.assertEqual(result['state'], 'lower_bound', result)
            self.assertEqual(result['mtu'], 2000)
        finally:
            client.close()

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
