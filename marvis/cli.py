"""
Marvis CLI — 命令行入口。

用法:
    marvis search <root> [--mode name] [--keyword hello] [--ext .pdf]
    marvis analyze <filepath> [--action contract|analysis|chart|polish]
    marvis organize <root> [--action analyze|duplicates|empty-dirs]
    marvis system <action> [--port 80]
    marvis project <root> [--action scan|readme]
    marvis security <root> [--action full|sensitive-files|ports]
    marvis workflow <action> [--name myflow]
    marvis convert <input> [--format json|csv|markdown]
    marvis batch rename <root> [--pattern date-prefix|lowercase|clean]
    marvis ocr <root> [--keyword text]
    marvis web <action> [--query keyword|--url url]
    marvis knowledge <root> [--mode image-gallery|doc-library]
    marvis mcp-server
"""

import json
import sys


def main():
    """主 CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Marvis 智能助手 — 文件搜索、文档分析、系统管理、安全巡检",
        prog="marvis"
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # search
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

    # analyze
    p_analyze = sub.add_parser("analyze", help="文档分析")
    p_analyze.add_argument("filepath")
    p_analyze.add_argument("--action", choices=["contract", "analysis", "chart", "polish"], default="contract")
    p_analyze.add_argument("--chart-type", default="auto")
    p_analyze.add_argument("--output", "-o")
    p_analyze.add_argument("--json", action="store_true")

    # organize
    p_org = sub.add_parser("organize", help="文件整理")
    p_org.add_argument("root")
    p_org.add_argument("--action", choices=["analyze", "duplicates", "empty-dirs"], default="analyze")
    p_org.add_argument("--json", action="store_true")

    # system
    p_sys = sub.add_parser("system", help="系统管理")
    p_sys.add_argument("action", choices=[
        "info", "net", "processes", "services", "disk", "port-check",
        "clean", "repair", "firewall", "startup"
    ])
    p_sys.add_argument("--port", type=int)
    p_sys.add_argument("--sort", default="cpu")
    p_sys.add_argument("--limit", type=int, default=20)
    p_sys.add_argument("--json", action="store_true")

    # project
    p_proj = sub.add_parser("project", help="项目分析")
    p_proj.add_argument("root")
    p_proj.add_argument("--action", choices=["scan", "readme", "deps"], default="scan")
    p_proj.add_argument("--json", action="store_true")

    # security
    p_sec = sub.add_parser("security", help="安全巡检")
    p_sec.add_argument("root", nargs="?", default=".")
    p_sec.add_argument("--action", choices=["full", "sensitive-files", "ports", "users", "firewall"], default="full")
    p_sec.add_argument("--json", action="store_true")

    # workflow
    p_wf = sub.add_parser("workflow", help="工作流")
    p_wf.add_argument("action", choices=["list", "run", "templates", "create", "delete"])
    p_wf.add_argument("--name", "-n")
    p_wf.add_argument("--params")
    p_wf.add_argument("--json", action="store_true")

    # convert
    p_conv = sub.add_parser("convert", help="格式转换")
    p_conv.add_argument("input")
    p_conv.add_argument("--format", "-f", choices=["json", "csv", "markdown", "text"], default="json")
    p_conv.add_argument("--output", "-o")

    # batch
    p_batch = sub.add_parser("batch", help="批量处理")
    p_batch.add_argument("action", choices=["rename", "compress", "merge-pdf", "encoding"])
    p_batch.add_argument("root")
    p_batch.add_argument("--pattern", default="date-prefix")
    p_batch.add_argument("--quality", type=int, default=85)
    p_batch.add_argument("--output", "-o")
    p_batch.add_argument("--execute", action="store_true")
    p_batch.add_argument("--json", action="store_true")

    # ocr
    p_ocr = sub.add_parser("ocr", help="图片 OCR")
    p_ocr.add_argument("root")
    p_ocr.add_argument("--keyword", "-k")
    p_ocr.add_argument("--lang", default="chi_sim+eng")
    p_ocr.add_argument("--json", action="store_true")

    # web
    p_web = sub.add_parser("web", help="网页工具")
    p_web.add_argument("action", choices=["search", "read", "monitor"])
    p_web.add_argument("--query", "-q")
    p_web.add_argument("--url", "-u")
    p_web.add_argument("--json", action="store_true")

    # knowledge
    p_kb = sub.add_parser("knowledge", help="知识库")
    p_kb.add_argument("root")
    p_kb.add_argument("--mode", choices=["image-gallery", "doc-library"], default="doc-library")
    p_kb.add_argument("--action", choices=["build", "search", "stats"], default="build")
    p_kb.add_argument("--keyword", "-k")
    p_kb.add_argument("--json", action="store_true")

    # mcp-server
    sub.add_parser("mcp-server", help="启动 MCP 服务器")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Route to handler
    _dispatch(args)


def _dispatch(args):
    """路由到对应的命令处理"""
    cmd = args.command

    if cmd == "search":
        from marvis.core.search import search
        result = search(
            root=args.root, mode=args.mode, keyword=args.keyword,
            pattern=args.pattern, ext=args.ext, min_size_mb=args.min_size,
            max_size_mb=args.max_size, days=args.days, limit=args.limit,
        )
        _output(result, args)

    elif cmd == "analyze":
        from marvis.core.doc_analyzer import read_file, contract_review, data_analysis, generate_chart, polish_text
        if args.action == "contract":
            text = read_file(args.filepath)
            result = contract_review(text) if text else {"error": "无法读取文件"}
        elif args.action == "analysis":
            result = data_analysis(args.filepath)
        elif args.action == "chart":
            result = generate_chart(args.filepath, args.chart_type, args.output)
        elif args.action == "polish":
            text = read_file(args.filepath)
            result = polish_text(text) if text else {"error": "无法读取文件"}
        _output(result, args)

    elif cmd == "organize":
        from marvis.core.file_organizer import scan_files, analyze_structure, find_duplicates, find_empty_dirs
        files = scan_files(args.root)
        if args.action == "analyze":
            result = analyze_structure(files)
        elif args.action == "duplicates":
            result = {"duplicates": find_duplicates(files)}
        elif args.action == "empty-dirs":
            result = {"empty_dirs": find_empty_dirs(args.root)}
        _output(result, args)

    elif cmd == "system":
        from marvis.core import system_manager as sm
        actions = {
            "info": sm.sys_info, "net": sm.net_info, "processes": lambda: sm.process_list(args.sort, args.limit),
            "services": lambda: sm.service_list(), "disk": sm.disk_usage,
            "port-check": lambda: sm.port_check(args.port) if args.port else {"error": "需要 --port"},
            "clean": sm.system_clean, "repair": sm.net_repair,
            "firewall": sm.firewall_rules, "startup": sm.startup_list,
        }
        result = actions.get(args.action, lambda: {"error": f"未知操作: {args.action}"})()
        _output(result, args)

    elif cmd == "project":
        from marvis.core.project_scanner import scan_project, generate_readme, parse_dependencies
        if args.action == "readme":
            scan_result = scan_project(args.root)
            print(generate_readme(scan_result))
        elif args.action == "deps":
            result = parse_dependencies(args.root)
            _output(result, args)
        else:
            result = scan_project(args.root)
            _output(result, args)

    elif cmd == "security":
        from marvis.core.security_audit import full_audit, check_sensitive_files, check_open_ports, check_user_accounts, check_firewall
        if args.action == "full":
            result = full_audit(args.root)
        elif args.action == "sensitive-files":
            result = {"sensitive_files": check_sensitive_files(args.root)}
        elif args.action == "ports":
            result = {"open_ports": check_open_ports()}
        elif args.action == "users":
            result = {"users": check_user_accounts()}
        elif args.action == "firewall":
            result = {"firewall": check_firewall()}
        _output(result, args)

    elif cmd == "workflow":
        from marvis.core.workflow import list_workflows, run_workflow, builtin_templates
        if args.action == "list":
            result = {"workflows": list_workflows()}
        elif args.action == "templates":
            result = builtin_templates()
        elif args.action == "run":
            params = json.loads(args.params) if args.params else None
            result = run_workflow(args.name, params)
        else:
            result = {"error": f"请使用 list/run/templates"}
        _output(result, args)

    elif cmd == "convert":
        from marvis.core.format_converter import convert
        result = convert(args.input, args.format, args.output)
        _output(result, args)

    elif cmd == "batch":
        from marvis.core.batch_processor import batch_rename, compress_images, merge_pdfs, convert_encoding
        dry_run = not getattr(args, "execute", False)
        if args.action == "rename":
            result = {"renamed": batch_rename(args.root, args.pattern, dry_run)}
        elif args.action == "compress":
            result = {"compressed": compress_images(args.root, args.quality, None, None, dry_run)}
        elif args.action == "merge-pdf":
            result = merge_pdfs(args.root, args.output or "merged.pdf")
        elif args.action == "encoding":
            result = {"encoding": convert_encoding(args.root, dry_run=dry_run)}
        _output(result, args)

    elif cmd == "ocr":
        from marvis.core.ocr import scan_and_ocr, search_by_text
        results = scan_and_ocr(args.root, lang=args.lang)
        if args.keyword:
            result = {"matches": search_by_text(results, args.keyword)}
        else:
            result = {"ocr_results": results}
        _output(result, args)

    elif cmd == "web":
        from marvis.core.web_monitor import search_web, read_page, monitor_page
        if args.action == "search" and args.query:
            result = search_web(args.query)
        elif args.action == "read" and args.url:
            result = read_page(args.url)
        elif args.action == "monitor" and args.url:
            result = monitor_page(args.url)
        else:
            result = {"error": "需要 --query 或 --url"}
        _output(result, args)

    elif cmd == "knowledge":
        from marvis.core.knowledge_base import (
            build_image_gallery, build_doc_library, search_gallery, search_library,
            gallery_stats, library_stats,
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
        _output(result, args)

    elif cmd == "mcp-server":
        from marvis.mcp.server import run
        run()


def _output(result, args):
    """输出结果"""
    if hasattr(args, "json") and args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        if isinstance(result, dict):
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        elif isinstance(result, list):
            for item in result:
                print(json.dumps(item, ensure_ascii=False, default=str))
        else:
            print(result)


def _output(result, args):
    """输出字符串结果（系统命令类）"""
    if hasattr(args, "json") and args.json:
        try:
            data = json.loads(result) if isinstance(result, str) else result
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        except (json.JSONDecodeError, TypeError):
            print(result)
    else:
        print(result)


if __name__ == "__main__":
    main()
