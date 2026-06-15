#!/usr/bin/env python3
"""Marvis Windows 系统管理 - 查看/修改系统设置/清理/网络修复"""

import argparse
import json
import os
import subprocess
import sys
import tempfile


def run_ps(script):
    """运行 PowerShell 脚本文件并返回输出"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as f:
        f.write(script)
        f.flush()
        tmp = f.name
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=30
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def sys_info():
    out, err, rc = run_ps("""
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor
$ram = Get-CimInstance Win32_PhysicalMemory | Measure-Object Capacity -Sum
$gpu = Get-CimInstance Win32_VideoController
$disk = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'
@{
    OS        = $os.Caption + ' ' + $os.Version
    Arch      = $os.OSArchitecture
    CPU       = $cpu.Name
    CPUCores  = $cpu.NumberOfCores
    CPULogical= $cpu.NumberOfLogicalProcessors
    RAM_GB    = [math]::Round($ram.Sum / 1GB, 1)
    GPU       = ($gpu | ForEach-Object { $_.Name }) -join ', '
    Disks     = ($disk | ForEach-Object { "$($_.DeviceID) $([math]::Round($_.Size/1GB,0))GB (free: $([math]::Round($_.FreeSpace/1GB,0))GB)" }) -join '; '
    Hostname  = $env:COMPUTERNAME
} | ConvertTo-Json
""")
    return out


def net_info():
    out, err, rc = run_ps("""
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
    return out


def process_list(sort_by="cpu", limit=20):
    out, err, rc = run_ps(f"""
Get-Process | Sort-Object -Property {sort_by} -Descending | Select-Object -First {limit} |
    ForEach-Object {{
        @{{
            Name=$_.Name; PID=$_.Id; CPU=[math]::Round($_.CPU,1); Memory_MB=[math]::Round($_.WorkingSet64/1MB,1)
        }}
    }} | ConvertTo-Json
""")
    return out


def service_list(filter_name=None, status=None):
    cmd = "Get-Service"
    if filter_name:
        cmd += f" | Where-Object {{ $_.Name -like '*{filter_name}*' -or $_.DisplayName -like '*{filter_name}*' }}"
    if status:
        cmd += f" | Where-Object {{ $_.Status -eq '{status}' }}"
    cmd += " | Select-Object Name, DisplayName, Status | ConvertTo-Json"
    out, err, rc = run_ps(cmd)
    return out


def startup_list():
    out, err, rc = run_ps("""
Get-CimInstance Win32_StartupCommand | Select-Object Name, Command, Location |
    ConvertTo-Json
""")
    return out


def env_vars(scope="user"):
    target = "User" if scope == "user" else "Machine"
    out, err, rc = run_ps(f"""
[Environment]::GetEnvironmentVariables('{target}') | ConvertTo-Json
""")
    return out


