"""Marvis MCP Server — 将全部能力暴露为 MCP Tools，适配任何 AI 平台。"""

import json
from typing import Any

from marvis.core.search import search
from marvis.core.doc_analyzer import read_file, contract_review, data_analysis, generate_chart
from marvis.core.file_organizer import scan_files, analyze_structure, find_duplicates, find_empty_dirs, organize_summary
from marvis.core.knowledge_base import build_image_gallery, build_doc_library, search_gallery, search_library
from marvis.core.system_manager import (
    sys_info, net_info, process_list, service_list, disk_usage, port_check, system_clean, net_repair
)
from marvis.core.ocr import ocr_image, search_by_text, scan_and_ocr
from marvis.core.format_converter import convert
from marvis.core.task_scheduler import create_task, list_tasks, run_task, delete_task
from marvis.core.web_monitor import search_web, read_page, monitor_page
from marvis.core.project_scanner import scan_project, generate_readme
from marvis.core.security_audit import full_audit, check_sensitive_files, check_open_ports
from marvis.core.batch_processor import batch_rename, compress_images, merge_pdfs
from marvis.core.workflow import create_workflow, list_workflows, run_workflow, builtin_templates


# ──── Tool handler registry ────

def handle_search_files(args: dict) -> dict:
    """按文件名/大小/时间搜索文件"""
    result = search(
        root=args.get("root", "."),
        mode=args.get("mode", "name"),
        keyword=args.get("keyword"),
        pattern=args.get("pattern"),
        ext=args.get("ext"),
        min_size=args.get("min_size"),
        max_size=args.get("max_size"),
        days=args.get("days"),
        limit=args.get("limit", 50),
    )
    return {"count": len(result), "files": result}


def handle_search_content(args: dict) -> dict:
    """搜索文件内容（关键词/正则）"""
    result = search(
        root=args.get("root", "."),
        mode=args.get("mode", "content"),
        keyword=args.get("keyword"),
        pattern=args.get("pattern"),
        ext=args.get("ext"),
        limit=args.get("limit", 30),
    )
    return {"count": len(result), "matches": result}


def handle_read_document(args: dict) -> dict:
    """读取文档内容"""
    path = args["path"]
    text = read_file(path)
    return {"path": path, "content": text[:10000] if text else None}


def handle_contract_review(args: dict) -> dict:
    """合同审查"""
    text = read_file(args["path"])
    return contract_review(text)


def handle_data_analysis(args: dict) -> dict:
    """数据分析（Excel/CSV）"""
    return data_analysis(args["path"])


def handle_generate_chart(args: dict) -> dict:
    """从数据生成图表"""
    return generate_chart(
        args["path"],
        chart_type=args.get("chart_type", "auto"),
        output_path=args.get("output_path"),
        columns=args.get("columns"),
    )


def handle_organize_files(args: dict) -> dict:
    """分析文件结构"""
    summary = organize_summary(args.get("root", "."), args.get("max_depth"))
    return summary


def handle_find_duplicates(args: dict) -> dict:
    """查找重复文件"""
    root = args.get("root", ".")
    max_depth = args.get("max_depth")
    files = scan_files(root, max_depth)
    dups = find_duplicates(files)
    return {"root": root, "duplicate_groups": len(dups), "duplicates": dups}


def handle_find_empty_dirs(args: dict) -> dict:
    """查找空目录"""
    empty = find_empty_dirs(args.get("root", "."))
    return {"count": len(empty), "directories": empty}


def handle_build_image_gallery(args: dict) -> dict:
    """扫描构建 AI 图库"""
    gallery = build_image_gallery(args.get("root", "."), args.get("max_images", 100))
    return {"count": len(gallery), "images": gallery}


def handle_build_doc_library(args: dict) -> dict:
    """扫描构建文档库"""
    library = build_doc_library(args.get("root", "."), args.get("max_files", 100))
    return {"count": len(library), "documents": library}


def handle_search_gallery(args: dict) -> dict:
    """搜索图库"""
    gallery = build_image_gallery(args.get("root", "."), args.get("max_images", 200))
    results = search_gallery(gallery, keyword=args.get("keyword"))
    return {"count": len(results), "images": results}


def handle_search_library(args: dict) -> dict:
    """搜索文档库"""
    library = build_doc_library(args.get("root", "."), args.get("max_files", 200))
    results = search_library(library, keyword=args.get("keyword"))
    return {"count": len(results), "documents": results}


