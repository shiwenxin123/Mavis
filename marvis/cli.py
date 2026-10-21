"""
Marvis CLI — 命令行入口。

用法:
    marvis doctor
    marvis search <root> [--mode name] [--keyword hello] [--ext .pdf]
    marvis analyze <filepath> [--action contract|analysis|chart|polish]
    marvis organize <root> [--action analyze|duplicates|empty-dirs]
    marvis system <action> [--port 80] [--execute]
    marvis project <root> [--action scan|readme]
    marvis security <root> [--action full|sensitive-files|ports]
    marvis workflow templates
    marvis workflow run --template 敏感文件卫生 --root <dir> [--output report.txt]
    marvis workflow run --template 磁盘与大文件巡检 --root <dir> [--top 10] [--days 90]
    marvis convert <input> [--format json|csv|markdown]
    marvis batch rename <root> [--pattern date-prefix|lowercase|clean]
    marvis ocr <root> [--keyword text]
    marvis web <action> [--query keyword|--url url]
    marvis knowledge <root> [--mode image-gallery|doc-library]
    marvis mcp-server
"""

import json
import os
import sys

from marvis import __version__


def main(argv=None) -> int:
    """主 CLI 入口。返回进程退出码。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Marvis 智能助手 — 文件搜索、文档分析、系统管理、安全巡检",
        prog="marvis",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--local",
        action="store_true",
        help="本地模式：阻止外部网络访问",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    sub.add_parser("doctor", help="检查安装、依赖和运行模式")

    p_search = sub.add_parser("search", help="智能文件搜索")
    p_search.add_argument("root", help="搜索根目录")
    p_search.add_argument("--mode", choices=["name", "content", "size", "time", "regex"], default="name")
    p_search.add_argument("--keyword", "-k")
    p_search.add_argument("--pattern", "-p")
    p_search.add_argument("--ext", "-e")
    p_search.add_argument("--min-size", type=float)
    p_search.add_argument("--max-size", type=float)
    p_search.add_argument("--days", type=int)
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--json", action="store_true")

    p_analyze = sub.add_parser("analyze", help="文档分析")
    p_analyze.add_argument("filepath")
    p_analyze.add_argument("--action", choices=["contract", "analysis", "chart", "polish"], default="contract")
    p_analyze.add_argument("--chart-type", default="auto")
    p_analyze.add_argument("--output", "-o")
    p_analyze.add_argument("--json", action="store_true")

    p_org = sub.add_parser("organize", help="文件整理")
    p_org.add_argument("root")
    p_org.add_argument("--action", choices=["analyze", "duplicates", "empty-dirs"], default="analyze")
    p_org.add_argument("--json", action="store_true")

    p_sys = sub.add_parser("system", help="系统管理")
    p_sys.add_argument("action", choices=[
        "info", "net", "processes", "services", "disk", "port-check",
        "clean", "repair", "firewall", "startup"
    ])
    p_sys.add_argument("--port", type=int)
    p_sys.add_argument("--sort", default="cpu")
    p_sys.add_argument("--limit", type=int, default=20)
    p_sys.add_argument("--execute", action="store_true", help="确认执行网络修复（默认只预览）")
    p_sys.add_argument("--json", action="store_true")

    p_proj = sub.add_parser("project", help="项目分析")
    p_proj.add_argument("root")
    p_proj.add_argument("--action", choices=["scan", "readme", "deps"], default="scan")
    p_proj.add_argument("--json", action="store_true")

    p_sec = sub.add_parser("security", help="安全巡检")
    p_sec.add_argument("root", nargs="?", default=".")
    p_sec.add_argument("--action", choices=["full", "sensitive-files", "ports", "users", "firewall"], default="full")
    p_sec.add_argument("--json", action="store_true")

    p_wf = sub.add_parser("workflow", help="工作流")
    p_wf.add_argument("action", choices=["list", "run", "templates", "create", "delete"])
    p_wf.add_argument("--name", "-n", help="已保存的工作流名称")
    p_wf.add_argument("--template", "-t", help="直接运行内置模板，例如 敏感文件卫生、磁盘与大文件巡检，或别名 hygiene / disk")
    p_wf.add_argument("--root", help="只读模板要扫描的目录，例如 samples/hygiene 或 samples/disk")
    p_wf.add_argument("--output", "-o", help="把可读报告写到新文件；文件已存在则拒绝覆盖")
    p_wf.add_argument("--top", type=int, help="磁盘巡检列出的最大文件和目录数量，默认 10")
    p_wf.add_argument("--days", type=int, help="久未修改的天数，默认 90")
    p_wf.add_argument("--min-bytes", type=int, help="久未修改的大文件最小字节数，默认 1048576（1MB）")
    p_wf.add_argument("--params", help="JSON。create 需要 steps；run 可传参数对象")
    p_wf.add_argument("--json", action="store_true", help="输出 JSON。默认 templates 和卫生报告打印可读文本")

    p_conv = sub.add_parser("convert", help="格式转换")
    p_conv.add_argument("input")
    p_conv.add_argument("--format", "-f", choices=["json", "csv", "markdown", "text"], default="json")
    p_conv.add_argument("--output", "-o")

    p_batch = sub.add_parser("batch", help="批量处理")
    p_batch.add_argument("action", choices=["rename", "compress", "merge-pdf", "encoding"])
    p_batch.add_argument("root")
    p_batch.add_argument("--pattern", default="date-prefix")
    p_batch.add_argument("--quality", type=int, default=85)
    p_batch.add_argument("--output", "-o")
    p_batch.add_argument("--execute", action="store_true", help="确认执行。默认只预览")
    p_batch.add_argument("--json", action="store_true")

    p_ocr = sub.add_parser("ocr", help="图片 OCR")
    p_ocr.add_argument("root")
    p_ocr.add_argument("--keyword", "-k")
    p_ocr.add_argument("--lang", default="chi_sim+eng")
    p_ocr.add_argument("--json", action="store_true")

    p_web = sub.add_parser("web", help="网页工具")
    p_web.add_argument("action", choices=["search", "read", "monitor"])
    p_web.add_argument("--query", "-q")
    p_web.add_argument("--url", "-u")
    p_web.add_argument("--json", action="store_true")

    p_kb = sub.add_parser("knowledge", help="知识库")
    p_kb.add_argument("root")
    p_kb.add_argument("--mode", choices=["image-gallery", "doc-library"], default="doc-library")
    p_kb.add_argument("--action", choices=["build", "search", "stats"], default="build")
    p_kb.add_argument("--keyword", "-k")
    p_kb.add_argument("--json", action="store_true")

    sub.add_parser("mcp-server", help="启动 MCP 服务器")

    args = parser.parse_args(argv)
    if args.local:
        os.environ["MARVIS_MODE"] = "local"
    if not args.command:
        parser.print_help()
        return 0
    try:
        return _dispatch(args)
    except BrokenPipeError:
        return 0
    except Exception as exc:
        _emit({"error": f"命令失败: {exc}"}, failed=True)
        return 1


def _dispatch(args) -> int:
    """路由到对应的命令处理"""
    cmd = args.command

    if cmd == "doctor":
        from marvis.core.doctor import doctor, format_doctor
        report = doctor()
        if getattr(args, "json", False):
            return _output(report, args)
        print(format_doctor(report))
        return 0

    if cmd == "search":
        from marvis.core.search import search
        result = search(
            root=args.root, mode=args.mode, keyword=args.keyword,
            pattern=args.pattern, ext=args.ext,
            min_size_mb=args.min_size or 0,
            max_size_mb=args.max_size or 0,
            days=args.days, limit=args.limit,
        )
        return _output(result, args)

    if cmd == "analyze":
        from marvis.core.doc_analyzer import (
            contract_review, data_analysis, generate_chart, get_last_read_error,
            polish_text, read_file,
        )
        if args.action == "contract":
            text = read_file(args.filepath)
            result = contract_review(text) if text else {"error": get_last_read_error() or "无法读取文件"}
        elif args.action == "analysis":
            result = data_analysis(args.filepath)
        elif args.action == "chart":
            result = generate_chart(args.filepath, args.chart_type, args.output)
        else:
            text = read_file(args.filepath)
            result = polish_text(text) if text else {"error": get_last_read_error() or "无法读取文件"}
        return _output(result, args)

    if cmd == "organize":
        from marvis.core.file_organizer import (
            analyze_structure, find_duplicates, find_empty_dirs, scan_files,
        )
        if args.action == "analyze":
            result = analyze_structure(scan_files(args.root))
        elif args.action == "duplicates":
            result = {"duplicates": find_duplicates(scan_files(args.root))}
        else:
            result = {"empty_dirs": find_empty_dirs(args.root)}
        return _output(result, args)

    if cmd == "system":
        from marvis.core import system_manager as sm
        if args.action == "processes":
            result = sm.process_list(args.sort, args.limit)
        elif args.action == "services":
            result = sm.service_list()
        elif args.action == "port-check":
            result = sm.port_check(args.port) if args.port else {"error": "需要 --port"}
        elif args.action == "repair":
            result = sm.net_repair(execute=bool(args.execute))
        else:
            actions = {
                "info": sm.sys_info,
                "net": sm.net_info,
                "disk": sm.disk_usage,
                "clean": sm.system_clean,
                "firewall": sm.firewall_rules,
                "startup": sm.startup_list,
            }
            result = actions[args.action]()
        return _output(result, args)

    if cmd == "project":
        from marvis.core.project_scanner import generate_readme, parse_dependencies, scan_project
        if args.action == "readme":
            print(generate_readme(scan_project(args.root)))
            return 0
        if args.action == "deps":
            return _output(parse_dependencies(args.root), args)
        return _output(scan_project(args.root), args)

    if cmd == "security":
        from marvis.core.security_audit import (
            check_firewall, check_open_ports, check_sensitive_files,
            check_user_accounts, full_audit,
        )
        if args.action == "full":
            result = full_audit(args.root)
        elif args.action == "sensitive-files":
            result = {"sensitive_files": check_sensitive_files(args.root)}
        elif args.action == "ports":
            result = {"open_ports": check_open_ports()}
        elif args.action == "users":
            result = {"users": check_user_accounts()}
        else:
            result = {"firewall": check_firewall()}
        return _output(result, args)

    if cmd == "workflow":
        from marvis.core.workflow import (
            builtin_templates, create_workflow, delete_workflow, format_templates,
            list_workflows, run_builtin_template, run_workflow,
        )
        if args.action == "list":
            result = {"workflows": list_workflows()}
        elif args.action == "templates":
            result = builtin_templates()
        elif args.action == "run":
            result = _run_workflow_cli(args, run_workflow, run_builtin_template)
        elif args.action == "create":
            result = _create_workflow_cli(args, create_workflow)
        elif args.action == "delete":
            if not args.name:
                result = {"error": "delete 需要 --name"}
            else:
                result = {"name": args.name, "deleted": delete_workflow(args.name)}
        else:
            result = {"error": "未知工作流操作"}
        if args.action == "templates" and not args.json and not (isinstance(result, dict) and "error" in result):
            print(format_templates(result))
            return 0
        if (
            args.action == "run"
            and not args.json
            and isinstance(result, dict)
            and result.get("report")
            and "error" not in result
        ):
            print(result["report"])
            return 0
        return _output(result, args)

    if cmd == "convert":
        from marvis.core.format_converter import convert
        return _output(convert(args.input, args.format, args.output), args)

    if cmd == "batch":
        from marvis.core.batch_processor import (
            batch_rename, compress_images, convert_encoding, merge_pdfs,
        )
        dry_run = not bool(args.execute)
        if args.action == "rename":
            result = {"dry_run": dry_run, "renamed": batch_rename(args.root, args.pattern, dry_run)}
        elif args.action == "compress":
            result = {"dry_run": dry_run, "compressed": compress_images(args.root, args.quality, None, None, dry_run)}
        elif args.action == "merge-pdf":
            result = merge_pdfs(args.root, args.output or "merged.pdf")
        else:
            result = {"dry_run": dry_run, "encoding": convert_encoding(args.root, dry_run=dry_run)}
        return _output(result, args)

    if cmd == "ocr":
        from marvis.core.ocr import scan_and_ocr, search_by_text
        results = scan_and_ocr(args.root, lang=args.lang)
        if args.keyword:
            result = {"matches": search_by_text(results, args.keyword)}
        else:
            result = {"ocr_results": results}
        return _output(result, args)

    if cmd == "web":
        from marvis.core.web_monitor import monitor_page, read_page, search_web
        if args.action == "search" and args.query:
            result = search_web(args.query)
        elif args.action == "read" and args.url:
            result = read_page(args.url)
        elif args.action == "monitor" and args.url:
            result = monitor_page(args.url)
        else:
            result = {"error": "search 需要 --query；read/monitor 需要 --url"}
        return _output(result, args)

    if cmd == "knowledge":
        from marvis.core.knowledge_base import (
            build_doc_library, build_image_gallery, gallery_stats, library_stats,
            search_gallery, search_library,
        )
        if args.mode == "image-gallery":
            gallery = build_image_gallery(args.root)
            if args.action == "search":
                result = {"results": search_gallery(gallery, args.keyword)}
            elif args.action == "stats":
                result = gallery_stats(gallery)
            else:
                result = {"gallery": gallery[:30], "total": len(gallery)}
        else:
            library = build_doc_library(args.root)
            if args.action == "search":
                result = {"results": search_library(library, args.keyword)}
            elif args.action == "stats":
                result = library_stats(library)
            else:
                result = {"library": library[:30], "total": len(library)}
        return _output(result, args)

    if cmd == "mcp-server":
        from marvis.mcp.server import run
        run()
        return 0

    return _output({"error": f"未知命令: {cmd}"}, args)


def _load_json_arg(raw: str | None):
    if not raw:
        return None, None
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, {"error": f"--params 不是合法 JSON: {exc}"}


def _create_workflow_cli(args, create_workflow) -> dict:
    if not args.name:
        return {"error": "create 需要 --name"}
    payload, err = _load_json_arg(args.params)
    if err:
        return err
    if isinstance(payload, list):
        steps, description = payload, ""
    elif isinstance(payload, dict):
        steps = payload.get("steps")
        description = payload.get("description") or ""
    else:
        return {"error": "create 的 --params 需要 JSON 数组，或包含 steps 的对象"}
    if not isinstance(steps, list) or not steps:
        return {"error": "steps 必须是非空数组"}
    return create_workflow(args.name, steps, description)


def _run_workflow_cli(args, run_workflow, run_builtin_template) -> dict:
    if args.template and args.name:
        return {"error": "请只指定 --name 或 --template 之一"}
    params = None
    flagged = args.root or args.output or args.top is not None or args.days is not None or args.min_bytes is not None
    if args.params or flagged:
        params = {}
        if args.params:
            payload, err = _load_json_arg(args.params)
            if err:
                return err
            if not isinstance(payload, dict):
                return {"error": "run 的 --params 必须是 JSON 对象"}
            params.update(payload)
        if args.root:
            params["root"] = args.root
        if args.output:
            params["output"] = args.output
        if args.top is not None:
            params["top"] = args.top
        if args.days is not None:
            params["days"] = args.days
        if args.min_bytes is not None:
            params["min_bytes"] = args.min_bytes
    if args.template:
        return run_builtin_template(args.template, params)
    if not args.name:
        return {"error": "run 需要 --name 或 --template"}
    return run_workflow(args.name, params)


def _emit(result, failed: bool) -> None:
    if isinstance(result, str):
        text = result
    else:
        text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    print(text, file=sys.stderr if failed else sys.stdout)


def _output(result, args) -> int:
    """结构化结果统一打印 JSON。带 error 的结果走 stderr 并返回 1。"""
    failed = isinstance(result, dict) and "error" in result
    _emit(result, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
