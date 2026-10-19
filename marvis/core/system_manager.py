"""
Marvis 系统管理 — 跨平台系统信息、进程、服务、磁盘、网络、清理、修复。

Windows: 使用 PowerShell 查询系统信息。
Linux/macOS: 使用原生命令查询。
可导入使用：
    from marvis.core.system_manager import sys_info, net_info, disk_usage, system_clean
"""

import json
import re
import subprocess
from typing import Optional

from marvis.utils.shell import run_powershell, IS_WINDOWS, run

_SORT_FIELDS = {"cpu", "memory", "name", "pid"}
_HOST_RE = re.compile(r"^[A-Za-z0-9.][A-Za-z0-9.\-]{0,252}$")
_SERVICE_NAME_RE = re.compile(r"[\w.\- ]{1,64}")
_SECRET_ASSIGN = re.compile(
    r"(?i)([A-Za-z0-9_.-]*(?:token|password|passwd|secret|api[_-]?key)[A-Za-z0-9_.-]*)"
    r"(=|\s+)(\S+)"
)
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}")


def _redact(text: str) -> str:
    """进程命令行等文本默认打码，避免把 token 打到终端。"""
    text = _JWT_RE.sub("[redacted]", text)
    return _SECRET_ASSIGN.sub(lambda match: match.group(1) + match.group(2) + "[redacted]", text)


def _ps(script: str, timeout: int = 30) -> dict:
    """运行 PowerShell 脚本并返回解析后的 JSON"""
    if not IS_WINDOWS:
        return {"error": "此功能仅支持 Windows"}
    stdout, stderr, rc = run_powershell(script, timeout)
    if rc != 0 and not stdout:
        return {"error": stderr or "PowerShell 执行失败"}
    try:
        return json.loads(stdout)

    except json.JSONDecodeError:
        return {"raw": stdout, "error": stderr} if stdout else {"error": stderr or "无输出"}


def sys_info() -> dict:
    """获取系统基本信息：OS/CPU/RAM/GPU/磁盘"""
    if not IS_WINDOWS:
        return _linux_sys_info()
    return _ps(r"""
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor
$ram = Get-CimInstance Win32_PhysicalMemory | Measure-Object Capacity -Sum
$gpu = Get-CimInstance Win32_VideoController
$disk = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'
@{
    OS         = $os.Caption + ' ' + $os.Version
    Arch       = $os.OSArchitecture
    CPU        = $cpu.Name
    CPUCores   = $cpu.NumberOfCores
    CPULogical = $cpu.NumberOfLogicalProcessors
    RAM_GB     = [math]::Round($ram.Sum / 1GB, 1)
    GPU        = ($gpu | ForEach-Object { $_.Name }) -join ', '
    Disks      = ($disk | ForEach-Object { "$($_.DeviceID) $([math]::Round($_.Size/1GB,0))GB (free: $([math]::Round($_.FreeSpace/1GB,0))GB)" }) -join '; '
    Hostname   = $env:COMPUTERNAME
} | ConvertTo-Json
""")


def _linux_sys_info() -> dict:
    """Linux/macOS 系统信息"""
    import platform
    info = {"OS": f"{platform.system()} {platform.release()}", "Arch": platform.machine(),
            "Hostname": platform.node()}
    try:
        stdout, _, _ = run("cat /proc/cpuinfo | grep 'model name' | head -1 | cut -d: -f2")
        if stdout:
            info["CPU"] = stdout.strip()
        stdout, _, _ = run("nproc")
        if stdout:
            info["CPUCores"] = int(stdout.strip())
        stdout, _, _ = run("free -h | grep Mem | awk '{print $2}'")
        if stdout:
            info["RAM"] = stdout.strip()
        stdout, _, _ = run("df -h / | tail -1 | awk '{print $2\" total, \"$4\" free\"}'")
        if stdout:
            info["Disk_Root"] = stdout.strip()
    except Exception:
        pass
    return info


def net_info() -> dict:
    """获取网络接口信息"""
    if not IS_WINDOWS:
        return _linux_net_info()
    return _ps(r"""
$adapters = Get-NetIPConfiguration | Where-Object { $_.IPv4Address }
$results = @()
foreach ($a in $adapters) {
    $results += @{
        Interface = $a.InterfaceAlias
        IP        = $a.IPv4Address.IPAddress
        Gateway   = if ($a.IPv4DefaultGateway) { $a.IPv4DefaultGateway.NextHop } else { 'N/A' }
        DNS       = ($a.DNSServer | ForEach-Object { $_.ServerAddresses }) -join ', '
    }
}
$results | ConvertTo-Json
""")


def _linux_net_info() -> list:
    stdout, _, _ = run("ip -4 addr show | grep inet | awk '{print $2, $NF}'")
    rows = []
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            rows.append({"ip": parts[0], "interface": parts[1]})
    return rows


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return 20
    return max(1, min(value, 200))