def handle_system_info(args: dict) -> dict:
    """系统信息"""
    info = sys_info()
    return {"system": json.loads(info) if info else {"error": "无法获取系统信息"}}


def handle_network_info(args: dict) -> dict:
    """网络信息"""
    info = net_info()
    return {"network": json.loads(info) if info else {"error": "无法获取网络信息"}}


def handle_process_list(args: dict) -> dict:
    """进程列表"""
    procs = process_list(args.get("sort_by", "cpu"), args.get("limit", 20))
    return {"processes": json.loads(procs) if procs else []}


def handle_disk_usage(args: dict) -> dict:
    """磁盘使用"""
    usage = disk_usage()
    return {"disks": json.loads(usage) if usage else []}


def handle_port_check(args: dict) -> dict:
    """端口检查"""
    result = port_check(args["port"], args.get("host", "127.0.0.1"))
    return {"port_check": json.loads(result) if result else {}}


def handle_system_clean(args: dict) -> dict:
    """扫描可清理项"""
    result = system_clean()
    return {"clean_items": json.loads(result) if result else []}


def handle_ocr_image(args: dict) -> dict:
    """OCR 识别"""
    text, error = ocr_image(args["path"], args.get("lang", "chi_sim+eng"))
    return {"text": text, "error": error}


def handle_ocr_search(args: dict) -> dict:
    """OCR 搜索"""
    results = scan_and_ocr(
        args.get("root", "."),
        lang=args.get("lang", "chi_sim+eng"),
        max_files=args.get("max_files", 20),
    )
    if args.get("keyword"):
        results = search_by_text(results, args["keyword"])
    return {"count": len(results), "results": results}


def handle_convert_format(args: dict) -> dict:
    """文件格式转换"""
    result = convert(
        args["path"],
        args.get("output_format", "json"),
        args.get("output_path"),
    )
    return {"converted": result}


def handle_web_search(args: dict) -> dict:
    """网页搜索（Bing）"""
    return search_web(args["query"], args.get("count", 10))


def handle_read_webpage(args: dict) -> dict:
    """读取网页"""
    return read_page(args["url"], args.get("max_length", 5000))


def handle_monitor_webpage(args: dict) -> dict:
    """监控网页变化"""
    return monitor_page(args["url"], args.get("keyword"))


def handle_scan_project(args: dict) -> dict:
    """项目扫描"""
    result = scan_project(args.get("root", "."), args.get("max_depth", 5))
    return result


def handle_generate_readme(args: dict) -> dict:
    """生成项目 README"""
    result = scan_project(args.get("root", "."))
    return {"readme": generate_readme(result)}


def handle_security_audit(args: dict) -> dict:
    """安全巡检"""
    return full_audit(args.get("root", "."))


def handle_batch_rename(args: dict) -> dict:
    """批量重命名"""
    results = batch_rename(
        args.get("root", "."),
        pattern=args.get("pattern", "date-prefix"),
        dry_run=args.get("dry_run", True),
        ext=args.get("ext"),
    )
    return {"count": len(results), "changes": results}


def handle_compress_images(args: dict) -> dict:
    """批量压缩图片"""
    results = compress_images(
        args.get("root", "."),
        quality=args.get("quality", 85),
        max_size=args.get("max_size"),
        dry_run=args.get("dry_run", True),
    )
    return {"count": len(results), "results": results}


def handle_merge_pdfs(args: dict) -> dict:
    """合并 PDF"""
    return merge_pdfs(args.get("root", "."), args.get("output_path", "merged.pdf"))


def handle_list_tasks(args: dict) -> dict:
    """列出定时任务"""
    tasks = list_tasks()
    return {"count": len(tasks), "tasks": tasks}


def handle_create_task(args: dict) -> dict:
    """创建定时任务"""
    task = create_task(
        name=args["name"],
        task_type=args["type"],
        command=args.get("command"),
        url=args.get("url"),
        schedule=args.get("schedule"),
        watch_path=args.get("watch_path"),
        description=args.get("description"),
    )
    return task


def handle_run_task(args: dict) -> dict:
    """手动执行任务"""
    return run_task(args["name"])


def handle_delete_task(args: dict) -> dict:
    """删除任务"""
    return {"deleted": delete_task(args["name"])}


def handle_list_workflows(args: dict) -> dict:
    """列出工作流"""
    workflows = list_workflows()
    templates = builtin_templates()
    return {"custom": workflows, "templates": templates}


