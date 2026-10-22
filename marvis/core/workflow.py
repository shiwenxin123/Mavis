"""
Marvis 快捷工作流 — 组合操作为可复用流程。

支持：shell/Python/PowerShell/条件/通知步骤。参数模板 {{param}} 运行时替换。

可导入使用：
    from marvis.core.workflow import create_workflow, run_workflow, list_workflows, builtin_templates

直接跑只读模板（不写入工作流存档）：
    from marvis.core.workflow import run_builtin_template
    run_builtin_template("敏感文件卫生", {"root": "samples/hygiene"})
    run_builtin_template("磁盘与大文件巡检", {"root": "samples/disk"})
    run_builtin_template("日志错误摘要", {"root": "samples/logs"})
"""

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from typing import Optional

_PARAM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}")
_PARAM_VALUE = re.compile(r"[\w.\- \u4e00-\u9fff]{0,120}")


def _workflow_dir() -> str:
    from marvis.utils.config import load_config
    return load_config().workflow_dir


def _ensure_dir():
    os.makedirs(_workflow_dir(), exist_ok=True)


def _path(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return os.path.join(_workflow_dir(), f"{safe}.json")


def _subst(text: str, params: Optional[dict]) -> str:
    """替换 {{param}}。参数值拒绝 shell 元字符，避免拼进命令。"""
    if not params:
        return text
    for key, value in params.items():
        if not _PARAM_NAME.fullmatch(str(key)):
            raise ValueError(f"参数名无效: {key}")
        sval = str(value)
        if not _PARAM_VALUE.fullmatch(sval):
            raise ValueError(f"参数 {key} 含有不允许的字符，已拒绝写入命令")
        text = text.replace("{{" + str(key) + "}}", sval)
    return text


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
    for f in os.listdir(_workflow_dir()):
        if f.endswith(".json"):
            with open(os.path.join(_workflow_dir(), f), "r", encoding="utf-8") as fh:
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


HYGIENE_TEMPLATE = "敏感文件卫生"
DISK_TEMPLATE = "磁盘与大文件巡检"
LOG_TEMPLATE = "日志错误摘要"
_TEMPLATE_ALIASES = {
    "hygiene": HYGIENE_TEMPLATE,
    "sensitive-hygiene": HYGIENE_TEMPLATE,
    "disk": DISK_TEMPLATE,
    "large-files": DISK_TEMPLATE,
    "logs": LOG_TEMPLATE,
    "log-errors": LOG_TEMPLATE,
}
_FAILED = {"failed", "error", "timeout"}


def resolve_template_name(name: str) -> str:
    """把 hygiene 这类别名解析成模板名。未知名称原样返回。"""
    return _TEMPLATE_ALIASES.get(str(name).strip(), str(name).strip())


def format_hygiene_report(summary: dict) -> str:
    """人类可读的只读卫生报告。只包含路径和类型，不包含文件正文。"""
    lines = [
        "敏感文件卫生报告",
        f"目录: {summary.get('root', '')}",
        "模式: 只读预览（未删除、未修改任何文件，报告不含密钥正文）",
        f"扫描文件: {summary.get('files_scanned', 0)}",
        f"发现: {summary.get('finding_count', 0)}",
        "",
    ]
    findings = summary.get("findings") or []
    if not findings:
        lines.append("未发现敏感文件名或凭据样式。")
    else:
        for item in findings:
            severity = item.get("severity", "")
            kind = item.get("type", "")
            rel = item.get("file", "")
            detail = item.get("detail", "")
            extra = f" ×{item['count']}" if item.get("count") else ""
            lines.append(f"[{severity}] {kind}  {rel}")
            if detail:
                lines.append(f"    {detail}{extra}")
        lines.append("")
        lines.append("建议: 把凭据移出该目录并加入忽略规则。确认前不要删除；本命令不会改动文件。")
    return "\n".join(lines)


def _write_new_report(path: str, text: str) -> str:
    """把报告写到新文件。目标已存在时拒绝覆盖。"""
    if not isinstance(path, str) or not path.strip() or "\x00" in path or "\n" in path or "\r" in path:
        raise ValueError("报告路径无效")
    dest = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(dest)
    if not parent or not os.path.isdir(parent):
        raise ValueError(f"报告目录不存在: {parent}")
    if os.path.isdir(dest):
        raise ValueError("报告路径是目录")
    if os.path.exists(dest):
        raise ValueError(f"报告文件已存在，未覆盖: {dest}")
    payload = text if text.endswith("\n") else text + "\n"
    with open(dest, "x", encoding="utf-8") as handle:
        handle.write(payload)
    return dest


def _run_steps(name: str, steps: list[dict], params: Optional[dict] = None) -> dict:
    """执行步骤。不写工作流存档。"""
    from marvis.core.security_audit import summarize_sensitive_files

    results = []
    context: dict = {"params": params or {}}

    for i, step in enumerate(steps):
        step_type = step.get("type", "command")
        result = {"step": i + 1, "name": step.get("name", f"Step {i+1}"), "type": step_type}

        try:
            if step_type == "command":
                cmd = _subst(step.get("command", ""), params)
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                      encoding="utf-8", timeout=60)
                result["status"] = "success" if proc.returncode == 0 else "failed"
                result["output"] = proc.stdout[:500] if proc.stdout else ""
                result["error"] = proc.stderr[:200] if proc.stderr else ""
                context[f"step_{i+1}_output"] = proc.stdout.strip()

            elif step_type == "python":
                code = _subst(step.get("code", ""), params)
                proc = subprocess.run([os.environ.get("MARVIS_PYTHON", "python3"), "-c", code],
                                      capture_output=True,
                                      text=True, encoding="utf-8", timeout=60)
                result["status"] = "success" if proc.returncode == 0 else "failed"
                result["output"] = proc.stdout[:500] if proc.stdout else ""

            elif step_type == "powershell":
                ps = _subst(step.get("command", ""), params)
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

            elif step_type == "hygiene":
                root = (params or {}).get("root")
                if not isinstance(root, str) or not root.strip():
                    raise ValueError("需要 --root 指向要扫描的目录，例如 samples/hygiene")
                summary = summarize_sensitive_files(root)
                report = format_hygiene_report(summary)
                output = (params or {}).get("output")
                if output:
                    dest = os.path.abspath(os.path.expanduser(str(output)))
                    report = f"{report}\n\n报告已写入: {dest}"
                    context["report_path"] = _write_new_report(str(output), report)
                context["hygiene_report"] = report
                context["hygiene_summary"] = summary
                result["status"] = "success"
                result["output"] = (
                    f"扫描 {summary['files_scanned']} 个文件，发现 {summary['finding_count']} 项"
                )

            elif step_type == "disk":
                from marvis.core.disk_inspect import format_disk_report, inspect_large_files

                root = (params or {}).get("root")
                if not isinstance(root, str) or not root.strip():
                    raise ValueError("需要 --root 指向要巡检的目录，例如 samples/disk")
                disk_params = params or {}
                summary = inspect_large_files(
                    root,
                    top=disk_params.get("top"),
                    older_than_days=disk_params.get("days"),
                    min_old_bytes=disk_params.get("min_bytes"),
                    max_depth=disk_params.get("max_depth"),
                    max_entries=disk_params.get("max_entries"),
                    timeout_seconds=disk_params.get("timeout_seconds"),
                )
                report = format_disk_report(summary)
                output = disk_params.get("output")
                if output:
                    dest = os.path.abspath(os.path.expanduser(str(output)))
                    report = f"{report}\n\n报告已写入: {dest}"
                    context["report_path"] = _write_new_report(str(output), report)
                context["disk_report"] = report
                context["disk_summary"] = summary
                result["status"] = "success"
                result["output"] = f"已统计 {summary.get('files_seen', 0)} 个文件，未修改目录"

            elif step_type == "logs":
                from marvis.core.log_summary import format_log_report, summarize_logs

                root = (params or {}).get("root")
                if not isinstance(root, str) or not root.strip():
                    raise ValueError("需要 --root 指向要摘要的日志目录，例如 samples/logs")
                log_params = params or {}
                summary = summarize_logs(
                    root,
                    top=log_params.get("top"),
                    newer_than_days=log_params.get("days"),
                    max_depth=log_params.get("max_depth"),
                    max_files=log_params.get("max_files"),
                    max_entries=log_params.get("max_entries"),
                    max_lines=log_params.get("max_lines"),
                    max_bytes_per_file=log_params.get("max_bytes_per_file"),
                    max_total_bytes=log_params.get("max_total_bytes"),
                    timeout_seconds=log_params.get("timeout_seconds"),
                )
                report = format_log_report(summary)
                output = log_params.get("output")
                if output:
                    dest = os.path.abspath(os.path.expanduser(str(output)))
                    report = f"{report}\n\n报告已写入: {dest}"
                    context["report_path"] = _write_new_report(str(output), report)
                context["logs_report"] = report
                context["logs_summary"] = summary
                result["status"] = "success"
                result["output"] = (
                    f"已读取 {summary.get('files_read', 0)} 个日志，"
                    f"错误 {summary.get('error_events', 0)}，"
                    f"警告 {summary.get('warning_events', 0)}，未修改文件"
                )

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

        if step.get("stop_on_error", True) and result.get("status") in _FAILED:
            break

    payload = {
        "workflow": name,
        "total_steps": len(steps),
        "executed_steps": len(results),
        "results": results,
    }
    summary = context.get("hygiene_summary")
    if isinstance(summary, dict):
        payload.update({
            "preview": True,
            "deleted": False,
            "root": summary.get("root"),
            "files_scanned": summary.get("files_scanned", 0),
            "finding_count": summary.get("finding_count", 0),
            "by_severity": summary.get("by_severity") or {},
            "findings": summary.get("findings") or [],
            "report": context.get("hygiene_report") or "",
        })
        if context.get("report_path"):
            payload["report_path"] = context["report_path"]
    disk = context.get("disk_summary")
    if isinstance(disk, dict):
        payload.update({
            "preview": True,
            "deleted": False,
            "modified": False,
            "moved": False,
            "root": disk.get("root"),
            "filesystem": disk.get("filesystem") or {},
            "top": disk.get("top"),
            "older_than_days": disk.get("older_than_days"),
            "min_old_bytes": disk.get("min_old_bytes"),
            "files_seen": disk.get("files_seen", 0),
            "dirs_seen": disk.get("dirs_seen", 0),
            "scanned_bytes": disk.get("scanned_bytes", 0),
            "symlink_count": disk.get("symlink_count", 0),
            "outside_symlink_count": disk.get("outside_symlink_count", 0),
            "error_count": disk.get("error_count", 0),
            "skipped": disk.get("skipped") or [],
            "partial": disk.get("partial", False),
            "limit_hits": disk.get("limit_hits") or [],
            "limits": disk.get("limits") or {},
            "largest_files": disk.get("largest_files") or [],
            "largest_dirs": disk.get("largest_dirs") or [],
            "old_large_files": disk.get("old_large_files") or [],
            "old_large_count": disk.get("old_large_count", 0),
            "report": context.get("disk_report") or "",
        })
        if context.get("report_path"):
            payload["report_path"] = context["report_path"]
    logs = context.get("logs_summary")
    if isinstance(logs, dict):
        payload.update({
            "preview": True,
            "deleted": False,
            "modified": False,
            "moved": False,
            "root": logs.get("root"),
            "top": logs.get("top"),
            "newer_than_days": logs.get("newer_than_days"),
            "files_read": logs.get("files_read", 0),
            "log_files_seen": logs.get("log_files_seen", 0),
            "dirs_seen": logs.get("dirs_seen", 0),
            "lines_read": logs.get("lines_read", 0),
            "bytes_read": logs.get("bytes_read", 0),
            "non_log_skipped": logs.get("non_log_skipped", 0),
            "compressed_skipped": logs.get("compressed_skipped", 0),
            "binary_skipped": logs.get("binary_skipped", 0),
            "tailed_files": logs.get("tailed_files", 0),
            "symlink_count": logs.get("symlink_count", 0),
            "outside_symlink_count": logs.get("outside_symlink_count", 0),
            "error_count": logs.get("error_count", 0),
            "skipped": logs.get("skipped") or [],
            "overflow": logs.get("overflow", 0),
            "partial": logs.get("partial", False),
            "limit_hits": logs.get("limit_hits") or [],
            "limits": logs.get("limits") or {},
            "levels": logs.get("levels") or {},
            "fatal_count": logs.get("fatal_count", 0),
            "error_events": logs.get("error_events", 0),
            "warning_events": logs.get("warning_events", 0),
            "errors": logs.get("errors") or [],
            "warnings": logs.get("warnings") or [],
            "busiest_files": logs.get("busiest_files") or [],
            "report": context.get("logs_report") or "",
        })
        if context.get("report_path"):
            payload["report_path"] = context["report_path"]
    return payload


