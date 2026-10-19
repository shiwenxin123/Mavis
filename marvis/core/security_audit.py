"""
Marvis 安全巡检 — 敏感文件扫描、端口检查、账户审计、防火墙检查。

可导入使用：
    from marvis.core.security_audit import (
        check_sensitive_files, check_open_ports,
        check_user_accounts, check_firewall, full_audit
    )
"""

import json
import os
import platform
import re
import subprocess
import tempfile
from typing import Optional


def _run_ps(script: str, timeout: int = 30) -> tuple:
    """运行 PowerShell 脚本。非 Windows 直接返回，不抛异常。"""
    if platform.system() != "Windows":
        return "", "PowerShell 不可用", -1
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as f:
        f.write(script)
        tmp = f.name
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", str(exc), -1
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


SENSITIVE_PATTERNS = [
    (r"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----", "私钥文件", "高"),
    (r'(?:password|passwd|pwd)\s*[=:]\s*\S+', "明文密码", "高"),
    (r'(?:api[_-]?key|apikey|secret[_-]?key)\s*[=:]\s*["\']?\w{8,}', "API 密钥", "高"),
    (r'(?:access[_-]?token|auth[_-]?token)\s*[=:]\s*["\']?\w{8,}', "访问令牌", "高"),
    (r'(?:jdbc|mysql|postgres|mongodb)://\S+:\S+@\S+', "数据库连接串", "高"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key", "高"),
    (r"AIza[0-9A-Za-z\-_]{35}", "Google API Key", "中"),
    (r"ghp_[0-9a-zA-Z]{36}", "GitHub Token", "高"),
    (r"sk-[0-9a-zA-Z]{20,}", "OpenAI API Key", "高"),
    (r"eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*", "JWT Token", "中"),
]

SENSITIVE_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".npmrc", ".pypirc", ".netrc", "_netrc",
    "credentials.json", "service-account.json", "client_secret.json",
    ".htpasswd", "wp-config.php",
}


def check_sensitive_files(root: str) -> list[dict]:
    """扫描目录中的敏感文件"""
    findings = []
    ext_skip = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
                ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".avi",
                ".zip", ".rar", ".7z", ".gz", ".exe", ".dll", ".so", ".dylib"}

    skip_dirs = {".git", "node_modules", "__pycache__", "venv", ".venv"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in ext_skip:
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root)

            if f in SENSITIVE_FILENAMES:
                findings.append({
                    "type": "敏感文件名", "file": rel,
                    "detail": f"发现敏感文件: {f}", "severity": "高"
                })
                continue

            try:
                size = os.path.getsize(full)
                if size > 500_000 or size == 0:
                    continue
                with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                for pattern, desc, severity in SENSITIVE_PATTERNS:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        # 只报告类型和次数，不把密钥正文写进结果
                        findings.append({
                            "type": "敏感内容", "file": rel,
                            "detail": desc, "severity": severity,
                            "count": len(matches),
                        })
                        break
            except (PermissionError, OSError):
                continue
    return findings


def _assess_port_risk(port: int, address: str) -> dict:
    """评估端口风险"""
    high_risk = {22: "SSH", 23: "Telnet", 445: "SMB", 3389: "RDP",
                 5900: "VNC", 6379: "Redis", 27017: "MongoDB", 9200: "Elasticsearch"}
    med_risk = {80: "HTTP", 443: "HTTPS", 3000: "Dev Server", 8080: "HTTP Proxy",
                8443: "HTTPS Alt", 8888: "Jupyter", 5000: "Flask Dev"}
    if port in high_risk:
        return {"level": "高", "reason": f"{high_risk[port]} 服务暴露"}
    if port in med_risk:
        return {"level": "中", "reason": f"{med_risk[port]} 服务在 {port} 端口"}
    if address == "0.0.0.0":
        return {"level": "中", "reason": "监听所有网络接口"}
    if address == "127.0.0.1":
        return {"level": "低", "reason": "仅本地访问"}
    return {"level": "低", "reason": "未知服务"}


def _parse_ss_listeners(text: str) -> list[dict]:
    result = []
    seen = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        if local.startswith("["):
            # [::]:22 或 [::1]:22
            host, _, port_s = local.rpartition(":")
        elif ":" in local:
            host, port_s = local.rsplit(":", 1)
        else:
            continue
        try:
            port = int(port_s)
        except ValueError:
            continue
        key = (host, port)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "address": host,
            "port": port,
            "pid": None,
            "process": "",
            "risk": _assess_port_risk(port, host),
        })
    return result


def _parse_proc_net_tcp(path: str = "/proc/net/tcp") -> list[dict]:
    result = []
    seen = set()
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()[1:]
    except OSError:
        return []
    for line in lines:
        cols = line.split()
        if len(cols) < 4 or cols[3] != "0A":
            continue
        ip_hex, port_hex = cols[1].split(":")
        try:
            raw = bytes.fromhex(ip_hex)
            address = ".".join(str(b) for b in reversed(raw))
            port = int(port_hex, 16)
        except ValueError:
            continue
        key = (address, port)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "address": address,
            "port": port,
            "pid": None,
            "process": "",
            "risk": _assess_port_risk(port, address),
        })
    return result