def handle_run_workflow(args: dict) -> dict:
    """执行工作流"""
    return run_workflow(args["name"], args.get("params"))


def handle_create_workflow(args: dict) -> dict:
    """创建工作流"""
    wf = create_workflow(
        name=args["name"],
        steps=args["steps"],
        description=args.get("description"),
    )
    return wf


# ──── Tool registry ────

TOOL_REGISTRY = {
    "search_files": handle_search_files,
    "search_content": handle_search_content,
    "read_document": handle_read_document,
    "contract_review": handle_contract_review,
    "data_analysis": handle_data_analysis,
    "generate_chart": handle_generate_chart,
    "organize_files": handle_organize_files,
    "find_duplicates": handle_find_duplicates,
    "find_empty_dirs": handle_find_empty_dirs,
    "build_image_gallery": handle_build_image_gallery,
    "build_doc_library": handle_build_doc_library,
    "search_gallery": handle_search_gallery,
    "search_library": handle_search_library,
    "system_info": handle_system_info,
    "network_info": handle_network_info,
    "process_list": handle_process_list,
    "disk_usage": handle_disk_usage,
    "port_check": handle_port_check,
    "system_clean": handle_system_clean,
    "ocr_image": handle_ocr_image,
    "ocr_search": handle_ocr_search,
    "convert_format": handle_convert_format,
    "web_search": handle_web_search,
    "read_webpage": handle_read_webpage,
    "monitor_webpage": handle_monitor_webpage,
    "scan_project": handle_scan_project,
    "generate_readme": handle_generate_readme,
    "security_audit": handle_security_audit,
    "batch_rename": handle_batch_rename,
    "compress_images": handle_compress_images,
    "merge_pdfs": handle_merge_pdfs,
    "list_tasks": handle_list_tasks,
    "create_task": handle_create_task,
    "run_task": handle_run_task,
    "delete_task": handle_delete_task,
    "list_workflows": handle_list_workflows,
    "run_workflow": handle_run_workflow,
    "create_workflow": handle_create_workflow,
}


def call_tool(tool_name: str, arguments: dict) -> dict:
    """统一工具调用入口"""
    handler = TOOL_REGISTRY.get(tool_name)
    if not handler:
        return {"error": f"未知工具: {tool_name}"}
    try:
        return handler(arguments)
    except Exception as e:
        return {"error": str(e)}


# ──── MCP Tool Schema (for server.py) ────

