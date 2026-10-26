"""
Marvis — 通用 AI 智能助手核心库。

灵感源自腾讯 Marvis 马维斯，提供文件搜索、文档分析、系统管理、
安全巡检、工作流引擎等核心能力。可作为 Python 库导入、CLI 调用
或通过 MCP Server 向任何 AI 平台暴露。
"""

__version__ = "2.1.4"

_LAZY_MODULES = {
    "search": "marvis.core.search",
    "doc_analyzer": "marvis.core.doc_analyzer",
    "file_organizer": "marvis.core.file_organizer",
    "knowledge_base": "marvis.core.knowledge_base",
    "system_manager": "marvis.core.system_manager",
    "ocr": "marvis.core.ocr",
    "format_converter": "marvis.core.format_converter",
    "task_scheduler": "marvis.core.task_scheduler",
    "web_monitor": "marvis.core.web_monitor",
    "project_scanner": "marvis.core.project_scanner",
    "security_audit": "marvis.core.security_audit",
    "batch_processor": "marvis.core.batch_processor",
    "workflow": "marvis.core.workflow",
}

__all__ = ["__version__", *_LAZY_MODULES.keys()]


def __getattr__(name: str):
    import importlib

    target = _LAZY_MODULES.get(name)
    if target is None:
        raise AttributeError(f"module 'marvis' has no attribute {name!r}")
    module = importlib.import_module(target)
    globals()[name] = module
    return module
