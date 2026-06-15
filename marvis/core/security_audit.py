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
import re
import subprocess
import tempfile
from typing import Optional


def _run_ps(script: str, timeout: int = 30) -> tuple:
    """运行 PowerShell 脚本"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as f:
        f.write(script)
        tmp = f.name
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
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


def check_open_ports() -> list[dict]:
    """检查本机监听端口"""
    out, _, _ = _run_ps("Get-NetTCPConnection -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess | Sort-Object LocalPort | ConvertTo-Json")
    if not out:
        return []
    try:
        ports = json.loads(out)
        if isinstance(ports, dict):
            ports = [ports]
        result = []
        seen = set()
        for p in ports:
            key = (p.get("LocalAddress", ""), p.get("LocalPort", 0))
            if key in seen:
                continue
            seen.add(key)
            pid = p.get("OwningProcess", 0)
            proc_name = ""
            if pid:
                try:
                    proc = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).ProcessName"],
                        capture_output=True, text=True, encoding="utf-8", timeout=5)
                    proc_name = proc.stdout.strip()
                except Exception:
                    pass
            risk = _assess_port_risk(p.get("LocalPort", 0), p.get("LocalAddress", ""))
            result.append({"address": p.get("LocalAddress", ""), "port": p.get("LocalPort", 0),
                           "pid": pid, "process": proc_name, "risk": risk})
        return result
    except json.JSONDecodeError:
        return []


def check_user_accounts() -> list[dict]:
    """检查本地用户账户"""
    out, _, _ = _run_ps("Get-LocalUser | Select-Object Name, Enabled, Description, PasswordRequired, LastLogon | ConvertTo-Json")
    if not out:
        return []
    try:
        users = json.loads(out)
        if isinstance(users, dict):
            users = [users]
        result = []
        for u in users:
            risks = []
            if u.get("Enabled") and not u.get("PasswordRequired"):
                risks.append("账户已启用但未要求密码")
            if u.get("Name", "").lower() in ("admin", "administrator", "root", "test", "guest"):
                if u.get("Enabled"):
                    risks.append(f"高危用户名 '{u['Name']}' 已启用")
            result.append({
                "name": u.get("Name", ""),
                "enabled": u.get("Enabled", False),
                "password_required": u.get("PasswordRequired", True),
                "last_logon": str(u.get("LastLogon", "")),
                "risks": risks,
            })
        return result
    except json.JSONDecodeError:
        return []


def check_firewall() -> dict:
    """检查防火墙状态"""
    ps = """
@{
    Domain = (Get-NetFirewallProfile -Profile Domain).Enabled
    Private = (Get-NetFirewallProfile -Profile Private).Enabled
    Public = (Get-NetFirewallProfile -Profile Public).Enabled
} | ConvertTo-Json
"""
    out, _, _ = _run_ps(ps)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"error": "无法获取防火墙状态"}


def check_windows_update() -> str:
    """检查 Windows 更新状态"""
    ps = """
$sess = New-Object -ComObject Microsoft.Update.Session
$searcher = $sess.CreateUpdateSearcher()
$result = $searcher.Search("IsInstalled=0")
@{
    PendingUpdates = $result.Updates.Count
} | ConvertTo-Json
"""
    out, _, _ = _run_ps(ps)
    try:
        data = json.loads(out)
        return f"待更新: {data.get('PendingUpdates', '?')} 个"
    except Exception:
        return out or "无法获取更新状态"


def full_audit(root: Optional[str] = None) -> dict:
    """执行完整安全巡检"""
    if root is None:
        root = os.getcwd()
    return {
        "sensitive_files": check_sensitive_files(os.path.abspath(root)),
        "open_ports": check_open_ports(),
        "user_accounts": check_user_accounts(),
        "firewall": check_firewall(),
        "windows_update": check_windows_update(),
    }
