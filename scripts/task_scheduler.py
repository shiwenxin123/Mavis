#!/usr/bin/env python3
"""Marvis 定时任务与自动化 - 创建/管理/执行定时任务"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

TASK_DIR = os.path.join(os.path.expanduser("~"), ".marvis", "tasks")


def ensure_task_dir():
    os.makedirs(TASK_DIR, exist_ok=True)


def task_file(task_name):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_name)
    return os.path.join(TASK_DIR, f"{safe}.json")


def create_task(name, task_type, command=None, url=None, schedule=None, 
                keyword=None, watch_path=None, description=None):
    """创建定时任务"""
    ensure_task_dir()
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
    
    path = task_file(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    
    # 注册到 Windows 任务计划程序
    if schedule:
        register_scheduled_task(name, schedule, command, task_type, url, keyword, watch_path)
    
    return task


def register_scheduled_task(name, schedule, command=None, task_type=None, 
                            url=None, keyword=None, watch_path=None):
    """注册 Windows 任务计划程序"""
    # 构建要执行的 Python 脚本调用
    script_path = os.path.abspath(__file__)
    
    if task_type == "script" and command:
        exec_cmd = command
    elif task_type == "url-ping" and url:
        exec_cmd = f'powershell -Command "Invoke-WebRequest -Uri \'{url}\' -UseBasicParsing | Select-Object StatusCode"'
    elif task_type == "remind":
        exec_cmd = f'powershell -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show(\'{command or name}\', \'Marvis 提醒\')"'
    else:
        exec_cmd = f'python "{script_path}" --run-task "{name}"'
    
    # 解析 schedule 格式: "daily:08:00", "hourly", "every:30min", "weekly:mon:09:00"
    trigger = parse_schedule(schedule)
    
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
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=15
        )
        if result.returncode != 0:
            print(f"注册任务计划失败: {result.stderr.strip()}", file=sys.stderr)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def parse_schedule(schedule):
    """解析定时规则为 PowerShell 触发器"""
    parts = schedule.lower().split(":")
    if parts[0] == "daily" and len(parts) >= 2:
        time = parts[1]
        return f"New-ScheduledTaskTrigger -Daily -At '{time}'"
    elif parts[0] == "hourly":
        return "New-ScheduledTaskTrigger -Once -RepetitionInterval (New-TimeSpan -Hours 1)"
    elif parts[0] == "every" and len(parts) >= 2:
        interval = parts[1]  # e.g. "30min"
        if "min" in interval:
            mins = int(interval.replace("min", ""))
            return f"New-ScheduledTaskTrigger -Once -RepetitionInterval (New-TimeSpan -Minutes {mins})"
        elif "h" in interval:
            hrs = int(interval.replace("h", ""))
            return f"New-ScheduledTaskTrigger -Once -RepetitionInterval (New-TimeSpan -Hours {hrs})"
    elif parts[0] == "weekly" and len(parts) >= 3:
        day = parts[1].capitalize()
        time = parts[2]
        return f"New-ScheduledTaskTrigger -Weekly -DaysOfWeek {day} -At '{time}'"
    
    # 默认：每天 9:00
    return "New-ScheduledTaskTrigger -Daily -At '09:00'"


def list_tasks():
    """列出所有任务"""
    ensure_task_dir()
    tasks = []
    for f in os.listdir(TASK_DIR):
        if f.endswith(".json"):
            with open(os.path.join(TASK_DIR, f), "r", encoding="utf-8") as fh:
                tasks.append(json.load(fh))
    return tasks


def get_task(name):
    """获取单个任务"""
    path = task_file(name)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_task(name):
    """删除任务"""
    path = task_file(name)
    safe_name = "Marvis_" + "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    
    # 从 Windows 任务计划程序中移除
    ps_script = f"Unregister-ScheduledTask -TaskName '{safe_name}' -Confirm:$false"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as f:
        f.write(ps_script)
        tmp = f.name
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=10
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


def run_task(name):
    """手动执行任务"""
    task = get_task(name)
    if not task:
        print(f"任务不存在: {name}", file=sys.stderr)
        return
    
    task_type = task["type"]
    result = {"task": name, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "status": "unknown"}
    
    try:
        if task_type == "script" and task.get("command"):
            proc = subprocess.run(
                task["command"], shell=True, capture_output=True, text=True, 
                encoding="utf-8", timeout=60
            )
            result["status"] = "success" if proc.returncode == 0 else "failed"
            result["output"] = proc.stdout[:500]
            result["error"] = proc.stderr[:200] if proc.stderr else None
            
        elif task_type == "url-ping" and task.get("url"):
            resp = subprocess.run(
                ["powershell", "-NoProfile", "-Command", 
                 f"(Invoke-WebRequest -Uri '{task['url']}' -UseBasicParsing -TimeoutSec 10).StatusCode"],
                capture_output=True, text=True, encoding="utf-8", timeout=15
            )
            result["status"] = "success" if "200" in resp.stdout else "failed"
            result["output"] = f"HTTP {resp.stdout.strip()}"
            
        elif task_type == "remind":
            msg = task.get("command", name)
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Add-Type -AssemblyName PresentationFramework; "
                 f"[System.Windows.MessageBox]::Show('{msg}', 'Marvis 提醒')"],
                capture_output=True, text=True, encoding="utf-8", timeout=30
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
                        stat = os.stat(fp)
                        files.append({"name": f, "size": stat.st_size, "modified": 
                                     datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
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
    path = task_file(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Marvis 定时任务与自动化")
    parser.add_argument("--action", choices=[
        "create", "list", "delete", "run", "get"
    ], required=True, help="操作类型")
    parser.add_argument("--name", "-n", help="任务名称")
    parser.add_argument("--type", "-t", choices=["script", "url-ping", "remind", "file-watch"], help="任务类型")
    parser.add_argument("--command", "-c", help="执行的命令/脚本")
    parser.add_argument("--url", "-u", help="URL (url-ping 类型)")
    parser.add_argument("--schedule", "-s", help="定时规则 (daily:08:00, hourly, every:30min, weekly:mon:09:00)")
    parser.add_argument("--keyword", "-k", help="监控关键词")
    parser.add_argument("--watch-path", "-w", help="监控目录路径")
    parser.add_argument("--description", "-d", help="任务描述")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    args = parser.parse_args()

    if args.action == "create":
        if not args.name:
            print("错误: 需要指定 --name", file=sys.stderr)
            sys.exit(1)
        if not args.type:
            print("错误: 需要指定 --type", file=sys.stderr)
            sys.exit(1)
        task = create_task(
            args.name, args.type, args.command, args.url, args.schedule,
            args.keyword, args.watch_path, args.description
        )
        if args.json:
            print(json.dumps(task, ensure_ascii=False, indent=2))
        else:
            print(f"任务已创建: {args.name}")
            print(f"  类型: {args.type}")
            if args.schedule:
                print(f"  定时: {args.schedule}")
            print(f"  ⚠️ 定时任务已注册到 Windows 任务计划程序")

    elif args.action == "list":
        tasks = list_tasks()
        if args.json:
            print(json.dumps(tasks, ensure_ascii=False, indent=2))
        else:
            if not tasks:
                print("暂无定时任务。")
            else:
                print(f"共 {len(tasks)} 个任务:\n")
                for t in tasks:
                    status = t.get("last_status") or "未执行"
                    print(f"  [{t['type']}] {t['name']}")
                    print(f"    定时: {t.get('schedule', '手动')}")
                    print(f"    上次: {t.get('last_run', '-')} ({status})")
                    print(f"    执行次数: {t.get('run_count', 0)}")
                    print()

    elif args.action == "get":
        if not args.name:
            print("错误: 需要指定 --name", file=sys.stderr)
            sys.exit(1)
        task = get_task(args.name)
        if not task:
            print(f"任务不存在: {args.name}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(task, ensure_ascii=False, indent=2))

    elif args.action == "delete":
        if not args.name:
            print("错误: 需要指定 --name", file=sys.stderr)
            sys.exit(1)
        if delete_task(args.name):
            print(f"任务已删除: {args.name}")
        else:
            print(f"任务不存在: {args.name}", file=sys.stderr)
            sys.exit(1)

    elif args.action == "run":
        if not args.name:
            print("错误: 需要指定 --name", file=sys.stderr)
            sys.exit(1)
        result = run_task(args.name)
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()