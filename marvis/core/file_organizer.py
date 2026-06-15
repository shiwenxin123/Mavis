"""
Marvis 文件智能整理 — 分析、归类、去重、清理。

可导入使用：
    from marvis.core.file_organizer import scan_files, analyze_structure, find_duplicates
"""

import hashlib
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional

from marvis.utils.fs import format_size

TYPE_MAP = {
    "文档": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".wps", ".ppt", ".pptx"},
    "表格": {".xls", ".xlsx", ".csv", ".ods"},
    "图片": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff"},
    "视频": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"},
    "音频": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "代码": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".rb", ".php",
             ".sh", ".ps1", ".html", ".css", ".json", ".yaml", ".yml", ".xml", ".sql"},
    "压缩包": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
    "可执行": {".exe", ".msi", ".dmg", ".deb", ".rpm", ".apk"},
}

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vs", ".BIN",
             "System Volume Information"}
EXT_TEMP = {".tmp", ".temp", ".log", ".cache", ".bak", ".old", ".swp"}


def get_category(ext: str) -> str:
    """根据扩展名获取文件类别"""
    ext = ext.lower()
    for cat, exts in TYPE_MAP.items():
        if ext in exts:
            return cat
    return "其他"


def scan_files(root: str, max_depth: Optional[int] = None) -> list[dict]:
    """扫描目录下所有文件，返回文件信息列表"""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]

        rel_depth = os.path.relpath(dirpath, root).count(os.sep)
        if max_depth is not None and rel_depth >= max_depth:
            dirnames.clear()
            continue

        for f in filenames:
            full = os.path.join(dirpath, f)
            try:
                st = os.stat(full)
                ext = os.path.splitext(f)[1].lower()
                files.append({
                    "path": os.path.abspath(full),
                    "name": f,
                    "ext": ext,
                    "category": get_category(ext),
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                })
            except (PermissionError, OSError):
                continue
    return files


def analyze_structure(files: list[dict]) -> dict:
    """分析文件结构，按类别生成统计"""
    stats: dict = defaultdict(lambda: {"count": 0, "size": 0, "exts": defaultdict(int)})
    for f in files:
        cat = f["category"]
        stats[cat]["count"] += 1
        stats[cat]["size"] += f["size"]
        stats[cat]["exts"][f["ext"]] += 1
    return dict(stats)


def generate_organize_plan(
    files: list[dict], target_dir: str, mode: str = "type"
) -> list[dict]:
    """生成整理计划（预览，不实际执行）"""
    plan = []
    for f in files:
        if mode == "type":
            dest_dir = os.path.join(target_dir, f["category"])
        elif mode == "time":
            mtime = datetime.strptime(f["modified"], "%Y-%m-%d %H:%M:%S")
            dest_dir = os.path.join(target_dir, str(mtime.year), f"{mtime.month:02d}")
        else:
            dest_dir = target_dir

        dest = os.path.join(dest_dir, f["name"])
        if os.path.abspath(f["path"]) != os.path.abspath(dest):
            plan.append({
                "source": f["path"],
                "destination": dest,
                "category": f["category"],
            })
    return plan


def find_duplicates(files: list[dict]) -> list[dict]:
    """基于文件大小+MD5哈希检测重复文件"""
    size_groups: dict = defaultdict(list)
    for f in files:
        size_groups[f["size"]].append(f)

    duplicates = []
    for size, group in size_groups.items():
        if len(group) < 2 or size == 0:
            continue
        hash_groups: dict = defaultdict(list)
        for f in group:
            try:
                with open(f["path"], "rb") as fh:
                    h = hashlib.md5(fh.read()).hexdigest()
                hash_groups[h].append(f)
            except (PermissionError, OSError):
                continue
        for h, hgroup in hash_groups.items():
            if len(hgroup) > 1:
                duplicates.append({
                    "hash": h,
                    "size": format_size(size),
                    "files": [f["path"] for f in hgroup],
                })
    return duplicates


def find_temp_files(files: list[dict]) -> list[dict]:
    """查找临时/缓存文件"""
    return [f for f in files if f["ext"] in EXT_TEMP]


def find_empty_dirs(root: str) -> list[str]:
    """查找空目录"""
    empty = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if not dirnames and not filenames:
            rel = os.path.relpath(dirpath, root)
            if rel == ".":
                continue
            if any(skip in dirpath for skip in SKIP_DIRS):
                continue
            empty.append(dirpath)
    return empty


def organize_summary(root: str, max_depth: Optional[int] = None) -> dict:
    """一站式目录分析总结"""
    files = scan_files(root, max_depth)
    stats = analyze_structure(files)
    total_size = sum(f["size"] for f in files)
    return {
        "root": os.path.abspath(root),
        "file_count": len(files),
        "total_size": total_size,
        "total_size_readable": format_size(total_size),
        "categories": stats,
    }
