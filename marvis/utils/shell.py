"""
跨平台 Shell 抽象层。

封装 Linux/macOS/Windows 的 Shell 调用差异，
统一为 Python 函数接口。
"""

import os
import platform
import subprocess
import sys
import tempfile
from typing import Optional, Tuple


SYSTEM = platform.system()  # "Windows" | "Linux" | "Darwin"
IS_WINDOWS = SYSTEM == "Windows"


def run(
    command: str,
    shell: bool = True,
    timeout: int = 60,
    cwd: Optional[str] = None,
    encoding: str = "utf-8",
) -> Tuple[str, str, int]:
    """跨平台执行命令，返回 (stdout, stderr, returncode)"""
    try:
        proc = subprocess.run(
            command,
            shell=shell,
            capture_output=True,
            text=True,
            encoding=encoding,
            timeout=timeout,
            cwd=cwd,
        )
        return proc.stdout.strip(), proc.stderr.strip(), proc.returncode
    except subprocess.TimeoutExpired:
        return "", "命令超时", -1
    except Exception as e:
        return "", str(e), -1


def run_powershell(script: str, timeout: int = 30) -> Tuple[str, str, int]:
    """运行 PowerShell 脚本（跨平台安全方式）"""
    if IS_WINDOWS:
        # 通过临时 .ps1 文件执行，避免命令行转义问题
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False
        ) as f:
            f.write(script)
            tmp_path = f.name
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    else:
        # 非 Windows：尝试 pwsh，回退到简单说明
        pwsh = _find_pwsh()
        if pwsh:
            proc = subprocess.run(
                [pwsh, "-NoProfile", "-Command", script],
                capture_output=True, text=True, encoding="utf-8", timeout=timeout
            )
            return proc.stdout.strip(), proc.stderr.strip(), proc.returncode
        return "", "PowerShell 不可用（非 Windows 平台需安装 pwsh）", -1


def _find_pwsh() -> Optional[str]:
    """查找 pwsh 路径"""
    for candidate in ["pwsh", "/usr/local/bin/pwsh", "/opt/microsoft/powershell/7/pwsh"]:
        try:
            subprocess.run([candidate, "--version"], capture_output=True, timeout=5)
            return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def is_admin() -> bool:
    """检查是否具有管理员/root 权限"""
    try:
        if IS_WINDOWS:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except Exception:
        return False


def get_env(var: str, default: str = "") -> str:
    """获取环境变量"""
    return os.environ.get(var, default)


def which(program: str) -> Optional[str]:
    """查找可执行文件路径（跨平台 which）"""
    if IS_WINDOWS:
        ext_list = os.environ.get("PATHEXT", ".EXE;.CMD;.BAT;.PS1").split(";")
        for ext in ext_list:
            full = f"{program}{ext}"
            for path_dir in os.environ.get("PATH", "").split(os.pathsep):
                candidate = os.path.join(path_dir, full)
                if os.path.isfile(candidate):
                    return candidate
        return None
    else:
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(path_dir, program)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None
