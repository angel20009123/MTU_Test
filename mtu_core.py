"""IPv4 ICMP probes using Windows IP Helper API (no administrator required)."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import socket
import statistics


@dataclass
class Probe:
    payload: int
    status: str
    rtt_ms: float | None = None
    detail: str = ""

    @property
    def packet_size(self):
        return self.payload + 28


class WindowsPing:
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


def discover_mtu(ping, lower, upper, attempts, timeout, cancel, emit):
    """Only explicit packet-too-big replies lower the upper bound."""
    def check(mtu):
        for _ in range(attempts):
            if cancel.is_set():
                return "cancelled"
            result = ping(mtu - 28, timeout, True)
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
            "message": f"路径 MTU {'至少为' if capped else '为'} {best} 字节（IPv4 + ICMP 头共 28 字节）。"}


def summarize(probes):
    good = [p.rtt_ms for p in probes if p.status == "ok"]
    total = len(probes)
    return {"sent": total, "received": len(good),
            "loss_percent": round(100 * (total - len(good)) / total, 2) if total else 0,
            "min_ms": min(good) if good else None,
            "avg_ms": round(statistics.mean(good), 2) if good else None,
            "max_ms": max(good) if good else None,
            "jitter_ms": round(statistics.mean(abs(b-a) for a, b in zip(good, good[1:])), 2) if len(good) > 1 else None}