def _windows_open_ports() -> list[dict]:
    out, _, _ = _run_ps(
        "Get-NetTCPConnection -State Listen | "
        "Select-Object LocalAddress, LocalPort, OwningProcess | "
        "Sort-Object LocalPort | ConvertTo-Json"
    )
    if not out:
        return []
    try:
        ports = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(ports, dict):
        ports = [ports]
    result = []
    seen = set()
    for item in ports:
        address = str(item.get("LocalAddress", ""))
        try:
            port = int(item.get("LocalPort", 0))
        except (TypeError, ValueError):
            continue
        key = (address, port)
        if key in seen:
            continue
        seen.add(key)
        pid = item.get("OwningProcess", 0)
        try:
            pid_num = int(pid)
        except (TypeError, ValueError):
            pid_num = 0
        result.append({
            "address": address,
            "port": port,
            "pid": pid_num,
            "process": "",
            "risk": _assess_port_risk(port, address),
        })
    return result


def check_open_ports() -> list[dict]:
    """检查本机监听端口。只读，不把连接信息发往外部。"""
    if platform.system() == "Windows":
        return _windows_open_ports()
    try:
        proc = subprocess.run(
            ["ss", "-H", "-lnt"],
            capture_output=True, text=True, timeout=8,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return _parse_ss_listeners(proc.stdout)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return _parse_proc_net_tcp()


def _password_statuses() -> dict[str, str]:
    """一次读取 passwd -Sa。失败时返回空，不读取哈希。"""
    try:
        proc = subprocess.run(
            ["passwd", "-Sa"],
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    statuses = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in {"P", "NP", "L", "LK"}:
            statuses[parts[0]] = parts[1]
    return statuses


def _posix_user_accounts() -> list[dict]:
    import pwd

    statuses = _password_statuses()
    result = []
    for user in pwd.getpwall():
        if user.pw_uid != 0 and user.pw_uid < 1000:
            continue
        status = statuses.get(user.pw_name)
        risks = []
        if status == "NP":
            risks.append("账户未设置密码")
        result.append({
            "name": user.pw_name,
            "enabled": status not in {"L", "LK"},
            "uid": user.pw_uid,
            "password_required": None if status is None else status == "P",
            "risks": risks,
        })
    return result


def check_user_accounts() -> list[dict]:
    """检查本地用户账户。不读取、不回传密码哈希。"""
    if platform.system() != "Windows":
        return _posix_user_accounts()
    out, _, _ = _run_ps(
        "Get-LocalUser | Select-Object Name, Enabled, Description, "
        "PasswordRequired, LastLogon | ConvertTo-Json"
    )
    if not out:
        return []
    try:
        users = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(users, dict):
        users = [users]
    result = []
    for user in users:
        risks = []
        if user.get("Enabled") and not user.get("PasswordRequired"):
            risks.append("账户已启用但未要求密码")
        name = str(user.get("Name", ""))
        if name.lower() in ("admin", "administrator", "root", "test", "guest") and user.get("Enabled"):
            risks.append(f"高危用户名 '{name}' 已启用")
        result.append({
            "name": name,
            "enabled": user.get("Enabled", False),
            "password_required": user.get("PasswordRequired", True),
            "last_logon": str(user.get("LastLogon", "")),
            "risks": risks,
        })
    return result


def check_firewall() -> dict:
    """检查防火墙状态。只读查询，不改规则。"""
    if platform.system() == "Windows":
        out, _, _ = _run_ps("""
@{
    Domain = (Get-NetFirewallProfile -Profile Domain).Enabled
    Private = (Get-NetFirewallProfile -Profile Private).Enabled
    Public = (Get-NetFirewallProfile -Profile Public).Enabled
} | ConvertTo-Json
""")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return {"error": "无法获取防火墙状态"}
        if isinstance(data, dict):
            return data
        return {"error": "无法获取防火墙状态"}

    try:
        proc = subprocess.run(
            ["ufw", "status"],
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc is not None and proc.returncode == 0 and proc.stdout.strip():
        first = proc.stdout.strip().splitlines()[0][:200]
        return {
            "tool": "ufw",
            "enabled": "inactive" not in first.lower(),
            "summary": first,
        }
    return {
        "tool": None,
        "enabled": None,
        "note": "未检测到 ufw。未改动防火墙。",
    }


def check_windows_update() -> str:
    """检查 Windows 更新状态"""
    if platform.system() != "Windows":
        return "不适用（非 Windows）"
    out, _, _ = _run_ps("""
$sess = New-Object -ComObject Microsoft.Update.Session
$searcher = $sess.CreateUpdateSearcher()
$result = $searcher.Search("IsInstalled=0")
@{
    PendingUpdates = $result.Updates.Count
} | ConvertTo-Json
""")
    try:
        data = json.loads(out)
        return f"待更新: {data.get('PendingUpdates', '?')} 个"
    except Exception:
        return "无法获取更新状态"


def full_audit(root: Optional[str] = None) -> dict:
    """执行完整安全巡检。单项失败不影响其余结果，也不外传文件内容。"""
    root = os.path.abspath(root or os.getcwd())
    report: dict = {"root": root, "notes": []}
    checks = (
        ("sensitive_files", lambda: check_sensitive_files(root)),
        ("open_ports", check_open_ports),
        ("user_accounts", check_user_accounts),
        ("firewall", check_firewall),
        ("windows_update", check_windows_update),
    )
    for name, fn in checks:
        try:
            report[name] = fn()
        except Exception as exc:
            report[name] = [] if name != "firewall" else {}
            report["notes"].append(f"{name} 检查失败: {exc}")
    return report
