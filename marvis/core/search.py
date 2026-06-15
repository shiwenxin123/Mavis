"""
Marvis 智能文件搜索 — 按文件名/内容/大小/时间/正则搜索本地文件。

可用作 Python 库直接导入，也可通过 MCP Tool 或 CLI 调用。
"""

import os
import re
from datetime import datetime, timedelta
from typing import Optional

from marvis.utils.fs import file_metadata, format_size
from marvis.utils.config import MarvisConfig

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".idea", ".vs", ".BIN", "System Volume Information",
}


def search_by_name(
    root: str,
    pattern: str,
    ext: Optional[str] = None,
    limit: int = 50,
    skip_dirs: Optional[set] = None,
) -> list[dict]:
    """按文件名模式搜索"""
    if skip_dirs is None:
        skip_dirs = SKIP_DIRS
    results = []
    regex = re.compile(re.escape(pattern), re.IGNORECASE)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            if regex.search(f):
                if ext and not f.lower().endswith(ext.lower()):
                    continue
                full = os.path.join(dirpath, f)
                results.append(file_metadata(full))
                if len(results) >= limit:
                    return results
    return results


def search_by_content(
    root: str,
    keyword: str,
    ext: Optional[str] = None,
    max_size_mb: int = 10,
    encoding: str = "utf-8",
    limit: int = 50,
    skip_dirs: Optional[set] = None,
) -> list[dict]:
    """按文件内容搜索关键词"""
    if skip_dirs is None:
        skip_dirs = SKIP_DIRS
    results = []
    max_bytes = max_size_mb * 1024 * 1024
    keyword_lower = keyword.lower()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(full)
                if size > max_bytes or size == 0:
                    continue
                with open(full, "r", encoding=encoding, errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if keyword_lower in line.lower():
                            results.append({
                                **file_metadata(full),
                                "match_line": i,
                                "match_text": line.strip()[:200],
                            })
                            break
                if len(results) >= limit:
                    return results
            except (PermissionError, OSError):
                continue
    return results


def search_by_size(
    root: str,
    min_mb: float = 0,
    max_mb: float = 0,
    ext: Optional[str] = None,
    limit: int = 50,
    skip_dirs: Optional[set] = None,
) -> list[dict]:
    """按文件大小搜索"""
    if skip_dirs is None:
        skip_dirs = SKIP_DIRS
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(full)
                size_mb = size / (1024 * 1024)
                if min_mb and size_mb < min_mb:
                    continue
                if max_mb and size_mb > max_mb:
                    continue
                results.append(file_metadata(full))
                if len(results) >= limit:
                    return results
            except (PermissionError, OSError):
                continue
    return results


def search_by_time(
    root: str,
    days: Optional[int] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    ext: Optional[str] = None,
    limit: int = 50,
    skip_dirs: Optional[set] = None,
) -> list[dict]:
    """按修改时间搜索文件

    Args:
        days: 最近 N 天
        after: 此日期之后 (YYYY-MM-DD)
        before: 此日期之前 (YYYY-MM-DD)
    """
    if skip_dirs is None:
        skip_dirs = SKIP_DIRS
    results = []
    now = datetime.now()

    after_dt = datetime.strptime(after, "%Y-%m-%d") if after else None
    before_dt = datetime.strptime(before, "%Y-%m-%d") if before else None

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(full))
                if days and (now - mtime).days > days:
                    continue
                if after_dt and mtime < after_dt:
                    continue
                if before_dt and mtime > before_dt:
                    continue
                results.append(file_metadata(full))
                if len(results) >= limit:
                    return results
            except (PermissionError, OSError):
                continue
    return results


def search_by_regex(
    root: str,
    pattern: str,
    ext: Optional[str] = None,
    max_size_mb: int = 10,
    limit: int = 50,
    skip_dirs: Optional[set] = None,
) -> list[dict]:
    """按正则表达式搜索文件内容"""
    if skip_dirs is None:
        skip_dirs = SKIP_DIRS
    results = []
    max_bytes = max_size_mb * 1024 * 1024
    regex = re.compile(pattern, re.IGNORECASE)

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(full)
                if size > max_bytes or size == 0:
                    continue
                with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if regex.search(line):
                            results.append({
                                **file_metadata(full),
                                "match_line": i,
                                "match_text": line.strip()[:200],
                            })
                            break
                if len(results) >= limit:
                    return results
            except (PermissionError, OSError):
                continue
    return results


def search(
    root: str,
    mode: str = "name",
    keyword: Optional[str] = None,
    pattern: Optional[str] = None,
    ext: Optional[str] = None,
    min_size_mb: float = 0,
    max_size_mb: float = 0,
    days: Optional[int] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    limit: int = 50,
    config: Optional[MarvisConfig] = None,
) -> dict:
    """统一搜索入口，根据 mode 分发到具体搜索方法。

    返回 {"results": [...], "count": N, "mode": str}
    """
    if not os.path.isdir(root):
        return {"error": f"目录不存在: {root}", "results": [], "count": 0}

    cfg = config or MarvisConfig()

    mode_map = {
        "name": lambda: search_by_name(root, keyword or "", ext, limit,
                                       skip_dirs=cfg.skip_dirs),
        "content": lambda: search_by_content(root, keyword or "", ext,
                                              cfg.search_max_size_mb,
                                              cfg.search_encoding, limit,
                                              skip_dirs=cfg.skip_dirs),
        "size": lambda: search_by_size(root, min_size_mb, max_size_mb, ext, limit,
                                       skip_dirs=cfg.skip_dirs),
        "time": lambda: search_by_time(root, days, after, before, ext, limit,
                                       skip_dirs=cfg.skip_dirs),
        "regex": lambda: search_by_regex(root, pattern or "", ext,
                                          cfg.search_max_size_mb, limit,
                                          skip_dirs=cfg.skip_dirs),
    }

    if mode not in mode_map:
        return {"error": f"不支持的搜索模式: {mode}", "results": [], "count": 0}

    results = mode_map[mode]()
    return {"results": results[:limit], "count": len(results), "mode": mode}


# CLI 入口（保持向后兼容）
if __name__ == "__main__":
    import argparse, json, sys
    parser = argparse.ArgumentParser(description="Marvis 智能文件搜索")
    parser.add_argument("root", help="搜索根目录")
    parser.add_argument("--mode", choices=["name", "content", "size", "time", "regex"],
                        default="name")
    parser.add_argument("--keyword", "-k")
    parser.add_argument("--pattern", "-p")
    parser.add_argument("--ext", "-e")
    parser.add_argument("--min-size", type=float)
    parser.add_argument("--max-size", type=float)
    parser.add_argument("--days", type=int)
    parser.add_argument("--after")
    parser.add_argument("--before")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    res = search(
        root=args.root,
        mode=args.mode,
        keyword=args.keyword,
        pattern=args.pattern,
        ext=args.ext,
        min_size_mb=args.min_size or 0,
        max_size_mb=args.max_size or 0,
        days=args.days,
        after=args.after,
        before=args.before,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        if res.get("error"):
            print(res["error"], file=sys.stderr)
            sys.exit(1)
        results = res["results"]
        if not results:
            print("未找到匹配文件。")
        else:
            print(f"找到 {len(results)} 个文件:\n")
            for r in results:
                print(f"  {r['path']}")
                print(f"    大小: {r.get('size_readable', 'N/A')}  修改: {r.get('modified', 'N/A')}")
                if "match_text" in r:
                    print(f"    匹配 (行{r['match_line']}): {r['match_text']}")
                print()
