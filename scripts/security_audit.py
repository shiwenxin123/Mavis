#!/usr/bin/env python3
"""Marvis 安全巡检 - 检查本地安全风险（敏感文件泄露、端口暴露、弱密码等）"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile


def run_ps(script):
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


def check_sensitive_files(root):
    """检查目录中的敏感文件（密钥、凭据、配置等）"""
    findings = []
    sensitive_patterns = [
        (r'-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----', "私钥文件", "高"),
        (r'(?:password|passwd|pwd)\s*[=:]\s*\S+', "明文密码", "高"),
        (r'(?:api[_-]?key|apikey|secret[_-]?key)\s*[=:]\s*["\']?\w{8,}', "API 密钥", "高"),
        (r'(?:access[_-]?token|auth[_-]?token)\s*[=:]\s*["\']?\w{8,}', "访问令牌", "高"),
        (r'(?:jdbc|mysql|postgres|mongodb)://\S+:\S+@\S+', "数据库连接串", "高"),
        (r'AKIA[0-9A-Z]{16}', "AWS Access Key", "高"),
        (r'AIza[0-9A-Za-z\-_]{35}', "Google API Key", "中"),
        (r'ghp_[0-9a-zA-Z]{36}', "GitHub Token", "高"),
        (r'gho_[0-9a-zA-Z]{36}', "GitHub OAuth Token", "高"),
        (r'sk-[0-9a-zA-Z]{20,}', "OpenAI API Key", "高"),
        (r'eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*', "JWT Token", "中"),
    ]

    sensitive_filenames = {
        '.env', '.env.local', '.env.production', '.env.development',
        'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519',
        '.npmrc', '.pypirc', '.netrc', '_netrc',
        'credentials.json', 'service-account.json', 'client_secret.json',
        '.htpasswd', 'wp-config.php',
    }

    ext_skip = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',
                '.woff', '.woff2', '.ttf', '.eot', '.mp3', '.mp4', '.avi',
                '.zip', '.rar', '.7z', '.gz', '.exe', '.dll', '.so', '.dylib'}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {'.git', 'node_modules', '__pycache__', 'venv', '.venv'}]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in ext_skip:
                continue

            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root)

            # 检查文件名
            if f in sensitive_filenames:
                findings.append({
                    "type": "敏感文件名",
                    "file": rel,
                    "detail": f"发现敏感文件: {f}",
                    "severity": "高"
                })
                continue

            # 检查文件内容（小文件）
            try:
                size = os.path.getsize(full)
                if size > 500_000 or size == 0:
                    continue
                with open(full, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read()
                    for pattern, desc, severity in sensitive_patterns:
                        matches = re.findall(pattern, content, re.IGNORECASE)
                        if matches:
                            findings.append({
                                "type": "敏感内容",
                                "file": rel,
                                "detail": desc,
                                "severity": severity,
                                "count": len(matches)
                            })
                            break  # 每个文件只报第一个匹配
            except (PermissionError, OSError):
                continue

    return findings


def check_open_ports():
    """检查本机监听端口"""
    out, err, rc = run_ps("""
Get-NetTCPConnection -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess |
    Sort-Object LocalPort | ConvertTo-Json
""")
    if not out:
        return []
    try:
        ports = json.loads(out)
        if isinstance(ports, dict):
            ports = [ports]
        result = []
        seen = set()
        for p in ports:
            port_key = (p.get('LocalAddress', ''), p.get('LocalPort', 0))
            if port_key not in seen:
                seen.add(port_key)
                pid = p.get('OwningProcess', 0)
                proc_name = ""
                if pid:
                    try:
                        proc = subprocess.run(
                            ["powershell", "-NoProfile", "-Command",
                             f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).ProcessName"],
                            capture_output=True, text=True, encoding="utf-8", timeout=5
                        )
                        proc_name = proc.stdout.strip()
                    except Exception:
                        pass
                risk = assess_port_risk(p.get('LocalPort', 0), p.get('LocalAddress', ''))
                result.append({
                    "address": p.get('LocalAddress', ''),
                    "port": p.get('LocalPort', 0),
                    "pid": pid,
                    "process": proc_name,
                    "risk": risk
                })
        return result
    except json.JSONDecodeError:
        return []


def assess_port_risk(port, address):
    """评估端口风险等级"""
    high_risk = {22: "SSH", 23: "Telnet", 445: "SMB", 3389: "RDP",
                 5900: "VNC", 6379: "Redis", 27017: "MongoDB", 9200: "Elasticsearch"}
    med_risk = {80: "HTTP", 443: "HTTPS", 3000: "Dev Server", 8080: "HTTP Proxy",
                8443: "HTTPS Alt", 8888: "Jupyter", 5000: "Flask Dev"}

    if port in high_risk:
        return {"level": "高", "reason": f"{high_risk[port]} 服务暴露在 {port} 端口"}
    if port in med_risk:
        return {"level": "中", "reason": f"{med_risk[port]} 服务在 {port} 端口"}
    if address == '0.0.0.0':
        return {"level": "中", "reason": "监听所有网络接口"}
    if address == '127.0.0.1':
        return {"level": "低", "reason": "仅本地访问"}
    return {"level": "低", "reason": "未知服务"}


def check_user_accounts():
    """检查本地用户账户"""
    out, err, rc = run_ps("""