def process_list(sort_by: str = "cpu", limit: int = 20) -> list:
    """获取进程列表。排序字段来自白名单，避免拼进 shell。"""
    sort_by = (sort_by or "cpu").lower()
    if sort_by not in _SORT_FIELDS:
        return [{"error": f"不支持的排序字段: {sort_by}"}]
    limit = _bounded_limit(limit)
    if not IS_WINDOWS:
        return _posix_processes(sort_by, limit)
    prop = {"cpu": "CPU", "memory": "WorkingSet64", "name": "Name", "pid": "Id"}[sort_by]
    data = _ps(f"""
Get-Process | Sort-Object -Property {prop} -Descending | Select-Object -First {limit} |
    ForEach-Object {{
        @{{ Name=$_.Name; PID=$_.Id; CPU=[math]::Round($_.CPU,1); Memory_MB=[math]::Round($_.WorkingSet64/1MB,1) }}
    }} | ConvertTo-Json
""")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and data.get("error") and "Name" not in data:
        return [data]
    return [data]


def _posix_processes(sort_by: str, limit: int) -> list:
    import platform

    # comm 只有程序名，不带参数，避免把 --token 打出来
    sort_key = {"cpu": "-pcpu", "memory": "-pmem", "name": "comm", "pid": "pid"}[sort_by]
    if platform.system() == "Darwin":
        cmd = ["ps", "-axo", "user,pid,pcpu,pmem,comm"]
    else:
        cmd = ["ps", "-eo", "user,pid,pcpu,pmem,comm", f"--sort={sort_key}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [{"error": str(exc)}]
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return [{"error": _redact((proc.stderr or "无法获取进程").strip())[:200]}]
    return [{"raw": _redact(line)} for line in lines[: limit + 1]]


def service_list(filter_name: Optional[str] = None, status: Optional[str] = None) -> list:
    """获取服务列表。过滤值限制为安全字符，不拼进任意 shell。"""
    if filter_name is not None and not _SERVICE_NAME_RE.fullmatch(filter_name):
        return [{"error": "服务名过滤包含不允许的字符"}]
    if not IS_WINDOWS:
        allowed_state = {"running", "failed", "inactive", "active", "dead"}
        cmd = ["systemctl", "list-units", "--type=service", "--no-pager"]
        if status:
            if status.lower() not in allowed_state:
                return [{"error": "不支持的服务状态过滤"}]
            cmd.extend(["--state", status.lower()])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [{"error": str(exc)}]
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        if filter_name:
            needle = filter_name.lower()
            lines = [line for line in lines if needle in line.lower()]
        return [{"raw": line} for line in lines[:100]] or [{"message": "无匹配服务"}]

    cmd = "Get-Service"
    if filter_name:
        cmd += (
            " | Where-Object { $_.Name -like '*"
            + filter_name
            + "*' -or $_.DisplayName -like '*"
            + filter_name
            + "*' }"
        )
    if status:
        allowed = {"Running", "Stopped", "StartPending", "StopPending"}
        canonical = status[:1].upper() + status[1:]
        if canonical not in allowed and status not in allowed:
            return [{"error": "不支持的服务状态过滤"}]
        chosen = status if status in allowed else canonical
        cmd += f" | Where-Object {{ $_.Status -eq '{chosen}' }}"
    cmd += " | Select-Object Name, DisplayName, Status | ConvertTo-Json"
    data = _ps(cmd)
    if isinstance(data, list):
        return data
    return [data]


def disk_usage() -> list:
    """获取磁盘使用情况"""
    if not IS_WINDOWS:
        stdout, _, _ = run("df -h | grep -E '^/dev/'")
        return [{"raw": l} for l in stdout.split("\n") if l.strip()]

    return _ps(r"""
Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
    $total = [math]::Round($_.Size/1GB, 1)
    $free  = [math]::Round($_.FreeSpace/1GB, 1)
    $used  = $total - $free
    @{
        Drive     = $_.DeviceID
        Label     = $_.VolumeName
        Total_GB  = $total
        Used_GB   = [math]::Round($used, 1)
        Free_GB   = $free
        Usage_Pct = if ($total -gt 0) { [math]::Round($used/$total*100, 1) } else { 0 }
    }
} | ConvertTo-Json
""")


def port_check(port: int, host: str = "127.0.0.1") -> dict:
    """检查端口是否开放。主机名先校验，再连接。"""
    try:
        port_num = int(port)
    except (TypeError, ValueError):
        return {"error": "端口必须是整数"}
    if not 1 <= port_num <= 65535:
        return {"error": "端口超出范围"}
    host = (host or "127.0.0.1").strip()
    if not _HOST_RE.fullmatch(host):
        return {"error": "主机名无效"}
    if IS_WINDOWS:
        return _ps(f"""
$tcp = Test-NetConnection -ComputerName '{host}' -Port {port_num} -WarningAction SilentlyContinue
@{{ Host='{host}'; Port={port_num}; IsOpen=$tcp.TcpTestSucceeded }} | ConvertTo-Json
""")
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect((host, port_num))
        return {"Host": host, "Port": port_num, "IsOpen": True}
    except Exception:
        return {"Host": host, "Port": port_num, "IsOpen": False}
    finally:
        sock.close()


def firewall_rules(direction: Optional[str] = None) -> list:
    """获取防火墙状态。只读，不修改规则。"""
    if direction and direction.lower() not in {"inbound", "outbound"}:
        return [{"error": "方向仅支持 inbound / outbound"}]
    if not IS_WINDOWS:
        from marvis.core.security_audit import check_firewall
        return [check_firewall()]
    cmd = "Get-NetFirewallRule | Where-Object { $_.Enabled -eq 'True' }"
    if direction:
        chosen = "Inbound" if direction.lower() == "inbound" else "Outbound"
        cmd += f" | Where-Object {{ $_.Direction -eq '{chosen}' }}"
    cmd += " | Select-Object DisplayName, Direction, Action, Profile | ConvertTo-Json"
    data = _ps(cmd)
    if isinstance(data, list):
        return data
    return [data]


def system_clean() -> list:
    """扫描可清理的系统临时文件"""
    if not IS_WINDOWS:
        stdout, _, _ = run("du -sh /tmp /var/tmp ~/.cache 2>/dev/null")
        return [{"raw": stdout}] if stdout else [{"message": "Linux 清理扫描"}]

    return _ps(r"""
$results = @()
$tempPaths = @($env:TEMP, "$env:LOCALAPPDATA\Temp", "C:\Windows\Temp")
foreach ($p in $tempPaths) {
    if (Test-Path $p) {
        $files = Get-ChildItem $p -Recurse -ErrorAction SilentlyContinue | Where-Object { -not $_.PSIsContainer }
        $size = ($files | Measure-Object Length -Sum).Sum
        $results += @{Category="临时文件"; Path=$p; FileCount=$files.Count; Size_MB=[math]::Round($size/1MB,1)}
    }
}
$thumbPath = "$env:LOCALAPPDATA\Microsoft\Windows\Explorer"
if (Test-Path $thumbPath) {
    $thumbs = Get-ChildItem $thumbPath -Filter "thumbcache_*" -ErrorAction SilentlyContinue
    $size = ($thumbs | Measure-Object Length -Sum).Sum
    $results += @{Category="缩略图缓存"; Path=$thumbPath; FileCount=$thumbs.Count; Size_MB=[math]::Round($size/1MB,1)}
}
$wuPath = "C:\Windows\SoftwareDistribution\Download"
if (Test-Path $wuPath) {
    $files = Get-ChildItem $wuPath -Recurse -ErrorAction SilentlyContinue | Where-Object { -not $_.PSIsContainer }
    $size = ($files | Measure-Object Length -Sum).Sum
    $results += @{Category="Windows更新缓存"; Path=$wuPath; FileCount=$files.Count; Size_MB=[math]::Round($size/1MB,1)}
}
$results | ConvertTo-Json
""")


_REPAIR_STEPS = (
    ("ipconfig /flushdns", "刷新DNS缓存"),
    ("ipconfig /release", "释放IP地址"),
    ("ipconfig /renew", "重新获取IP"),
    ("netsh winsock reset", "重置Winsock"),
    ("netsh int ip reset", "重置IP配置"),
    ("ipconfig /registerdns", "重新注册DNS"),
)


def net_repair(execute: bool = False) -> list:
    """网络修复。默认只预览；execute=True 才会改本机网络（仅 Windows）。"""
    if not IS_WINDOWS:
        return [{
            "step": "网络修复",
            "status": "skipped",
            "note": "非 Windows 不自动改网络。请手动检查 NetworkManager 或 systemd-resolved。",
        }]

    preview = [
        {
            "step": name,
            "command": cmd,
            "status": "preview",
            "note": "未执行。确认后使用 marvis system repair --execute",
        }
        for cmd, name in _REPAIR_STEPS
    ]
    if not execute:
        return preview

    steps = []
    for cmd, name in _REPAIR_STEPS:
        stdout, stderr, rc = run(cmd, shell=True, timeout=30)
        steps.append({
            "step": name,
            "command": cmd,
            "success": rc == 0,
            "output": (stdout or stderr)[:300],
        })
    return steps


def env_vars(scope: str = "user") -> dict:
    """获取环境变量"""
    import os
    if scope == "system":
        return dict(os.environ)
    return {k: v for k, v in os.environ.items() if not k.startswith("_")}


def startup_list() -> list:
    """获取开机启动项"""
    if not IS_WINDOWS:
        stdout, _, _ = run("systemctl list-unit-files --type=service --state=enabled --no-pager")
        return [{"raw": l} for l in stdout.split("\n") if l.strip()]
    return _ps("Get-CimInstance Win32_StartupCommand | Select-Object Name, Command, Location | ConvertTo-Json")


def power_plan() -> dict:
    """获取电源计划"""
    if not IS_WINDOWS:
        return {"message": "电源计划查询仅支持 Windows"}
    stdout, _, _ = run("powercfg /getactivescheme", timeout=10)
    return {"active_scheme": stdout}
