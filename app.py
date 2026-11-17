import csv
from dataclasses import asdict
from datetime import datetime
import json
import queue
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from mtu_core import WindowsPing, WindowsIPv6Ping, WindowsIPv6MTU, discover_mtu, summarize
from version import VERSION


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"链路实验室 v{VERSION} · MTU 与数据包测试")
        self.geometry("1200x920")
        self.minsize(1100, 850)
        icon = Path(__file__).resolve().parent / "assets" / "link_lab.ico"
        if icon.exists():
            self.iconbitmap(str(icon))
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.running = False
        self.probes = []
        self.report = {}
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("TButton", padding=8)
        outer = ttk.Frame(self, padding=22)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=f"链路实验室  v{VERSION}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="IPv4 / IPv6 路径 MTU 探测 · 数据包大小、丢包率与延迟测试").pack(anchor="w", pady=(4, 12))
        protocol_row = ttk.Frame(outer)
        protocol_row.pack(fill='x', pady=(0, 10))
        ttk.Label(protocol_row, text="IP 协议：").pack(side='left')
        self.protocol_version = tk.StringVar(value='IPv4')
        self.protocol_box = ttk.Combobox(protocol_row, textvariable=self.protocol_version, values=('IPv4', 'IPv6'), state='readonly', width=10)
        self.protocol_box.pack(side='left', padx=6)
        self.protocol_box.bind('<<ComboboxSelected>>', self.protocol_changed)
        ttk.Label(protocol_row, text="IPv6 支持地址 / 域名；链路本地地址示例 fe80::1%12").pack(side='left', padx=8)
        box = ttk.LabelFrame(outer, text="测试参数", padding=12)
        box.pack(fill="x")
        self.values = {}
        fields = [("host", "目标 IP / 域名", "127.0.0.1"),
                  ("lower", "MTU 下限（字节）", "576"), ("upper", "MTU 上限（字节）", "65528"),
                  ("sizes", "ICMP 负载（逗号分隔）", "32,512,1400,1472"),
                  ("count", "每种包长次数", "10"), ("interval", "发包间隔（毫秒）", "200"),
                  ("timeout", "超时（毫秒）", "1000"), ("attempts", "MTU 每点重试次数", "3")]
        for i, (key, label, default) in enumerate(fields):
            row, col = divmod(i, 4)
            cell = ttk.Frame(box, padding=5)
            cell.grid(row=row, column=col, sticky="ew")
            box.columnconfigure(col, weight=1)
            ttk.Label(cell, text=label).pack(anchor="w")
            var = tk.StringVar(value=default)
            self.values[key] = var
            ttk.Entry(cell, textvariable=var, width=24).pack(fill="x", pady=(5, 0))
        self.df = tk.BooleanVar(value=False)
        self.df_check = ttk.Checkbutton(box, text="IPv4 数据包测试禁止分片（DF）；IPv6 普通 Ping 由系统管理源端分片", variable=self.df)
        self.df_check.grid(row=2, column=0, columnspan=4, sticky="w", pady=7)
        presets = ttk.Frame(box)
        presets.grid(row=3, column=0, columnspan=4, sticky="ew")
        ttk.Button(presets, text="大包预设：20K–65.5K", command=lambda: self.preset(True)).pack(side="left")
        ttk.Button(presets, text="常规包预设", command=lambda: self.preset(False)).pack(side="left", padx=8)
        ttk.Button(presets, text="1600–1800 B 诊断", command=self.diagnostic_preset).pack(side='left')
        ttk.Label(presets, text="负载范围 0–65500 B").pack(side="left", padx=8)
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=12)
        self.mtu_button = ttk.Button(actions, text="探测路径 MTU", command=lambda: self.start("mtu"))
        self.mtu_button.pack(side="left")
        self.packet_button = ttk.Button(actions, text="开始数据包测试", command=lambda: self.start("packets"))
        self.packet_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(actions, text="停止", command=self.stop, state="disabled")
        self.stop_button.pack(side="left")
        ttk.Button(actions, text="导出报告", command=self.export).pack(side="right")
        self.status = tk.StringVar(value="就绪 · 请填写您要测试的目标地址")
        ttk.Label(outer, textvariable=self.status, wraplength=980).pack(anchor="w", pady=6)
        self.summary = tk.StringVar(value="发送 0  /  接收 0  /  丢包 —  /  平均延迟 —")
        ttk.Label(outer, textvariable=self.summary, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=8)
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        frame = ttk.Frame(notebook)
        notebook.add(frame, text="逐包明细")
        columns = ("seq", "payload", "packet", "status", "rtt", "detail")
        self.table = ttk.Treeview(frame, columns=columns, show="headings")
        for key, label, width in zip(columns, ["序号", "ICMP 负载 / B", "基础 IP 总长 / B", "结果", "延迟 / ms", "详情"], [60, 125, 140, 145, 110, 360]):
            self.table.heading(key, text=label)
            self.table.column(key, width=width)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        grouped = ttk.Frame(notebook)
        notebook.add(grouped, text="按包长统计")
        keys = ("payload", "packet", "sent", "received", "loss", "min", "avg", "max")
        self.group_table = ttk.Treeview(grouped, columns=keys, show="headings")
        for key, label in zip(keys, ("负载 / B", "IP 总长 / B", "发送", "接收", "未成功率 / %", "最小 / ms", "平均 / ms", "最大 / ms")):
            self.group_table.heading(key, text=label)
            self.group_table.column(key, width=115, anchor="center")
        self.group_table.pack(fill="both", expand=True)
        self.groups = {}
        self.help_text = tk.StringVar()
        ttk.Label(outer, textvariable=self.help_text, wraplength=1120).pack(anchor="w", pady=(12, 0))
        self.protocol_changed()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(80, self.poll)

    def protocol_changed(self, event=None):
        ipv6 = self.protocol_version.get() == 'IPv6'
        defaults = ('127.0.0.1', '::1')
        if self.values['host'].get() in defaults:
            self.values['host'].set(defaults[int(ipv6)])
        if self.values['lower'].get() in ('576', '1280'):
            self.values['lower'].set('1280' if ipv6 else '576')
        if self.values['upper'].get() in ('65528', '65548'):
            self.values['upper'].set('65548' if ipv6 else '65528')
        self.df_check.configure(state='disabled' if ipv6 else 'normal')
        if ipv6:
            self.df.set(False)
        self.help_text.set(
            'IPv6 基础总长 = 负载 + 48 B（不含扩展头）。普通 Ping 由系统管理分片，成功不代表路径 MTU 达到该大小。\nIPv6 MTU 探测禁止源端分片，需要右键 EXE → 以管理员身份运行；超时不能直接判定 MTU 上限。'
            if ipv6 else
            'IPv4 总包长 = 负载 + 28 B。大包可通过分片与重组完成，不代表路径 MTU 达到该大小。\n超时可能由过滤或拥塞造成；成功响应校验返回负载长度及内容。')

    def diagnostic_preset(self):
        if self.running:
            return
        self.values['sizes'].set('1400,1452,1500,1600,1650,1700,1750,1800,2000')
        self.df.set(False)
        self.status.set('已载入 1600–1800 B 诊断预设；点击“开始数据包测试”')

    def preset(self, large):
        if self.running:
            return
        ipv6 = self.protocol_version.get() == 'IPv6'
        self.values["sizes"].set("20000,24000,32768,48000,60000,65500" if large else ('32,512,1232,1452' if ipv6 else "32,512,1400,1472"))
        self.df.set(not large and not ipv6)
        self.status.set("已载入大包预设；点击“开始数据包测试”" if large else "已载入常规包预设")

    def parameters(self, mode):
        p = {k: v.get().strip() for k, v in self.values.items()}
        p['ip_version'] = 6 if self.protocol_version.get() == 'IPv6' else 4
        overhead = 48 if p['ip_version'] == 6 else 28
        if not p["host"]:
            raise ValueError("请输入目标地址")
        for key in ("lower", "upper", "count", "interval", "timeout", "attempts"):
            p[key] = int(p[key])
        minimum = 1280 if p['ip_version'] == 6 else 28
        if not minimum <= p["lower"] <= p["upper"] <= 65500 + overhead:
            raise ValueError(f"IPv{p['ip_version']} MTU 范围应为 {minimum}–{65500 + overhead} 字节，下限不得大于上限")
        if not 1 <= p["count"] <= 10000 or not 1 <= p["attempts"] <= 10:
            raise ValueError("次数应为 1–10000，MTU 重试应为 1–10")
        if not 100 <= p["timeout"] <= 60000 or not 0 <= p["interval"] <= 60000:
            raise ValueError("超时应为 100–60000 ms，间隔应为 0–60000 ms")
        p["sizes"] = list(dict.fromkeys(int(s.strip()) for s in p["sizes"].replace("，", ",").split(",")))
        if len(p["sizes"]) > 32 or any(not 0 <= s <= 65500 for s in p["sizes"]):
            raise ValueError("最多输入 32 种包长，每种为 0–65500 字节")
        p["df"] = self.df.get() if p['ip_version'] == 4 else False
        return p

    def start(self, mode):
        if self.running:
            return
        try:
            p = self.parameters(mode)
        except ValueError as exc:
            messagebox.showerror("参数有误", str(exc))
            return
        self.cancel.clear()
        self.running = True
        self.probes = []
        self.report = {"version": VERSION, "mode": mode, "started": datetime.now().astimezone().isoformat(), "parameters": p}
        self.table.delete(*self.table.get_children())
        self.group_table.delete(*self.group_table.get_children())
        self.groups = {}
        self.summary.set("发送 0  /  接收 0  /  丢包 —  /  平均延迟 —")
        self.status.set("测试中… 正在解析目标地址")
        self.mtu_button.configure(state="disabled")
        self.packet_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.protocol_box.configure(state='disabled')
        threading.Thread(target=self.work, args=(mode, p), daemon=True).start()

    def work(self, mode, p):
        client = None
        try:
            if p['ip_version'] == 6:
                client = (WindowsIPv6MTU if mode == 'mtu' else WindowsIPv6Ping)(p['host'])
            else:
                client = WindowsPing(p["host"])
            self.events.put(("address", client.address))
            emit = lambda result: self.events.put(("probe", result))
            if mode == "mtu":
                result = discover_mtu(client.ping, p["lower"], p["upper"], p["attempts"], p["timeout"], self.cancel, emit, p['ip_version'])
            else:
                for size in p["sizes"]:
                    for _ in range(p["count"]):
                        if self.cancel.is_set():
                            break
                        emit(client.ping(size, p["timeout"], p["df"]))
                        if self.cancel.wait(p["interval"] / 1000):
                            break
                    if self.cancel.is_set():
                        break
                result = {"state": "cancelled" if self.cancel.is_set() else "complete", "message": "测试已停止" if self.cancel.is_set() else "数据包测试完成"}
            self.events.put(("done", result))
        except Exception as exc:
            self.events.put(("done", {"state": "error", "message": str(exc)}))
        finally:
            if client:
                client.close()

    def poll(self):
        for _ in range(300):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "address":
                self.report["resolved_address"] = value
                p = self.report['parameters']
                mode = ('禁止源端分片' if self.report['mode'] == 'mtu' else '系统管理源端分片') if p['ip_version'] == 6 else ("禁止分片 DF" if self.report['mode'] == 'mtu' or p['df'] else "允许分片")
                self.status.set(f"正在测试 IPv{p['ip_version']} {value} · {mode}…")
            elif kind == "probe":
                self.probes.append(value)
                labels = {"ok": "成功 / 校验通过", "timeout": "超时", "too_big": "报文过大 / PTB", "error": "错误", "corrupt": "负载校验失败"}
                row = self.table.insert("", "end", values=(len(self.probes), value.payload, value.packet_size, labels[value.status], value.rtt_ms if value.rtt_ms is not None else "—", value.detail))
                self.table.see(row)
                group = self.groups.setdefault(value.payload, [])
                group.append(value)
                stats = summarize(group)
                cells = (value.payload, value.packet_size, stats['sent'], stats['received'], stats['loss_percent'],
                         *(stats[k] if stats[k] is not None else '—' for k in ('min_ms', 'avg_ms', 'max_ms')))
                iid = str(value.payload)
                if self.group_table.exists(iid):
                    self.group_table.item(iid, values=cells)
                else:
                    self.group_table.insert('', 'end', iid=iid, values=cells)
                s = summarize(self.probes)
                self.summary.set(f"发送 {s['sent']}  /  接收 {s['received']}  /  未成功 {s['loss_percent']}%  /  平均延迟 {s['avg_ms'] if s['avg_ms'] is not None else '—'} ms")
            elif kind == "done":
                self.running = False
                self.report["result"] = value
                if self.report['mode'] == 'packets':
                    successful = [p.payload for p in self.probes if p.status == 'ok']
                    largest = max(successful) if successful else None
                    value['largest_successful_payload'] = largest
                    if largest is not None:
                        overhead = 48 if self.report['parameters']['ip_version'] == 6 else 28
                        value['message'] += f" · 本次已验证最大负载 {largest} B（基础 IP 总长 {largest + overhead} B）；仅代表已测试包长"
                self.status.set(value["message"])
                self.mtu_button.configure(state="normal")
                self.packet_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.protocol_box.configure(state='readonly')
        self.after(80, self.poll)

    def stop(self):
        self.cancel.set()
        self.status.set("正在停止… 当前探测将在超时后退出")

    def export(self):
        if not self.report:
            messagebox.showinfo("导出报告", "请先执行一次测试")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON 报告", "*.json"), ("CSV 明细", "*.csv")], initialfile="mtu_report.json")
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=["ip_version", "payload", "packet_size", "status", "rtt_ms", "detail"])
                    writer.writeheader()
                    writer.writerows(dict(asdict(p), packet_size=p.packet_size) for p in self.probes)
            else:
                data = dict(self.report, running=self.running, summary=summarize(self.probes),
                    by_payload={str(size): summarize([p for p in self.probes if p.payload == size]) for size in sorted({p.payload for p in self.probes})},
                    probes=[dict(asdict(p), packet_size=p.packet_size) for p in self.probes])
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("导出成功", path)
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))

    def close(self):
        self.cancel.set()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