def run_workflow(name: str, params: Optional[dict] = None) -> dict:
    """执行已保存的工作流，支持 {{param}} 模板替换"""
    wf = get_workflow(name)
    if not wf:
        return {"error": f"工作流不存在: {name}"}

    payload = _run_steps(name, wf["steps"], params)

    wf["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wf["run_count"] = wf.get("run_count", 0) + 1
    with open(_path(name), "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
    return payload


def run_builtin_template(name: str, params: Optional[dict] = None) -> dict:
    """直接运行内置模板，不写入 ~/.marvis/workflows。

    只有标记 runnable 的模板可以走这条路径。带删除或系统改动的模板会被拒绝。
    """
    templates = builtin_templates()
    resolved = resolve_template_name(name)
    tpl = templates.get(resolved)
    if tpl is None:
        known = "、".join(templates)
        return {"error": f"模板不存在: {name}。可选: {known}"}
    if not tpl.get("runnable"):
        runnable = [item for item, body in templates.items() if body.get("runnable")]
        listed = "、".join(runnable) or "无"
        return {
            "error": (
                f"模板「{resolved}」不能直接运行（可能包含会改动文件或系统的步骤）。"
                f"可直接运行: {listed}"
            )
        }
    payload = _run_steps(resolved, tpl["steps"], params)
    payload["template"] = resolved
    failed = next((step for step in payload["results"] if step.get("status") in _FAILED), None)
    if failed:
        payload["error"] = failed.get("error") or f"步骤失败: {failed.get('name')}"
    return payload


def format_templates(templates: Optional[dict] = None) -> str:
    """内置模板的可读列表。可直接运行的排在前面。"""
    templates = templates if templates is not None else builtin_templates()
    lines = ["内置工作流模板", ""]
    items = sorted(templates.items(), key=lambda kv: (not kv[1].get("runnable"), kv[0]))
    for name, tpl in items:
        flag = "  [可直接运行]" if tpl.get("runnable") else ""
        lines.append(f"{name}{flag}")
        description = tpl.get("description") or ""
        if description:
            lines.append(f"  {description}")
        usage = tpl.get("usage")
        if usage:
            lines.append(f"  {usage}")
        aliases = tpl.get("aliases") or []
        if aliases:
            lines.append(f"  别名: {', '.join(aliases)}")
        lines.append(f"  步骤: {len(tpl.get('steps') or [])}")
        lines.append("")
    lines.append("直接运行只读模板不会改动文件。含删除或系统改动的模板不能用 --template 启动。")
    return "\n".join(lines)


def builtin_templates() -> dict:
    """内置工作流模板"""
    return {
        HYGIENE_TEMPLATE: {
            "description": "扫描目录中的敏感文件名和凭据样式，打印可读报告。只读，不删除，不输出密钥正文。",
            "runnable": True,
            "aliases": ["hygiene", "sensitive-hygiene"],
            "usage": "marvis workflow run --template 敏感文件卫生 --root samples/hygiene",
            "steps": [
                {"type": "hygiene", "name": "扫描并生成报告"},
                {"type": "notify", "name": "完成", "message": "敏感文件卫生报告已生成（只读，未改动任何文件）"},
            ],
        },
        DISK_TEMPLATE: {
            "description": "查看目录所在磁盘的用量，以及目录内最大的文件、子目录和久未修改的大文件。只读，不删除、不移动、不修改。",
            "runnable": True,
            "aliases": ["disk", "large-files"],
            "usage": "marvis workflow run --template 磁盘与大文件巡检 --root samples/disk",
            "steps": [
                {"type": "disk", "name": "统计磁盘与大文件"},
                {"type": "notify", "name": "完成", "message": "磁盘与大文件巡检报告已生成（只读，未改动任何文件）"},
            ],
        },
        LOG_TEMPLATE: {
            "description": "汇总目录里日志的致命、错误和警告，合并重复项，并打码令牌和密码。只读，不删除、不修改、不执行。",
            "runnable": True,
            "aliases": ["logs", "log-errors"],
            "usage": "marvis workflow run --template 日志错误摘要 --root samples/logs",
            "steps": [
                {"type": "logs", "name": "摘要日志错误"},
                {"type": "notify", "name": "完成", "message": "日志错误摘要已生成（只读，未改动任何文件）"},
            ],
        },
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