Get-LocalUser | Select-Object Name, Enabled, Description, PasswordRequired, LastLogon |
    ConvertTo-Json
""")
    if not out:
        return []
    try:
        users = json.loads(out)
        if isinstance(users, dict):
            users = [users]
        result = []
        for u in users:
            risk = []
            if u.get('Enabled') and not u.get('PasswordRequired'):
                risk.append("账户已启用但未要求密码")
            if u.get('Name', '').lower() in ('admin', 'administrator', 'root', 'test', 'guest'):
                if u.get('Enabled'):
                    risk.append(f"高危用户名 '{u['Name']}' 已启用")
            result.append({
                "name": u.get('Name', ''),
                "enabled": u.get('Enabled', False),
                "password_required": u.get('PasswordRequired', True),
                "last_logon": str(u.get('LastLogon', '')),
                "risks": risk
            })
        return result
    except json.JSONDecodeError:
        return []


def check_firewall():
    """检查防火墙状态"""
    out, err, rc = run_ps("""
@{
    All = (Get-NetFirewallProfile).Enabled
    Domain = (Get-NetFirewallProfile -Profile Domain).Enabled
    Private = (Get-NetFirewallProfile -Profile Private).Enabled
    Public = (Get-NetFirewallProfile -Profile Public).Enabled
} | ConvertTo-Json
""")
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"error": "无法获取防火墙状态"}


def check_windows_update():
    """检查 Windows 更新状态"""
    out, err, rc = run_ps("""
$sess = New-Object -ComObject Microsoft.Update.Session
$searcher = $sess.CreateUpdateSearcher()
$result = $searcher.Search("IsInstalled=0")
@{
    PendingUpdates = $result.Updates.Count
    LastSearch = $searcher.QueryHistory(0,1) | Select-Object -First 1 | ForEach-Object { $_.Date }
} | ConvertTo-Json
""")
    return out or "无法获取更新状态"


def main():
    parser = argparse.ArgumentParser(description="Marvis 安全巡检")
    parser.add_argument("root", nargs="?", default=".", help="扫描根目录（默认当前目录）")
    parser.add_argument("--action", choices=[
        "full", "sensitive-files", "ports", "users", "firewall", "updates"
    ], default="full", help="检查类型")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    results = {}

    if args.action in ("full", "sensitive-files"):
        results["sensitive_files"] = check_sensitive_files(os.path.abspath(args.root))

    if args.action in ("full", "ports"):
        results["open_ports"] = check_open_ports()

    if args.action in ("full", "users"):
        results["user_accounts"] = check_user_accounts()

    if args.action in ("full", "firewall"):
        results["firewall"] = check_firewall()

    if args.action in ("full", "updates"):
        results["windows_update"] = check_windows_update()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        print("=" * 60)
        print("🛡️ 安全巡检报告")
        print("=" * 60)

        if "sensitive_files" in results:
            findings = results["sensitive_files"]
            print(f"\n🔍 敏感文件扫描: 发现 {len(findings)} 个风险")
            for f in findings[:20]:
                icon = "🔴" if f["severity"] == "高" else "🟡" if f["severity"] == "中" else "🟢"
                print(f"  {icon} [{f['severity']}] {f['file']}")
                print(f"     {f['detail']}")
            if not findings:
                print("  ✅ 未发现敏感文件泄露")

        if "open_ports" in results:
            ports = results["open_ports"]
            print(f"\n🌐 开放端口: {len(ports)} 个监听端口")
            for p in ports[:15]:
                icon = "🔴" if p["risk"]["level"] == "高" else "🟡" if p["risk"]["level"] == "中" else "🟢"
                print(f"  {icon} {p['address']}:{p['port']} ({p['process'] or 'unknown'}) - {p['risk']['reason']}")

        if "user_accounts" in results:
            users = results["user_accounts"]
            print(f"\n👤 用户账户: {len(users)} 个")
            for u in users:
                icon = "⚠️" if u["risks"] else "✅"
                print(f"  {icon} {u['name']} (启用:{u['enabled']}, 需密码:{u['password_required']})")
                for r in u["risks"]:
                    print(f"     ⚡ {r}")

        if "firewall" in results:
            fw = results["firewall"]
            print(f"\n🔒 防火墙状态:")
            if isinstance(fw, dict):
                for profile, enabled in fw.items():
                    icon = "✅" if enabled else "❌"
                    print(f"  {icon} {profile}: {'启用' if enabled else '未启用'}")

        if "windows_update" in results:
            print(f"\n📦 Windows 更新: {results['windows_update']}")


if __name__ == "__main__":
    main()