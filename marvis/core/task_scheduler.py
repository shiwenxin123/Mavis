"""
Marvis 定时任务与自动化 — 创建/管理/执行定时任务，支持 Windows 任务计划程序集成。

可导入使用：
    from marvis.core.task_scheduler import create_task, list_tasks, run_task, delete_task
"""

import json
import os
import subprocess
import tempfile
from datetime import datetime
from typing import Optional


TASK_DIR = os.path.join(os.path.expanduser("~"), ".marvis", "tasks")


def _ensure_dir():
    os.makedirs(TASK_DIR, exist_ok=True)


def _task_file(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return os.path.join(TASK_DIR, f"{safe}.json")


def _parse_schedule(schedule: str) -> str:
    """解析定时规则为 PowerShell 触发器"""
    parts = schedule.lower().split(":")
    if parts[0] == "daily" and len(parts) >= 2:
        return f"New-ScheduledTaskTrigger -Daily -At '{parts[1]}'"
    elif parts[0] == "hourly":
        return "New-ScheduledTaskTrigger -Once -RepetitionInterval (New-TimeSpan -Hours 1)"
    elif parts[0] == "every" and len(parts) >= 2:
        interval = parts[1]
        if "min" in interval:
            mins = int(interval.replace("min", ""))
            return f"New-ScheduledTaskTrigger -Once -RepetitionInterval (New-TimeSpan -Minutes {mins})"
        elif "h" in interval:
            hrs = int(interval.replace("h", ""))
            return f"New-ScheduledTaskTrigger -Once -RepetitionInterval (New-TimeSpan -Hours {hrs})"
    elif parts[0] == "weekly" and len(parts) >= 3:
        return f"New-ScheduledTaskTrigger -Weekly -DaysOfWeek {parts[1].capitalize()} -At '{parts[2]}'"
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
) -> dict:
    """创建定时任务"""
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
    path = _task_file(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)

    if schedule:
        _register_scheduled_task(name, schedule, command, task_type, url, keyword, watch_path)

    return task


def _register_scheduled_task(name, schedule, command, task_type, url, keyword, watch_path):
    """注册 Windows 任务计划程序"""
    if task_type == "script" and command:
        exec_cmd = command
    elif task_type == "url-ping" and url:
        exec_cmd = f'powershell -Command "Invoke-WebRequest -Uri \'{url}\' -UseBasicParsing | Select-Object StatusCode"'
    elif task_type == "remind":
        exec_cmd = f'powershell -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show(\'{command or name}\', \'Marvis 提醒\')"'
    else:
        exec_cmd = f'python -c "from marvis.core.task_scheduler import run_task; run_task(\'{name}\')"'

    trigger = _parse_schedule(schedule)
    safe_name = "Marvis_" + "".join(c if c.isalnum() or c in "-_" else "_" for c in name)

    ps_script = f"""
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c {exec_cmd}'
$trigger = {trigger}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName '{safe_name}' -Action $action -Trigger $trigger -Settings $settings -Description 'Marvis auto task: {name}' -Force
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as f:
        f.write(ps_script)
        tmp = f.name
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def list_tasks() -> list[dict]:
    """列出所有任务"""
    _ensure_dir()
    tasks = []
    for f in os.listdir(TASK_DIR):
        if f.endswith(".json"):
            with open(os.path.join(TASK_DIR, f), "r", encoding="utf-8") as fh:
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
    safe_name = "Marvis_" + "".join(c if c.isalnum() or c in "-_" else "_" for c in name)

    ps_script = f"Unregister-ScheduledTask -TaskName '{safe_name}' -Confirm:$false"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as f:
        f.write(ps_script)
        tmp = f.name
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
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
            resp = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Invoke-WebRequest -Uri '{task['url']}' -UseBasicParsing -TimeoutSec 10).StatusCode"],
                capture_output=True, text=True, encoding="utf-8", timeout=15,
            )
            result["status"] = "success" if "200" in resp.stdout else "failed"
            result["output"] = f"HTTP {resp.stdout.strip()}"

        elif task_type == "remind":
            msg = task.get("command", name)
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Add-Type -AssemblyName PresentationFramework; "
                 f"[System.Windows.MessageBox]::Show('{msg}', 'Marvis 提醒')"],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
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