def disk_usage():
    out, err, rc = run_ps("""
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
    return out


def power_plan():
    out, err, rc = run_ps("powercfg /getactivescheme")
    return out


def firewall_rules(direction=None):
    cmd = "Get-NetFirewallRule | Where-Object { $_.Enabled -eq 'True' }"
    if direction:
        cmd += f" | Where-Object {{ $_.Direction -eq '{direction}' }}"
    cmd += " | Select-Object DisplayName, Direction, Action, Profile | ConvertTo-Json"
    out, err, rc = run_ps(cmd)
    return out


def port_check(port, host="127.0.0.1"):
    out, err, rc = run_ps(f"""
$tcp = Test-NetConnection -ComputerName {host} -Port {port} -WarningAction SilentlyContinue
@{{
    Host   = '{host}'
    Port   = {port}
    IsOpen = $tcp.TcpTestSucceeded
}} | ConvertTo-Json
""")
    return out


def system_clean():
    """系统清理 - 扫描可清理的临时文件"""
    out, err, rc = run_ps(r"""
$results = @()
$tempPaths = @(
    $env:TEMP,
    "$env:LOCALAPPDATA\Temp",
    "C:\Windows\Temp"
)
foreach ($p in $tempPaths) {
    if (Test-Path $p) {
        $files = Get-ChildItem $p -Recurse -ErrorAction SilentlyContinue |
            Where-Object { -not $_.PSIsContainer }
        $size = ($files | Measure-Object Length -Sum).Sum
        $results += @{
            Category = "临时文件"
            Path = $p
            FileCount = $files.Count
            Size_MB = [math]::Round($size / 1MB, 1)
        }
    }
}
$thumbPath = "$env:LOCALAPPDATA\Microsoft\Windows\Explorer"
if (Test-Path $thumbPath) {
    $thumbs = Get-ChildItem $thumbPath -Filter "thumbcache_*" -ErrorAction SilentlyContinue
    $size = ($thumbs | Measure-Object Length -Sum).Sum
    $results += @{
        Category = "缩略图缓存"
        Path = $thumbPath
        FileCount = $thumbs.Count
        Size_MB = [math]::Round($size / 1MB, 1)
    }
}
$wuPath = "C:\Windows\SoftwareDistribution\Download"
if (Test-Path $wuPath) {
    $files = Get-ChildItem $wuPath -Recurse -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer }
    $size = ($files | Measure-Object Length -Sum).Sum
    $results += @{
        Category = "Windows更新缓存"
        Path = $wuPath
        FileCount = $files.Count
        Size_MB = [math]::Round($size / 1MB, 1)
    }
}
$shell = New-Object -ComObject Shell.Application
$recycleBin = $shell.NameSpace(0x0a)
$rbCount = $recycleBin.Items().Count
$results += @{
    Category = "回收站"
    Path = "回收站"
    FileCount = $rbCount
    Size_MB = 0
}
$results | ConvertTo-Json
""")
    return out


def net_repair():
    """网络修复 - 刷新 DNS、重置网络适配器等"""
    steps = []
    out1, err1, rc1 = run_ps("ipconfig /flushdns")
    steps.append({"step": "刷新DNS缓存", "success": rc1 == 0, "output": out1})
    out2, err2, rc2 = run_ps("ipconfig /release")
    steps.append({"step": "释放IP地址", "success": rc2 == 0, "output": out2})
    out3, err3, rc3 = run_ps("ipconfig /renew")
    steps.append({"step": "重新获取IP", "success": rc3 == 0, "output": out3})
    out4, err4, rc4 = run_ps("netsh winsock reset")
    steps.append({"step": "重置Winsock", "success": rc4 == 0, "output": out4})
    out5, err5, rc5 = run_ps("netsh int ip reset")
    steps.append({"step": "重置IP配置", "success": rc5 == 0, "output": out5})
    out6, err6, rc6 = run_ps("ipconfig /registerdns")
    steps.append({"step": "重新注册DNS", "success": rc6 == 0, "output": out6})
    return json.dumps(steps, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Marvis Windows 系统管理")
    parser.add_argument("--action", choices=[
        "sys-info", "net-info", "processes", "services", "startup",
        "env-vars", "disk", "power", "firewall", "port-check",
        "system-clean", "net-repair"
    ], required=True, help="操作类型")
    parser.add_argument("--sort", default="cpu", help="进程排序字段")
    parser.add_argument("--limit", type=int, default=20, help="结果数量限制")
    parser.add_argument("--filter", help="服务名称过滤")
    parser.add_argument("--status", help="服务状态过滤 (Running/Stopped)")
    parser.add_argument("--scope", choices=["user", "system"], default="user", help="环境变量范围")
    parser.add_argument("--port", type=int, help="检查端口号")
    parser.add_argument("--host", default="127.0.0.1", help="检查端口主机")
    parser.add_argument("--direction", choices=["Inbound", "Outbound"], help="防火墙规则方向")

    args = parser.parse_args()

    try:
        if args.action == "sys-info":
            print(sys_info())
        elif args.action == "net-info":
            print(net_info())
        elif args.action == "processes":
            print(process_list(args.sort, args.limit))
        elif args.action == "services":
            print(service_list(args.filter, args.status))
        elif args.action == "startup":
            print(startup_list())
        elif args.action == "env-vars":
            print(env_vars(args.scope))
        elif args.action == "disk":
            print(disk_usage())
        elif args.action == "power":
            print(power_plan())
        elif args.action == "firewall":
            print(firewall_rules(args.direction))
        elif args.action == "port-check":
            if not args.port:
                print("错误: port-check 需要 --port 参数", file=sys.stderr)
                sys.exit(1)
            print(port_check(args.port, args.host))
        elif args.action == "system-clean":
            print(system_clean())
        elif args.action == "net-repair":
            print(net_repair())
    except subprocess.TimeoutExpired:
        print("错误: 命令执行超时", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()