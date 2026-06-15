"""
Marvis 系统管理 — 跨平台系统信息、进程、服务、磁盘、网络、清理、修复。

Windows: 使用 PowerShell 查询系统信息。
Linux/macOS: 使用原生命令查询。
可导入使用：
    from marvis.core.system_manager import sys_info, net_info, disk_usage, system_clean
"""

import json
from typing import Optional

from marvis.utils.shell import run_powershell, IS_WINDOWS, run


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
    return [{"interface": l.split()[1], "ip": l.split()[0]} for l in stdout.split("\n") if l.strip()]


def process_list(sort_by: str = "cpu", limit: int = 20) -> list:
    """获取进程列表"""
    if not IS_WINDOWS:
        stdout, _, _ = run(f"ps aux --sort=-%{'cpu' if sort_by == 'cpu' else 'mem'} | head -{limit}")
        return [{"raw": l} for l in stdout.split("\n") if l.strip()]
    return _ps(f"""
Get-Process | Sort-Object -Property {sort_by} -Descending | Select-Object -First {limit} |
    ForEach-Object {{
        @{{ Name=$_.Name; PID=$_.Id; CPU=[math]::Round($_.CPU,1); Memory_MB=[math]::Round($_.WorkingSet64/1MB,1) }}
    }} | ConvertTo-Json
""")


def service_list(filter_name: Optional[str] = None, status: Optional[str] = None) -> list:
    """获取服务列表"""
    if not IS_WINDOWS:
        cmd = "systemctl list-units --type=service --no-pager"
        if status:
            cmd += f" --state={status.lower()}"
        stdout, _, _ = run(cmd)
        return [{"raw": l} for l in stdout.split("\n") if l.strip()]

    cmd = "Get-Service"
    if filter_name:
        cmd += f" | Where-Object {{ $_.Name -like '*{filter_name}*' -or $_.DisplayName -like '*{filter_name}*' }}"
    if status:
        cmd += f" | Where-Object {{ $_.Status -eq '{status}' }}"
    cmd += " | Select-Object Name, DisplayName, Status | ConvertTo-Json"
    return _ps(cmd)


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
    """检查端口是否开放"""
    if IS_WINDOWS:
        return _ps(f"""
$tcp = Test-NetConnection -ComputerName {host} -Port {port} -WarningAction SilentlyContinue
@{{ Host='{host}'; Port={port}; IsOpen=$tcp.TcpTestSucceeded }} | ConvertTo-Json
""")
    else:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        try:
            s.connect((host, port))
            return {"Host": host, "Port": port, "IsOpen": True}
        except Exception:
            return {"Host": host, "Port": port, "IsOpen": False}
        finally:
            s.close()


def firewall_rules(direction: Optional[str] = None) -> list:
    """获取防火墙规则"""
    if not IS_WINDOWS:
        return [{"error": "防火墙查询仅支持 Windows"}]
    cmd = "Get-NetFirewallRule | Where-Object { $_.Enabled -eq 'True' }"
    if direction:
        cmd += f" | Where-Object {{ $_.Direction -eq '{direction}' }}"
    cmd += " | Select-Object DisplayName, Direction, Action, Profile | ConvertTo-Json"
    return _ps(cmd)


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


def net_repair() -> list:
    """网络修复：刷新 DNS / 重置 Winsock / 重置 IP"""
    if not IS_WINDOWS:
        return [{"step": "Linux网络修复", "note": "请手动运行 sudo systemctl restart NetworkManager"}]

    steps = []
    for cmd, name in [
        ("ipconfig /flushdns", "刷新DNS缓存"),
        ("ipconfig /release", "释放IP地址"),
        ("ipconfig /renew", "重新获取IP"),
        ("netsh winsock reset", "重置Winsock"),
        ("netsh int ip reset", "重置IP配置"),
        ("ipconfig /registerdns", "重新注册DNS"),
    ]:
        stdout, stderr, rc = run(cmd, shell=True, timeout=30)
        steps.append({"step": name, "success": rc == 0, "output": stdout or stderr})
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
