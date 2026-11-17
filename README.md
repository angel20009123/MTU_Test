# 链路实验室

Windows IPv4 / IPv6 路径 MTU、包长、丢包与延迟测试桌面工具。使用 Python 标准库和 Windows ICMP API，无需安装运行依赖。普通 Ping 与 IPv4 MTU 探测无需管理员权限；IPv6 MTU 探测需要管理员权限。

## 启动

当前版本 **1.3.0**：直接运行 `dist/MTU_Link_Tester_v1.3.0.exe`，无需安装 Python。该文件为 Windows x64 单文件桌面程序，包含大包测试预设和新图标。

安装带 Tk 的 Python 3.10 或更高版本，双击 `start.bat`，或执行 `python app.py`。

1. 选择 IPv4 或 IPv6，输入对应的地址或域名（域名解析为所选协议的一个地址）。默认回环地址用于本机自检，不代表外部链路。
2. 点击“探测路径 MTU”：在给定范围内二分探测，始终设置禁止分片 DF。只有明确的“需要分片”响应才缩小上界；超时或其他错误会报告无法确定及已确认的下界。达到设定上限仅说明 MTU 至少为该值。
3. 点击“开始数据包测试”：按顺序测试每种 ICMP 负载，记录结果和 RTT。可关闭 DF 以允许 IPv4 分片。间隔是每次响应或超时之后的等待时间。
4. 可随时停止；当前系统调用最多等待设置的超时时间。DNS 解析由系统处理，不能立即取消。
5. 导出 JSON 包含参数、解析地址、逐包明细、总体与每个包长的统计；CSV 导出逐包明细。运行中导出是当前快照。

### 20000 字节以上的大包

点击“大包预设：20K–65.5K”，再点击“开始数据包测试”。预设会依次测试 20000、24000、32768、48000、60000、65500 字节负载，自动允许 IPv4 分片。也可以在负载框输入其他数值（0–65500）。数值含义与 `ping -l 20000` 的负载大小一致。

“逐包明细”列出成功、需要分片、超时或错误；“按包长统计”显示每种包长的发送、接收、未成功率和最小/平均/最大延迟。每个成功响应都检查回包数据长度和内容，测试完成时显示本次成功的最大负载；该结果只针对已测试包长，并非自动确定的绝对上限。

允许分片时，20000 字节负载可以拆成多个 IP 分片后传输，再由对端重组。因此大包 Ping 成功不代表链路 MTU 为 20028 字节。要测试不分片的大小，请勾选 DF 或使用“探测路径 MTU”；MTU 默认搜索上限已扩展为 65528 字节。

## 指标解释

- 包长输入为 ICMP 数据负载；IP 总长 = 负载 + 20 字节 IPv4 头 + 8 字节 ICMP 头，不含二层封装。
- 未成功率包含超时、需要分片及其他错误，因此 MTU 探测的未成功率不能视为网络随机丢包率。
- RTT 使用 Windows 返回的毫秒值；0 ms 表示低于其计时精度。抖动为相邻成功响应 RTT 差值绝对值的均值。
- 探测假设链路 MTU 稳定且可通过性随包长单调变化。目标或途中设备过滤 ICMP、限速、路由变化均可能影响结果。
- 支持 IPv4 ICMP 与 IPv6 ICMPv6，不测 TCP/UDP 吞吐量。系统错误码保留在明细中。

## IPv6 测试

选择“IPv6”，输入目标地址，例如 `240b:8044:3000:2:2::701`，再执行数据包测试。支持 IPv6 域名、带方括号的地址、带接口编号的链路本地地址（如 `fe80::1%12`）。可在 PowerShell 使用 `Get-NetIPInterface -AddressFamily IPv6` 查看接口编号。不支持组播和未指定地址作为目标。

“1600–1800 B 诊断”预设覆盖 1400、1452、1500、1600、1650、1700、1750、1800、2000 字节负载；“大包预设”仍支持 20000–65500 字节。IPv6 基础 IP 总长为负载 + 48 字节，不含分片头等扩展头。

普通 IPv6 Ping 使用 `Icmp6SendEcho2`，由 Windows 管理源端分片，IPv4 DF 复选框在 IPv6 下禁用。成功时校验 API 返回的预期负载内容；该 API 不提供独立的实际回包长度字段，因此不宣称独立校验 IPv6 回包长度。详情明确显示此限制。

IPv6 路径 MTU 探测使用原始 ICMPv6 套接字和 `IPV6_DONTFRAG` 禁止源端分片，需右键 EXE →“以管理员身份运行”。权限不足会提示，不会将普通分片 Ping 当作 MTU 探测。MTU 搜索下限至少 1280 字节；收到匹配本次请求的 Packet Too Big 才缩小上界，超时则保留已验证下界并报告无法确定。普通 IPv6 Ping 无需提升权限。

IPv6 中间路由器不分片。大包可达性和禁止分片的路径 MTU 是不同指标；源端分片、ICMPv6 过滤、反向链路或重组问题均可能造成不同包长结果不一致。本工具不会自动修改网卡、路由或防火墙配置。

实现参考：[Windows ICMPv6 API](https://learn.microsoft.com/en-us/windows/win32/api/icmpapi/nf-icmpapi-icmp6sendecho2)、[Windows 原始套接字](https://learn.microsoft.com/en-us/windows/win32/winsock/tcp-ip-raw-sockets-2)。

## 验证

运行 `python -m unittest discover -s tests -v`。本机实测可使用 `127.0.0.1`，外部链路应填写实际目标。

## 重新打包

开发环境安装 PyInstaller（`python -m pip install pyinstaller`）后运行 `build.bat`。输出为 `dist/MTU_Link_Tester_v<版本号>.exe`，版本统一由 `version.py` 管理；窗口、JSON 报告和 Windows 文件属性同步显示该版本。

图标源文件为 `assets/link_lab.png`，多分辨率 Windows 图标为 `assets/link_lab.ico`。使用 `powershell -ExecutionPolicy Bypass -File make_icon.ps1` 可重新生成图标。

## 修改后发布并同步 GitHub

关联 GitHub origin 并配置 Git 身份及推送认证后，执行：

```powershell
python release.py --message "本次修改说明"
```

默认自动递增补丁号，例如 1.2.0 → 1.2.1，更新日志后运行单元测试、界面发包验证和打包，再提交源码、创建 `v1.2.1` 标签，原子推送分支与标签。功能版本可添加 `--bump minor`，重大版本可添加 `--bump major`。首次发布已有版本可使用 `--current`。

推送版本标签会触发 `.github/workflows/release.yml`，在 Windows 环境构建并将 EXE 上传到 GitHub Releases。源码保存在 Git 中，EXE 保存在 Releases，`dist/` 不进入源码提交。同步成功和 Release 发布成功是两个阶段，需在 Actions 中确认发布完成。

发布失败会保留本地修改和构建产物；若失败前已产生提交或标签，请先检查 Git 状态及远程状态，再重试推送，避免重复递增版本。