ALL_TOOLS: list[dict] = [
    {
        "name": "search_files",
        "description": "按文件名/大小/时间搜索文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "搜索根目录"},
                "mode": {"type": "string", "enum": ["name", "content", "size", "time", "regex"], "default": "name"},
                "keyword": {"type": "string", "description": "搜索关键词"},
                "ext": {"type": "string", "description": "文件扩展名过滤"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["root"],
        },
    },
    {
        "name": "search_content",
        "description": "搜索文件内容（关键词/正则）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "搜索根目录"},
                "keyword": {"type": "string", "description": "搜索关键词"},
                "pattern": {"type": "string", "description": "正则表达式"},
                "ext": {"type": "string"},
                "limit": {"type": "integer", "default": 30},
            },
            "required": ["root", "keyword"],
        },
    },
    {
        "name": "read_document",
        "description": "读取文档内容（PDF/DOCX/XLSX/TXT/MD）",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件路径"}},
            "required": ["path"],
        },
    },
    {
        "name": "contract_review",
        "description": "合同审查：提取条款、检测风险",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "合同文件路径"}},
            "required": ["path"],
        },
    },
    {
        "name": "data_analysis",
        "description": "数据分析（Excel/CSV），统计、异常、趋势",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "数据文件路径"}},
            "required": ["path"],
        },
    },
    {
        "name": "generate_chart",
        "description": "从 Excel/CSV 数据生成图表",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "chart_type": {"type": "string", "enum": ["line", "bar", "hist", "pie", "scatter", "auto"], "default": "auto"},
                "output_path": {"type": "string"},
                "columns": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["path"],
        },
    },
    {
        "name": "organize_files",
        "description": "分析目录文件结构",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "find_duplicates",
        "description": "查找重复文件（基于哈希）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "find_empty_dirs",
        "description": "查找空目录",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string", "default": "."}},
        },
    },
    {
        "name": "build_image_gallery",
        "description": "扫描构建 AI 图库（按人像/主题/时间/地点）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "max_images": {"type": "integer", "default": 100},
            },
            "required": ["root"],
        },
    },
    {
        "name": "build_doc_library",
        "description": "扫描构建文档库/知识库",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "max_files": {"type": "integer", "default": 100},
            },
            "required": ["root"],
        },
    },
    {
        "name": "search_gallery",
        "description": "搜索图库",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "keyword": {"type": "string"},
                "max_images": {"type": "integer", "default": 200},
            },
            "required": ["root", "keyword"],
        },
    },
    {
        "name": "search_library",
        "description": "搜索文档库",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "keyword": {"type": "string"},
                "max_files": {"type": "integer", "default": 200},
            },
            "required": ["root", "keyword"],
        },
    },
    {
        "name": "system_info",
        "description": "获取系统信息（CPU/内存/磁盘/GPU）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "network_info",
        "description": "获取网络信息（IP/DNS/网关）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "process_list",
        "description": "获取进程列表",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sort_by": {"type": "string", "default": "cpu"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "disk_usage",
        "description": "获取磁盘使用情况",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "port_check",
        "description": "检查端口是否开放",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port": {"type": "integer"},
                "host": {"type": "string", "default": "127.0.0.1"},
            },
            "required": ["port"],
        },
    },
    {
        "name": "system_clean",
        "description": "扫描可清理的系统垃圾文件",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "net_repair",
        "description": "网络修复（刷新DNS/重置Winsock）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ocr_image",
        "description": "对单张图片进行 OCR 文字提取",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "lang": {"type": "string", "default": "chi_sim+eng"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "ocr_search",
        "description": "OCR 扫描图片并按关键词搜索",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "keyword": {"type": "string"},
                "lang": {"type": "string", "default": "chi_sim+eng"},
                "max_files": {"type": "integer", "default": 50},
            },
            "required": ["root", "keyword"],
        },
    },
    {
        "name": "convert_format",
        "description": "文件格式转换（PDF/DOCX/XLSX/CSV/JSON/Markdown）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "format": {"type": "string", "enum": ["json", "csv", "markdown", "text"], "default": "json"},
                "output_path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "web_search",
        "description": "网页搜索",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "count": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_webpage",
        "description": "读取网页内容",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_length": {"type": "integer", "default": 5000},
            },
            "required": ["url"],
        },
    },
    {
        "name": "monitor_webpage",
        "description": "监控网页变化",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "keyword": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "scan_project",
        "description": "项目感知分析（技术栈/依赖/入口/建议）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "max_depth": {"type": "integer", "default": 5},
            },
            "required": ["root"],
        },
    },
    {
        "name": "generate_readme",
        "description": "自动生成项目 README",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}},
            "required": ["root"],
        },
    },
    {
        "name": "security_audit",
        "description": "安全巡检（敏感文件/端口/弱密码/防火墙）",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string", "default": "."}},
        },
    },
    {
        "name": "batch_rename",
        "description": "批量重命名文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "pattern": {"type": "string", "enum": ["date-prefix", "lowercase", "sequential", "clean"], "default": "date-prefix"},
                "ext": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["root"],
        },
    },
    {
        "name": "compress_images",
        "description": "批量压缩图片",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "quality": {"type": "integer", "default": 85},
                "max_size": {"type": "integer"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["root"],
        },
    },
    {
        "name": "merge_pdfs",
        "description": "合并目录下所有 PDF",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "output_path": {"type": "string", "default": "merged.pdf"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "list_tasks",
        "description": "列出定时任务",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_task",
        "description": "创建定时任务",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string", "enum": ["script", "url-ping", "remind", "file-watch"]},
                "command": {"type": "string"},
                "url": {"type": "string"},
                "schedule": {"type": "string"},
                "watch_path": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["name", "type"],
        },
    },
    {
        "name": "run_task",
        "description": "手动执行定时任务",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "delete_task",
        "description": "删除定时任务",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "list_workflows",
        "description": "列出工作流和内置模板",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_workflow",
        "description": "执行工作流",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "create_workflow",
        "description": "创建自定义工作流",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "object"}},
                "description": {"type": "string"},
            },
            "required": ["name", "steps"],
        },
    },
]


def execute_tool(name: str, arguments: dict) -> str:
    """执行 MCP Tool 调用，返回 JSON 字符串"""
    handler = TOOL_REGISTRY.get(name)
    if not handler:
        result = {"error": f"未知工具: {name}"}
    else:
        try:
            result = handler(arguments)
        except Exception as e:
            result = {"error": str(e)}
    return json.dumps(result, ensure_ascii=False, default=str)