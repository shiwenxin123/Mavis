"""安装与运行模式自检。供 `marvis doctor` 和 MCP 工具 doctor 使用。"""

import importlib.util
import platform
import shutil
import sys

from marvis import __version__
from marvis.utils.config import load_config, network_allowed

_OPTIONAL = (
    ("pdfplumber", "pdfplumber", "PDF 文本"),
    ("docx", "python-docx", "Word 文档"),
    ("openpyxl", "openpyxl", "Excel"),
    ("pandas", "pandas", "数据分析"),
    ("matplotlib", "matplotlib", "图表"),
    ("PIL", "Pillow", "图片"),
    ("chardet", "chardet", "编码检测"),
    ("httpx", "httpx", "HTTP 客户端"),
    ("bs4", "beautifulsoup4", "网页解析"),
    ("mcp", "mcp", "MCP 服务器"),
    ("pytesseract", "pytesseract", "OCR Python 绑定"),
)


def doctor() -> dict:
    """返回当前环境能直接用什么、缺什么。不访问网络，不扫描用户文件。"""
    cfg = load_config()
    allowed, reason = network_allowed()
    dependencies = {}
    for module_name, pip_name, purpose in _OPTIONAL:
        dependencies[pip_name] = {
            "installed": importlib.util.find_spec(module_name) is not None,
            "purpose": purpose,
        }
    mode = "local" if not allowed else cfg.mode
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "mode": mode,
        "network_allowed": allowed,
        "network_note": reason or "效率模式：网页工具可以访问外部网络",
        "destructive_ops": "preview",
        "tesseract": shutil.which("tesseract") is not None,
        "dependencies": dependencies,
        "hints": _hints(dependencies, allowed),
    }


def _hints(dependencies: dict, network_allowed_now: bool) -> list[str]:
    hints = [
        "试试: marvis workflow run --template 敏感文件卫生 --root samples/hygiene",
        "试试: marvis search . --keyword README",
        "试试: marvis security . --action sensitive-files",
        "试试: marvis project . --action scan",
        "网络修复等系统改动默认只预览，确认后加 --execute",
    ]
    if not dependencies["mcp"]["installed"]:
        hints.append("启动 MCP: pip install 'marvis[mcp]' && marvis mcp-server")
    if any(
        not info["installed"]
        for name, info in dependencies.items()
        if name not in {"mcp", "pytesseract"}
    ):
        hints.append("文档/图表等增强: pip install 'marvis[full]'")
    if network_allowed_now:
        hints.append("本地隐私模式: marvis --local web search --query 关键词")
    else:
        hints.append("当前为本地模式，web 搜索/读取/监控会直接拒绝")
    return hints


def format_doctor(report: dict) -> str:
    """人类可读的自检结果。"""
    network = "允许" if report.get("network_allowed") else "已阻止"
    lines = [
        f"Marvis {report.get('version', '')}",
        f"Python {report.get('python', '')} · {report.get('platform', '')}",
        f"运行模式: {report.get('mode', '')}（外部网络{network}）",
        "危险操作: 默认预览，需 --execute 才会改系统",
        "",
        "可选依赖",
    ]
    for name, info in (report.get("dependencies") or {}).items():
        mark = "就绪" if info.get("installed") else "缺失"
        lines.append(f"  [{mark}] {name} — {info.get('purpose', '')}")
    tess = "就绪" if report.get("tesseract") else "缺失"
    lines.append(f"  [{tess}] tesseract — OCR 引擎（系统程序）")
    lines.append("")
    lines.append("接下来可以")
    for hint in report.get("hints") or []:
        lines.append(f"  - {hint}")
    if report.get("network_note") and not report.get("network_allowed"):
        lines.append("")
        lines.append(report["network_note"])
    return "\n".join(lines)
