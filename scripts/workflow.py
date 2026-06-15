#!/usr/bin/env python3
"""Marvis 快捷工作流 - 组合常用操作为可复用工作流"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

WORKFLOW_DIR = os.path.join(os.path.expanduser("~"), ".marvis", "workflows")


def ensure_workflow_dir():
    os.makedirs(WORKFLOW_DIR, exist_ok=True)


def workflow_file(name):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return os.path.join(WORKFLOW_DIR, f"{safe}.json")


def create_workflow(name, steps, description=None):
    """创建工作流"""
    ensure_workflow_dir()
    workflow = {
        "name": name,
        "description": description or "",
        "steps": steps,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_run": None,
        "run_count": 0,
    }
    path = workflow_file(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workflow, f, ensure_ascii=False, indent=2)
    return workflow


def list_workflows():
    """列出所有工作流"""
    ensure_workflow_dir()
    workflows = []
    for f in os.listdir(WORKFLOW_DIR):
        if f.endswith(".json"):
            with open(os.path.join(WORKFLOW_DIR, f), "r", encoding="utf-8") as fh:
                workflows.append(json.load(fh))
    return workflows


def get_workflow(name):
    """获取单个工作流"""
    path = workflow_file(name)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_workflow(name):
    """删除工作流"""
    path = workflow_file(name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def run_workflow(name, params=None):
    """执行工作流"""
    workflow = get_workflow(name)
    if not workflow:
        return {"error": f"工作流不存在: {name}"}

    results = []
    context = {"params": params or {}}

    for i, step in enumerate(workflow["steps"]):
        step_type = step.get("type", "command")
        step_result = {"step": i + 1, "name": step.get("name", f"Step {i+1}"), "type": step_type}

        try:
            if step_type == "command":
                cmd = step.get("command", "")
                # 替换参数
                if params:
                    for key, val in params.items():
                        cmd = cmd.replace(f"{{{{{key}}}}}", str(val))
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, 
                    encoding="utf-8", timeout=60
                )
                step_result["status"] = "success" if proc.returncode == 0 else "failed"
                step_result["output"] = proc.stdout[:500] if proc.stdout else ""
                step_result["error"] = proc.stderr[:200] if proc.stderr else ""
                # 输出存入上下文供后续步骤使用
                context[f"step_{i+1}_output"] = proc.stdout.strip()

            elif step_type == "python":
                code = step.get("code", "")
                if params:
                    for key, val in params.items():
                        code = code.replace(f"{{{{{key}}}}}", str(val))
                proc = subprocess.run(
                    ["python", "-c", code], capture_output=True, text=True,
                    encoding="utf-8", timeout=60
                )
                step_result["status"] = "success" if proc.returncode == 0 else "failed"
                step_result["output"] = proc.stdout[:500] if proc.stdout else ""

            elif step_type == "powershell":
                ps_cmd = step.get("command", "")
                if params:
                    for key, val in params.items():
                        ps_cmd = ps_cmd.replace(f"{{{{{key}}}}}", str(val))
                with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as f:
                    f.write(ps_cmd)
                    tmp = f.name
                try:
                    proc = subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
                        capture_output=True, text=True, encoding="utf-8", timeout=30
                    )
                    step_result["status"] = "success" if proc.returncode == 0 else "failed"
                    step_result["output"] = proc.stdout[:500] if proc.stdout else ""
                finally:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

            elif step_type == "condition":
                condition = step.get("condition", "")
                var_name = step.get("variable", "")
                if var_name and var_name in context:
                    step_result["evaluated"] = str(context[var_name])
                    step_result["status"] = "evaluated"

            elif step_type == "notify":
                msg = step.get("message", "工作流通知")
                print(f"📢 {msg}")
                step_result["status"] = "notified"
                step_result["message"] = msg

        except subprocess.TimeoutExpired:
            step_result["status"] = "timeout"
        except Exception as e:
            step_result["status"] = "error"
            step_result["error"] = str(e)

        results.append(step_result)

        # 如果某步失败且配置了 stop_on_error，则终止
        if step.get("stop_on_error", True) and step_result.get("status") in ("failed", "error", "timeout"):
            break

    # 更新工作流记录
    workflow["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    workflow["run_count"] = workflow.get("run_count", 0) + 1
    path = workflow_file(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workflow, f, ensure_ascii=False, indent=2)

    return {
        "workflow": name,
        "total_steps": len(workflow["steps"]),
        "executed_steps": len(results),
        "results": results
    }


def builtin_workflows():
    """内置常用工作流模板"""
    return {
        "项目初始化": {
            "description": "新项目初始化：创建目录结构、git仓库、README",
            "steps": [
                {"type": "command", "name": "初始化 Git", "command": "git init"},
                {"type": "command", "name": "创建目录", "command": "mkdir src docs tests 2>$null; echo done"},
                {"type": "command", "name": "创建 README", "command": "echo '# {{project_name}}' > README.md"},
                {"type": "command", "name": "创建 .gitignore", "command": "echo '__pycache__/\n*.pyc\n.env\nnode_modules/' > .gitignore"},
                {"type": "notify", "message": "项目初始化完成！"}
            ]
        },
        "日报生成": {
            "description": "扫描今日修改的文件，生成工作日报",
            "steps": [
                {"type": "python", "name": "扫描今日文件", 
                 "code": "import os; from datetime import datetime; today = datetime.now().date(); [print(f) for f in os.listdir('.') if os.path.isfile(f) and datetime.fromtimestamp(os.path.getmtime(f)).date() == today]"},
                {"type": "notify", "message": "日报已生成，请根据文件修改记录补充内容"}
            ]
        },
        "安全检查": {
            "description": "快速安全巡检：敏感文件+端口+防火墙",
            "steps": [
                {"type": "command", "name": "敏感文件扫描", "command": "python -c \"from marvis.security_audit import check_sensitive_files; print(check_sensitive_files('.'))\" 2>$null; echo 'scan done'"},
                {"type": "command", "name": "端口检查", "command": "netstat -an | findstr LISTENING"},
                {"type": "notify", "message": "安全检查完成，请查看上方结果"}
            ]
        },
        "环境清理": {
            "description": "清理开发环境临时文件",
            "steps": [
                {"type": "command", "name": "清理 Python 缓存", "command": "powershell -Command \"Get-ChildItem -Recurse -Filter '__pycache__' | Remove-Item -Recurse -Force\""},
                {"type": "command", "name": "清理 .pyc", "command": "powershell -Command \"Get-ChildItem -Recurse -Filter '*.pyc' | Remove-Item -Force\""},
                {"type": "command", "name": "清理临时文件", "command": "powershell -Command \"Get-ChildItem $env:TEMP | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue\""},
                {"type": "notify", "message": "环境清理完成！"}
            ]
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Marvis 快捷工作流")
    parser.add_argument("--action", choices=[
        "create", "list", "run", "delete", "get", "templates"
    ], required=True, help="操作类型")
    parser.add_argument("--name", "-n", help="工作流名称")
    parser.add_argument("--steps", "-s", help="步骤 JSON（创建时使用）")
    parser.add_argument("--description", "-d", help="工作流描述")
    parser.add_argument("--params", "-p", help="运行参数 JSON")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.action == "templates":
        templates = builtin_workflows()
        if args.json:
            print(json.dumps(templates, ensure_ascii=False, indent=2))
        else:
            print("📋 内置工作流模板:\n")
            for name, wf in templates.items():
                print(f"  🔄 {name}")
                print(f"     {wf['description']}")
                print(f"     步骤数: {len(wf['steps'])}")
                print()

    elif args.action == "create":
        if not args.name:
            print("错误: 需要指定 --name", file=sys.stderr)
            sys.exit(1)
        if not args.steps:
            print("错误: 需要指定 --steps (JSON 格式)", file=sys.stderr)
            sys.exit(1)
        try:
            steps = json.loads(args.steps)
        except json.JSONDecodeError:
            print("错误: --steps 格式不正确", file=sys.stderr)
            sys.exit(1)
        wf = create_workflow(args.name, steps, args.description)
        if args.json:
            print(json.dumps(wf, ensure_ascii=False, indent=2))
        else:
            print(f"✅ 工作流已创建: {args.name} ({len(steps)} 步)")

    elif args.action == "list":
        workflows = list_workflows()
        if args.json:
            print(json.dumps(workflows, ensure_ascii=False, indent=2))
        else:
            if not workflows:
                print("暂无自定义工作流。使用 --action templates 查看内置模板。")
            else:
                print(f"共 {len(workflows)} 个工作流:\n")
                for wf in workflows:
                    print(f"  🔄 {wf['name']}")
                    print(f"     {wf.get('description', '')}")
                    print(f"     步骤数: {len(wf['steps'])}, 执行次数: {wf.get('run_count', 0)}")
                    print()

    elif args.action == "run":
        if not args.name:
            print("错误: 需要指定 --name", file=sys.stderr)
            sys.exit(1)
        params = None
        if args.params:
            try:
                params = json.loads(args.params)
            except json.JSONDecodeError:
                params = {"input": args.params}
        result = run_workflow(args.name, params)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            if "error" in result:
                print(f"❌ {result['error']}")
            else:
                print(f"🔄 工作流: {result['workflow']}")
                print(f"   步骤: {result['executed_steps']}/{result['total_steps']}\n")
                for r in result["results"]:
                    icon = "✅" if r.get("status") == "success" else "❌" if r.get("status") == "failed" else "ℹ️"
                    print(f"  {icon} [{r['type']}] {r['name']}: {r.get('status', 'N/A')}")
                    if r.get("output"):
                        preview = r["output"][:100].replace('\n', ' ')
                        print(f"     {preview}")

    elif args.action == "get":
        if not args.name:
            print("错误: 需要指定 --name", file=sys.stderr)
            sys.exit(1)
        wf = get_workflow(args.name)
        if not wf:
            print(f"工作流不存在: {args.name}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(wf, ensure_ascii=False, indent=2))

    elif args.action == "delete":
        if not args.name:
            print("错误: 需要指定 --name", file=sys.stderr)
            sys.exit(1)
        if delete_workflow(args.name):
            print(f"已删除工作流: {args.name}")
        else:
            print(f"工作流不存在: {args.name}", file=sys.stderr)


if __name__ == "__main__":
    main()