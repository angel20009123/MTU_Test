"""Windows IPv4/IPv6 ICMP probes and conservative path MTU discovery."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import socket
import statistics
import struct
import secrets
import time


@dataclass
class Probe:
    payload: int
    status: str
    rtt_ms: float | None = None
    detail: str = ""
    ip_version: int = 4

    @property
    def packet_size(self):
        return self.payload + (48 if self.ip_version == 6 else 28)


class WindowsPing:
    ip_version = 4
    def __init__(self, host):
        if not hasattr(ctypes, "WinDLL"):
            raise RuntimeError("此版本需要 Windows 系统")
        self.address = socket.gethostbyname(host)
        self.dll = ctypes.WinDLL("iphlpapi", use_last_error=True)

        class Options(ctypes.Structure):
            _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte),
                        ("Flags", ctypes.c_ubyte), ("OptionsSize", ctypes.c_ubyte),
                        ("OptionsData", ctypes.c_void_p)]

        class Reply(ctypes.Structure):
            _fields_ = [("Address", wintypes.DWORD), ("Status", wintypes.DWORD),
                        ("RoundTripTime", wintypes.DWORD), ("DataSize", wintypes.WORD),
                        ("Reserved", wintypes.WORD), ("Data", ctypes.c_void_p),
                        ("Options", Options)]

        self.Options, self.Reply = Options, Reply
        self.dll.IcmpCreateFile.restype = wintypes.HANDLE
        self.dll.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
        self.dll.IcmpSendEcho.argtypes = [wintypes.HANDLE, wintypes.DWORD,
            ctypes.c_void_p, wintypes.WORD, ctypes.POINTER(Options),
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
        self.dll.IcmpSendEcho.restype = wintypes.DWORD
        self.handle = self.dll.IcmpCreateFile()
        if self.handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle is not None:
            self.dll.IcmpCloseHandle(self.handle)
            self.handle = None

    def ping(self, payload, timeout_ms=1000, df=True):
        if not 0 <= payload <= 65500:
            raise ValueError("ICMP 负载必须在 0–65500 字节之间")
        request = ctypes.create_string_buffer(bytes(i % 251 for i in range(payload)))
        reply = ctypes.create_string_buffer(ctypes.sizeof(self.Reply) + payload + 8)
        options = self.Options(128, 0, 2 if df else 0, 0, None)
        destination = int.from_bytes(socket.inet_aton(self.address), "little")
        count = self.dll.IcmpSendEcho(self.handle, destination, request, payload,
            ctypes.byref(options), reply, len(reply), timeout_ms)
        if count:
            result = self.Reply.from_buffer(reply)
            code = result.Status
            rtt = float(result.RoundTripTime) if code == 0 else None
            if code == 0:
                if result.DataSize != payload or (payload and (not result.Data or ctypes.string_at(result.Data, payload) != request.raw[:payload])):
                    return Probe(payload, "corrupt", None, f"返回负载 {result.DataSize} B，预期 {payload} B；内容或长度不匹配")
        else:
            code, rtt = ctypes.get_last_error(), None
        status = {0: "ok", 11009: "too_big", 11010: "timeout"}.get(code, "error")
        detail = f"IP_STATUS={code}"
        if status == "ok":
            detail += f"；负载 {payload} B 校验通过"
        return Probe(payload, status, rtt, detail)


def discover_mtu(ping, lower, upper, attempts, timeout, cancel, emit, ip_version=4):
    """Only explicit packet-too-big replies lower the upper bound."""
    overhead = 48 if ip_version == 6 else 28
    if not overhead <= lower <= upper <= 65500 + overhead:
        raise ValueError("无效的 MTU 搜索范围")
    def check(mtu):
        for _ in range(attempts):
            if cancel.is_set():
                return "cancelled"
            result = ping(mtu - overhead, timeout, True)
            emit(result)
            if result.status != "timeout":
                return result.status
        return "timeout"

    state = check(lower)
    if state != "ok":
        return {"state": state, "mtu": None, "message": "最小包未成功，无法确定路径 MTU；请检查目标是否响应 ICMP。"}
    best, low, high = lower, lower + 1, upper
    while low <= high:
        mid = (low + high) // 2
        state = check(mid)
        if state == "ok":
            best, low = mid, mid + 1
        elif state == "too_big":
            high = mid - 1
        else:
            return {"state": state, "mtu": None, "verified_lower_bound": best,
                    "message": f"探测中断：{state}。已确认至少可通过 {best} 字节，未确定上限。"}
    capped = best == upper
    return {"state": "lower_bound" if capped else "complete", "mtu": best,
            "message": f"路径 MTU {'至少为' if capped else '为'} {best} 字节（IPv{ip_version} + ICMP 头共 {overhead} 字节）。"}


def resolve_ipv6(host):
    """Resolve AAAA or an IPv6 literal, retaining link-local scope ID."""
    host = host.strip()
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]
    destination = socket.getaddrinfo(host, 0, socket.AF_INET6, socket.SOCK_DGRAM)[0][4]
    packed = socket.inet_pton(socket.AF_INET6, destination[0].split('%')[0])
    if packed[0] == 255:
        raise ValueError("请选择单播 IPv6 地址，不支持组播目标")
    if packed == bytes(16):
        raise ValueError("不能将未指定地址 :: 作为目标")
    if packed[:2] == b'\xfe\x80' and not destination[3]:
        raise ValueError("链路本地地址请带接口编号，例如 fe80::1%12")
    return destination


class WindowsIPv6Ping:
    """Ordinary IPv6 Ping; fragmentation is managed by the Windows stack."""
    ip_version = 6

    def __init__(self, host):
        self.destination = resolve_ipv6(host)
        self.address = self.destination[0]
        if self.destination[3] and '%' not in self.address:
            self.address += f"%{self.destination[3]}"
        self.dll = ctypes.WinDLL("iphlpapi", use_last_error=True)

        class Sockaddr6(ctypes.Structure):
            _fields_ = [("family", ctypes.c_ushort), ("port", ctypes.c_ushort),
                        ("flow", ctypes.c_uint32), ("address", ctypes.c_ubyte * 16),
                        ("scope", ctypes.c_uint32)]

        class AddressEx(ctypes.Structure):
            _fields_ = [("port", ctypes.c_ushort), ("flow", ctypes.c_uint32),
                        ("address", ctypes.c_ushort * 8), ("scope", ctypes.c_uint32)]

        class Reply6(ctypes.Structure):
            _fields_ = [("address", AddressEx), ("status", ctypes.c_uint32), ("rtt", ctypes.c_uint32)]

        self.Reply6 = Reply6
        self.source = Sockaddr6()
        self.source.family = socket.AF_INET6
        self.target = Sockaddr6()
        self.target.family = socket.AF_INET6
        self.target.scope = self.destination[3]
        self.target.address[:] = socket.inet_pton(socket.AF_INET6, self.destination[0].split('%')[0])
        self.dll.Icmp6CreateFile.restype = wintypes.HANDLE
        self.dll.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
        self.dll.Icmp6SendEcho2.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Sockaddr6), ctypes.POINTER(Sockaddr6),
            ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
        self.dll.Icmp6SendEcho2.restype = wintypes.DWORD
        self.dll.Icmp6ParseReplies.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        self.dll.Icmp6ParseReplies.restype = wintypes.DWORD
        self.handle = self.dll.Icmp6CreateFile()
        if self.handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())

    close = WindowsPing.close

    def ping(self, payload, timeout_ms=1000, df=False):
        if df:
            raise ValueError("普通 IPv6 Ping 由系统管理分片；禁止分片请使用 IPv6 MTU 探测")
        if not 0 <= payload <= 65500:
            raise ValueError("ICMPv6 负载必须在 0–65500 字节之间")
        data = bytes(i % 251 for i in range(payload))
        request = ctypes.create_string_buffer(data)
        offset = ctypes.sizeof(self.Reply6)
        reply = ctypes.create_string_buffer(offset + payload + 8 + 2 * ctypes.sizeof(ctypes.c_void_p))
        count = self.dll.Icmp6SendEcho2(self.handle, None, None, None,
            ctypes.byref(self.source), ctypes.byref(self.target), request, payload,
            None, reply, len(reply), timeout_ms)
        if count:
            self.dll.Icmp6ParseReplies(reply, len(reply))
            result = self.Reply6.from_buffer(reply)
            code = result.status
            rtt = float(result.rtt) if code == 0 else None
            if code == 0 and reply.raw[offset:offset + payload] != data:
                return Probe(payload, "corrupt", None, "ICMPv6 返回负载内容不匹配", 6)
        else:
            code, rtt = ctypes.get_last_error(), None
        status = {0: "ok", 11009: "too_big", 11010: "timeout"}.get(code, "error")
        detail = f"IPv6 IP_STATUS={code}"
        if status == 'ok':
            detail += f"；负载 {payload} B 内容校验通过（API 不提供回包长度）"
        return Probe(payload, status, rtt, detail, 6)


def checksum(data):
    if len(data) % 2:
        data += b'\0'
    total = sum(struct.unpack(f'!{len(data)//2}H', data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535


def decode_ipv6_reply(data, peer, destination, identifier, sequence, payload):
    """Ignore unrelated traffic, including stale echoes and unrelated ICMP errors."""
    if len(data) < 8:
        return None
    kind, code, _, ident, seq = struct.unpack('!BBHHH', data[:8])
    target = socket.inet_pton(socket.AF_INET6, destination.split('%')[0])
    if kind == 129:
        if code != 0 or ident != identifier or seq != sequence or socket.inet_pton(socket.AF_INET6, peer.split('%')[0]) != target:
            return None
        return ('ok', 'ICMPv6 回包长度及内容校验通过') if data[8:] == payload else ('corrupt', 'ICMPv6 回包长度或内容不匹配')
    if kind not in (1, 2, 3, 4) or len(data) < 56:
        return None
    quoted = data[8:]
    # Our unfragmented requests have no extension headers.
    if quoted[0] >> 4 != 6 or quoted[6] != 58 or quoted[24:40] != target:
        return None
    if quoted[40] != 128 or struct.unpack('!HH', quoted[44:48]) != (identifier, sequence):
        return None
    if kind == 2 and code == 0:
        return 'too_big', f"ICMPv6 Packet Too Big；设备报告 MTU={struct.unpack('!I', data[4:8])[0]} B"
    return 'error', f"ICMPv6 错误 Type={kind}, Code={code}"


class WindowsIPv6MTU:
    """Raw ICMPv6 with IPV6_DONTFRAG; requires an elevated process."""
    ip_version = 6

    def __init__(self, host):
        self.destination = resolve_ipv6(host)
        self.address = self.destination[0]
        self.sock = None
        try:
            self.sock = socket.socket(socket.AF_INET6, socket.SOCK_RAW, socket.IPPROTO_ICMPV6)
            # Windows ws2ipdef.h: IPV6_DONTFRAG = 14.
            self.sock.setsockopt(socket.IPPROTO_IPV6, 14, 1)
            with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as route:
                route.connect(self.destination)
                self.source = route.getsockname()
            self.sock.bind((self.source[0], 0, self.source[2], self.source[3]))
        except OSError as exc:
            self.close()
            if isinstance(exc, PermissionError) or getattr(exc, 'winerror', None) == 10013:
                raise PermissionError("IPv6 MTU 探测需要管理员权限，请关闭程序后右键 EXE → 以管理员身份运行。普通 IPv6 数据包测试无需管理员权限。") from exc
            raise
        self.identifier = secrets.randbelow(65536)
        self.sequence = secrets.randbelow(65536)

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def ping(self, payload, timeout_ms=1000, df=True):
        if not df:
            raise ValueError("IPv6 MTU 探测仅支持禁止源端分片")
        if not 0 <= payload <= 65500:
            raise ValueError("ICMPv6 负载必须在 0–65500 字节之间")
        self.sequence = (self.sequence + 1) % 65536
        data = bytes(i % 251 for i in range(payload))
        packet = struct.pack('!BBHHH', 128, 0, 0, self.identifier, self.sequence) + data
        pseudo = socket.inet_pton(socket.AF_INET6, self.source[0].split('%')[0]) + socket.inet_pton(socket.AF_INET6, self.destination[0].split('%')[0]) + struct.pack('!I3xB', len(packet), 58)
        packet = packet[:2] + struct.pack('!H', checksum(pseudo + packet)) + packet[4:]
        start = time.perf_counter()
        deadline = start + timeout_ms / 1000
        try:
            self.sock.sendto(packet, self.destination)
            while time.perf_counter() < deadline:
                self.sock.settimeout(max(.001, deadline - time.perf_counter()))
                response, peer = self.sock.recvfrom(65575)
                decoded = decode_ipv6_reply(response, peer[0], self.address, self.identifier, self.sequence, data)
                if decoded:
                    status, detail = decoded
                    rtt = round((time.perf_counter() - start) * 1000, 3) if status == 'ok' else None
                    return Probe(payload, status, rtt, detail, 6)
        except socket.timeout:
            pass
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 10040:
                return Probe(payload, 'too_big', None, '本机禁止分片发送失败：WSAEMSGSIZE', 6)
            return Probe(payload, 'error', None, str(exc), 6)
        return Probe(payload, 'timeout', None, 'IPv6 超时；不能据此确定 MTU', 6)


def summarize(probes):
    good = [p.rtt_ms for p in probes if p.status == "ok"]
    total = len(probes)
    return {"sent": total, "received": len(good),
            "loss_percent": round(100 * (total - len(good)) / total, 2) if total else 0,
            "min_ms": min(good) if good else None,
            "avg_ms": round(statistics.mean(good), 2) if good else None,
            "max_ms": max(good) if good else None,
            "jitter_ms": round(statistics.mean(abs(b-a) for a, b in zip(good, good[1:])), 2) if len(good) > 1 else None}
