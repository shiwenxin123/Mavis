"""
Marvis 快捷工作流 — 组合操作为可复用流程。

支持：shell/Python/PowerShell/条件/通知步骤。参数模板 {{param}} 运行时替换。

可导入使用：
    from marvis.core.workflow import create_workflow, run_workflow, list_workflows, builtin_templates
"""

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

WORKFLOW_DIR = os.path.join(os.path.expanduser("~"), ".marvis", "workflows")

def _ensure_dir():
    os.makedirs(WORKFLOW_DIR, exist_ok=True)

def _path(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return os.path.join(WORKFLOW_DIR, f"{safe}.json")


def create_workflow(name: str, steps: list[dict], description: str = "") -> dict:
    """创建新的工作流"""
    _ensure_dir()
    wf = {
        "name": name, "description": description, "steps": steps,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_run": None, "run_count": 0,
    }
    with open(_path(name), "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
    return wf


def list_workflows() -> list[dict]:
    """列出所有工作流"""
    _ensure_dir()
    workflows = []
    for f in os.listdir(WORKFLOW_DIR):
        if f.endswith(".json"):
            with open(os.path.join(WORKFLOW_DIR, f), "r", encoding="utf-8") as fh:
                workflows.append(json.load(fh))
    return workflows


def get_workflow(name: str) -> Optional[dict]:
    """获取单个工作流"""
    path = _path(name)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_workflow(name: str) -> bool:
    """删除工作流"""
    path = _path(name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def run_workflow(name: str, params: Optional[dict] = None) -> dict:
    """执行工作流，支持 {{param}} 模板替换"""
    wf = get_workflow(name)
    if not wf:
        return {"error": f"工作流不存在: {name}"}

    results = []
    context: dict = {"params": params or {}}

    for i, step in enumerate(wf["steps"]):
        step_type = step.get("type", "command")
        result = {"step": i + 1, "name": step.get("name", f"Step {i+1}"), "type": step_type}

        try:
            if step_type == "command":
                cmd = step.get("command", "")
                if params:
                    for k, v in params.items():
                        cmd = cmd.replace(f"{{{{{k}}}}}", str(v))
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                      encoding="utf-8", timeout=60)
                result["status"] = "success" if proc.returncode == 0 else "failed"
                result["output"] = proc.stdout[:500] if proc.stdout else ""
                result["error"] = proc.stderr[:200] if proc.stderr else ""
                context[f"step_{i+1}_output"] = proc.stdout.strip()

            elif step_type == "python":
                code = step.get("code", "")
                if params:
                    for k, v in params.items():
                        code = code.replace(f"{{{{{k}}}}}", str(v))
                proc = subprocess.run(["python", "-c", code], capture_output=True,
                                      text=True, encoding="utf-8", timeout=60)
                result["status"] = "success" if proc.returncode == 0 else "failed"
                result["output"] = proc.stdout[:500] if proc.stdout else ""

            elif step_type == "powershell":
                ps = step.get("command", "")
                if params:
                    for k, v in params.items():
                        ps = ps.replace(f"{{{{{k}}}}}", str(v))
                with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1",
                                                  encoding="utf-8-sig", delete=False) as tf:
                    tf.write(ps)
                    tmp = tf.name
                try:
                    proc = subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
                        capture_output=True, text=True, encoding="utf-8", timeout=30
                    )
                    result["status"] = "success" if proc.returncode == 0 else "failed"
                    result["output"] = proc.stdout[:500] if proc.stdout else ""
                finally:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

            elif step_type == "condition":
                var = step.get("variable", "")
                if var in context:
                    result["evaluated"] = str(context[var])
                    result["status"] = "evaluated"

            elif step_type == "notify":
                msg = step.get("message", "工作流通知")
                result["status"] = "notified"
                result["message"] = msg

        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        results.append(result)

        if step.get("stop_on_error", True) and result.get("status") in ("failed", "error", "timeout"):
            break

    # 更新执行记录
    wf["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wf["run_count"] = wf.get("run_count", 0) + 1
    with open(_path(name), "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)

    return {
        "workflow": name, "total_steps": len(wf["steps"]),
        "executed_steps": len(results), "results": results,
    }


def builtin_templates() -> dict:
    """内置工作流模板"""
    return {
        "项目初始化": {
            "description": "新项目初始化：创建目录结构、git仓库、README",
            "steps": [
                {"type": "command", "name": "初始化 Git", "command": "git init"},
                {"type": "command", "name": "创建目录",
                 "command": "md src docs tests 2>$null; echo done"},
                {"type": "command", "name": "创建 README",
                 "command": "echo '# {{project_name}}' > README.md"},
                {"type": "command", "name": "创建 .gitignore",
                 "command": "echo '__pycache__/`n*.pyc`n.env`nnode_modules/' > .gitignore"},
                {"type": "notify", "message": "项目初始化完成！"}
            ]
        },
        "日报生成": {
            "description": "扫描今日修改的文件，生成工作日报",
            "steps": [
                {"type": "python", "name": "扫描今日文件",
                 "code": "import os; from datetime import datetime; "
                         "today = datetime.now().date(); "
                         "[print(f) for f in os.listdir('.') "
                         "if os.path.isfile(f) and "
                         "datetime.fromtimestamp(os.path.getmtime(f)).date() == today]"},
                {"type": "notify", "message": "日报已生成"}
            ]
        },
        "安全检查": {
            "description": "快速安全巡检：敏感文件+端口+防火墙",
            "steps": [
                {"type": "command", "name": "敏感文件扫描",
                 "command": "python -m marvis.core.security_audit --action sensitive-files"},
                {"type": "command", "name": "端口检查",
                 "command": "netstat -an | findstr LISTENING"},
                {"type": "notify", "message": "安全检查完成"}
            ]
        },
        "环境清理": {
            "description": "清理开发环境临时文件",
            "steps": [
                {"type": "powershell", "name": "清理 Python 缓存",
                 "command": "Get-ChildItem -Recurse -Filter '__pycache__' | Remove-Item -Recurse -Force"},
                {"type": "powershell", "name": "清理 .pyc",
                 "command": "Get-ChildItem -Recurse -Filter '*.pyc' | Remove-Item -Force"},
                {"type": "notify", "message": "环境清理完成！"}
            ]
        },
    }
