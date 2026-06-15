"""
跨平台文件系统工具。
"""

import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Optional


def format_size(size_bytes: int) -> str:
    """格式化文件大小为人类可读形式"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def file_metadata(path: str) -> dict:
    """获取文件元数据"""
    try:
        st = os.stat(path)
        return {
            "path": os.path.abspath(path),
            "name": os.path.basename(path),
            "ext": os.path.splitext(path)[1].lower(),
            "size_bytes": st.st_size,
            "size_readable": format_size(st.st_size),
            "modified": datetime.fromtimestamp(st.st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "created": datetime.fromtimestamp(st.st_ctime).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "is_dir": stat.S_ISDIR(st.st_mode),
            "is_link": os.path.islink(path),
        }
    except (PermissionError, OSError) as e:
        return {"path": os.path.abspath(path), "error": str(e)}


def find_files(
    root: str,
    pattern: Optional[str] = None,
    ext: Optional[str] = None,
    max_depth: Optional[int] = None,
    limit: int = 200,
    skip_dirs: Optional[set] = None,
) -> list:
    """通用文件查找器"""
    if skip_dirs is None:
        skip_dirs = {
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            ".idea", ".vs", ".BIN", "System Volume Information",
        }

    results = []
    root_depth = len(os.path.normpath(root).split(os.sep))

    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过目录
        dirnames[:] = [
            d for d in dirnames if d not in skip_dirs
        ]

        # 深度限制
        if max_depth is not None:
            current_depth = len(os.path.normpath(dirpath).split(os.sep)) - root_depth
            if current_depth >= max_depth:
                dirnames[:] = []

        for f in filenames:
            # 扩展名过滤
            if ext and not f.lower().endswith(ext.lower()):
                continue
            # 模式过滤
            if pattern and pattern.lower() not in f.lower():
                continue

            full = os.path.join(dirpath, f)
            results.append(full)
            if len(results) >= limit:
                return results

    return results


def safe_read(
    path: str,
    encoding: str = "utf-8",
    max_size_mb: int = 10,
) -> Optional[str]:
    """安全读取文本文件（带大小限制）"""
    try:
        size = os.path.getsize(path)
        if size > max_size_mb * 1024 * 1024 or size == 0:
            return None
        with open(path, "r", encoding=encoding, errors="ignore") as f:
            return f.read()
    except (PermissionError, OSError, UnicodeDecodeError):
        return None


def safe_read_lines(
    path: str,
    encoding: str = "utf-8",
    max_size_mb: int = 10,
) -> Optional[list]:
    """安全读取文本文件行（带大小限制）"""
    try:
        size = os.path.getsize(path)
        if size > max_size_mb * 1024 * 1024 or size == 0:
            return None
        with open(path, "r", encoding=encoding, errors="ignore") as f:
            return f.readlines()
    except (PermissionError, OSError, UnicodeDecodeError):
        return None
