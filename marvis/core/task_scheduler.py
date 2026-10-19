"""
Marvis 定时任务与自动化 — 创建/管理/执行定时任务，支持 Windows 任务计划程序集成。

可导入使用：
    from marvis.core.task_scheduler import create_task, list_tasks, run_task, delete_task
"""

import json
import os
import platform
import re
import subprocess
import tempfile
from datetime import datetime
from typing import Optional


def _task_dir() -> str:
    from marvis.utils.config import marvis_home
    return str(marvis_home() / "tasks")


def _ensure_dir():
    os.makedirs(_task_dir(), exist_ok=True)


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _task_file(name: str) -> str:
    return os.path.join(_task_dir(), f"{_safe_name(name)}.json")


_WEEKDAYS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}


def _parse_schedule(schedule: str) -> str:
    """解析定时规则为 PowerShell 触发器。只接受固定格式，避免拼进脚本。"""
    text = (schedule or "").strip()
    daily = re.fullmatch(r"daily:(\d{2}:\d{2})", text, re.IGNORECASE)
    if daily:
        return f"New-ScheduledTaskTrigger -Daily -At '{daily.group(1)}'"
    if re.fullmatch(r"hourly", text, re.IGNORECASE):
        return "New-ScheduledTaskTrigger -Once -RepetitionInterval (New-TimeSpan -Hours 1)"
    every = re.fullmatch(r"every:(\d{1,4})(min|h)", text, re.IGNORECASE)
    if every:
        amount = max(1, min(int(every.group(1)), 10080))
        unit = "Minutes" if every.group(2).lower() == "min" else "Hours"
        return (
            "New-ScheduledTaskTrigger -Once -RepetitionInterval "
            f"(New-TimeSpan -{unit} {amount})"
        )
    weekly = re.fullmatch(r"weekly:([A-Za-z]+):(\d{2}:\d{2})", text)
    if weekly and weekly.group(1).lower() in _WEEKDAYS:
        day = weekly.group(1).capitalize()
        return f"New-ScheduledTaskTrigger -Weekly -DaysOfWeek {day} -At '{weekly.group(2)}'"
    return "New-ScheduledTaskTrigger -Daily -At '09:00'"


def create_task(
    name: str,
    task_type: str,
    command: Optional[str] = None,
    url: Optional[str] = None,
    schedule: Optional[str] = None,
    keyword: Optional[str] = None,
    watch_path: Optional[str] = None,
    description: Optional[str] = None,
    register: bool = False,
) -> dict:
    """创建定时任务。默认只保存定义，不注册系统计划任务。"""
    _ensure_dir()
    task = {
        "name": name,
        "type": task_type,
        "command": command,
        "url": url,
        "keyword": keyword,
        "watch_path": watch_path,
        "schedule": schedule,
        "description": description,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_run": None,
        "last_status": None,
        "run_count": 0,
    }
    if schedule and register:
        task["scheduler"] = _register_scheduled_task(
            name, schedule, command, task_type, url, keyword, watch_path
        )
    elif schedule:
        task["scheduler"] = "未注册系统计划任务。默认只保存定义；确认后传入 register=True"
    path = _task_file(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    return task


def _register_scheduled_task(name, schedule, command, task_type, url, keyword, watch_path):
    """注册 Windows 任务计划程序。命令写入受控脚本，不拼进 PowerShell 字符串。"""
    if platform.system() != "Windows":
        return "当前系统无 Windows 任务计划程序，仅保存本地任务"
    if command and any(ch in command for ch in "\n\r\x00"):
        return "命令包含换行或空字符，已拒绝注册系统计划任务"
    safe = "Marvis_" + _safe_name(name)
    script_path = os.path.join(_task_dir(), safe + ".cmd")
    if task_type == "script" and command:
        payload = command
    elif task_type == "remind":
        payload = "echo Marvis reminder"
    else:
        payload = (
            "python -c \"from marvis.core.task_scheduler import run_task; "
            f"run_task({json.dumps(name)})\""
        )
    with open(script_path, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(payload + "\r\n")
    trigger = _parse_schedule(schedule or "")
    quoted = script_path.replace("'", "''")
    ps_script = f"""
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c ""{quoted}""'
$trigger = {trigger}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName '{safe}' -Action $action -Trigger $trigger -Settings $settings -Description 'Marvis auto task' -Force
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as handle:
        handle.write(ps_script)
        tmp = handle.name
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        return "已尝试注册系统计划任务"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"注册失败: {exc}"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def list_tasks() -> list[dict]:
    """列出所有任务"""
    _ensure_dir()
    tasks = []
    for f in os.listdir(_task_dir()):
        if f.endswith(".json"):
            with open(os.path.join(_task_dir(), f), "r", encoding="utf-8") as fh:
                tasks.append(json.load(fh))
    return tasks


def get_task(name: str) -> Optional[dict]:
    """获取单个任务"""
    path = _task_file(name)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_task(name: str) -> bool:
    """删除任务（包括 Windows 任务计划程序中的注册）"""
    path = _task_file(name)
    safe_name = "Marvis_" + _safe_name(name)

    if platform.system() == "Windows":
        ps_script = f"Unregister-ScheduledTask -TaskName '{safe_name}' -Confirm:$false"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as handle:
            handle.write(ps_script)
            tmp = handle.name
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def run_task(name: str) -> dict:
    """手动执行任务"""
    task = get_task(name)
    if not task:
        return {"error": f"任务不存在: {name}"}

    result = {"task": name, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "status": "unknown"}

    try:
        task_type = task["type"]
        if task_type == "script" and task.get("command"):
            proc = subprocess.run(
                task["command"], shell=True, capture_output=True, text=True,
                encoding="utf-8", timeout=60,
            )
            result["status"] = "success" if proc.returncode == 0 else "failed"
            result["output"] = proc.stdout[:500]
            result["error"] = proc.stderr[:200] if proc.stderr else None

        elif task_type == "url-ping" and task.get("url"):
            from marvis.core.web_monitor import http_get
            _body, err, status = http_get(task["url"], timeout=10, read_limit=0)
            if status == 0:
                result["status"] = "failed"
                result["error"] = err
            else:
                result["status"] = "success" if status == 200 else "failed"
                result["output"] = err or f"HTTP {status}"

        elif task_type == "remind":
            msg = str(task.get("command") or name)[:200]
            result["status"] = "success"
            result["output"] = f"提醒: {msg}"

        elif task_type == "file-watch" and task.get("watch_path"):
            wp = task["watch_path"]
            if os.path.isdir(wp):
                files = []
                for f in os.listdir(wp):
                    fp = os.path.join(wp, f)
                    if os.path.isfile(fp):
                        st = os.stat(fp)
                        files.append({
                            "name": f, "size": st.st_size,
                            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        })
                result["status"] = "success"
                result["output"] = f"监控目录 {wp}: {len(files)} 个文件"
                result["files"] = files
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    # 更新任务记录
    task["last_run"] = result["time"]
    task["last_status"] = result["status"]
    task["run_count"] = task.get("run_count", 0) + 1
    with open(_task_file(name), "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)

    return result
